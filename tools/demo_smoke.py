"""Demo smoke test: start the real API on the precomputed cache and check every decision endpoint.

    python tools/demo_smoke.py --bundle <bundle> --car-distances <od_car_distances.csv> --car-distances-sha256 <sha>

Starts citypilot.api.create_app (routing + decision on the M-supplement model, data/cache) with uvicorn on
127.0.0.1, then for P and B calls /state, /optimize (defaults and N_a 5 / B_h 105), /compare_ayna, /stress,
/remove and /co2 over HTTP. Answers are checked against outputs/m_results_dc34c5b.json where it has a value;
timings are printed. Exit code 1 if any check fails.
"""
import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CONFIG = ROOT / "supplements" / "m_services_v1" / "config"
RESULTS = ROOT / "outputs" / "m_results_dc34c5b.json"
TOL = 1e-6


# Coverage the CO2 panel must show (k of n restored journeys without a modelled car distance). Not in
# m_results_dc34c5b.json (it predates car_distance_coverage); fixed from Celal's original od_car_distances.csv.
EXPECTED_COVERAGE = {"P recommendation": (36, 750), "AYNA reference": (41, 882), "B recommendation": (0, 0)}
ALTERNATIVES_SHOWN = 3  # the optimiser reports the top 3; the expected file lists ties beyond them


class Checks:
    def __init__(self):
        self.rows = []  # (call, label, ok, detail)

    def check(self, call, label, ok, detail=""):
        self.rows.append((call, label, bool(ok), detail))

    def same(self, call, label, got, want):
        ok = (abs(got - want) <= TOL) if isinstance(want, float) and isinstance(got, (int, float)) else got == want
        self.check(call, label, ok, "" if ok else f"got {got!r}, want {want!r}")

    @property
    def failures(self):
        return sum(not ok for _, _, ok, _ in self.rows)


def package_values(p):
    return {"candidate_ids": p["candidate_ids"], "within_t": p["within_t"], "capped_time_sum": p["capped_time_sum"],
            "bus_hours": p["bus_hours"]}


def same_package(c, call, label, got, want):
    for k in ("candidate_ids", "within_t", "capped_time_sum", "bus_hours"):
        c.same(call, f"{label} {k}", got.get(k), want.get(k))


def collect(client):
    """Every demo call over HTTP: name -> (seconds, answer)."""
    out = {}

    def call(name, method, path, body=None):
        started = time.perf_counter()
        r = client.request(method, path, json=body)
        seconds = time.perf_counter() - started
        if r.status_code != 200:
            raise RuntimeError(f"{name}: {method} {path} {body} -> {r.status_code} {r.text[:300]}")
        out[name] = (seconds, r.json())
        return r.json()

    call("state", "GET", "/decision/state")
    for p in ("P", "B"):
        rec = call(f"optimize {p} defaults", "POST", "/decision/optimize", {"B_h": 30, "K": 2.0, "N_a": 3, "profile": p})
        call(f"optimize {p} N_a 5, B_h 105", "POST", "/decision/optimize", {"B_h": 105, "K": 2.0, "N_a": 5, "profile": p})
        call(f"compare_ayna {p}", "POST", "/decision/compare_ayna", {"profile": p})
        package = rec["recommendation"]["candidate_ids"]
        call(f"stress {p}", "POST", "/decision/stress", {"package_ids": package, "profile": p})
        call(f"remove {p}", "POST", "/decision/remove", {"package_ids": package, "action_id": package[0], "profile": p})
    return out


def collect_co2(client, ref, out):
    def call(name, body):
        started = time.perf_counter()
        r = client.post("/decision/co2", json=body)
        if r.status_code != 200:
            raise RuntimeError(f"{name}: /co2 {body} -> {r.status_code} {r.text[:300]}")
        out[name] = (time.perf_counter() - started, r.json())

    for name, ids, profile in co2_packages(ref):
        call(f"co2 {name}", {"package_ids": ids, "profile": profile})
        call(f"co2 {name}, 10 km entered", {"package_ids": ids, "profile": profile, "car_trip_km": 10.0})


def co2_packages(ref):
    return (("P recommendation", ref["default"]["P"]["recommendation"]["candidate_ids"], "P"),
            ("AYNA reference", ref["compare_ayna"]["P"]["reference"]["candidate_ids"], "P"),
            ("B recommendation", ref["default"]["B"]["recommendation"]["candidate_ids"], "B"))


def verify(answers, ref, coverage=EXPECTED_COVERAGE) -> Checks:
    """Exact checks of the collected answers against the expected results (pure; no HTTP)."""
    c = Checks()
    a = lambda name: answers[name][1]  # noqa: E731
    s = a("state")
    for p in ("P", "B"):
        c.same("state", f"index {p} loaded, 0 dropped", (s["index"][p]["loaded"], s["index"][p]["dropped"]), (True, 0))
    c.same("state", "objective P / B", (s["objective"]["P"]["value"], s["objective"]["B"]["value"]), ("count", "sum"))
    c.same("state", "N_a_max / B_h_max", (s["N_a_max"], s["B_h_max"]), (5, 120.0))
    for p in ("P", "B"):
        d, cmp = ref["default"][p], ref["compare_ayna"][p]
        name = f"optimize {p} defaults"
        r = a(name)
        same_package(c, name, "recommendation", r["recommendation"], d["recommendation"])
        want = [package_values(x) for x in d["alternatives"]][:ALTERNATIVES_SHOWN]
        got = [package_values(x) for x in r["alternatives"]]
        c.check(name, "alternatives present", bool(got) or not want,
                "" if (got or not want) else f"empty, expected {len(want)}")
        c.same(name, "alternatives count", len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            same_package(c, name, f"alternative {i + 1}", g, w)
        for b, bw in d["baselines"].items():
            same_package(c, name, f"baseline {b}", package_values(r["baselines"][b]["package"]), bw["package"])
        name = f"optimize {p} N_a 5, B_h 105"
        c.same(name, "recommendation = compare_ayna CityPilot package", a(name)["recommendation"]["candidate_ids"],
               cmp["citypilot"]["candidate_ids"])
        name = f"compare_ayna {p}"
        r = a(name)
        c.same(name, "verdict", r["verdict"], cmp["verdict"])
        same_package(c, name, "reference", r["reference"], cmp["reference"])
        same_package(c, name, "CityPilot package", r["optimizer"]["recommendation"], cmp["citypilot"])
        c.same(name, "limits", r["limits"], cmp["limits"])
        name = f"stress {p}"
        r = a(name)
        c.same(name, "status / points", (r["status"], len(r["points"])), ("ok", 9))
        if p == "P":
            want = ref["stress_P"]
            c.same(name, "grid points (level, within_t, bus_hours)",
                   [(q["speed_level"], q["headway_level"], q["within_t"], q["bus_hours"]) for q in r["points"]],
                   [(q["speed_level"], q["headway_level"], q["within_t"], q["bus_hours"]) for q in want["points"]])
            for q, w in zip(r["points"], want["points"]):
                c.same(name, f"capped sum {q['speed_level']}/{q['headway_level']}", q["capped_time_sum"], w["capped_time_sum"])
            c.same(name, "worst point", (r["worst"]["speed_level"], r["worst"]["headway_level"]),
                   (want["worst"]["speed_level"], want["worst"]["headway_level"]))
            c.same(name, "re-optimisation", r["reoptimization"]["recommendation"]["candidate_ids"],
                   want["reoptimization"]["recommendation"])
        name = f"remove {p}"
        r, package = a(name), d["recommendation"]["candidate_ids"]
        c.same(name, "remaining", r["remaining"]["candidate_ids"], [i for i in package if i != package[0]])
        if p == "P":
            c.same(name, "loss within 45", r["loss_within_t"], d["recommendation"]["within_t"] - d["disrupted"]["within_t"])
        else:
            c.same(name, "capped time increase", r["capped_time_increase"], d["recommendation"]["capped_time_sum_reduction"])
    for label, _, _ in co2_packages(ref):
        name = f"co2 {label}"
        r = a(name)
        want = ref["co2"].get({"P recommendation": "P_recommendation", "AYNA reference": "AYNA_reference"}.get(label, ""))
        if want:
            c.same(name, "bus_kg", r["bus_kg"], want["bus_kg"])
            c.same(name, "status", r["status"], want["status"])
        cov = r["car_distance_coverage"]
        c.same(name, "coverage k of n", (cov["missing"], cov["restored"]), tuple(coverage[label]))
        r10 = a(f"co2 {label}, 10 km entered")
        expected = math.ceil(r10["bus_kg"] / (10.0 * r10["car_kg_per_pkm"])) if r10["bus_kg"] > 0 else 0
        c.same(f"co2 {label}, 10 km entered", "break-even from the entered value",
               (r10["status"], r10["break_even_trips"]), ("complete", expected))
    return c


def self_test(answers, ref) -> list[str]:
    """Tampered expectations must make the checks fail; returns the tampers that did NOT fail (should be [])."""
    import copy
    missed = []
    empty = copy.deepcopy(ref)
    empty["default"]["P"]["alternatives"] = []  # expected empty, the API reports alternatives
    if verify(answers, empty).failures == 0:
        missed.append("expected alternatives emptied")
    if verify({**answers, "optimize P defaults": (0, {**answers["optimize P defaults"][1], "alternatives": []})},
              ref).failures == 0:
        missed.append("API alternatives emptied")
    impossible = {**EXPECTED_COVERAGE, "P recommendation": (999, 1)}
    if verify(answers, ref, impossible).failures == 0:
        missed.append("impossible coverage")
    return missed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--car-distances", required=True, type=Path)
    parser.add_argument("--car-distances-sha256", required=True)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()
    import httpx
    import uvicorn

    from citypilot.api import create_app
    from citypilot.api_routing import RoutingSettings
    from citypilot.decision_real import real_backend
    from citypilot.routing_engine import load_model

    timings = {}
    started = time.perf_counter()
    model = load_model(args.bundle, CONFIG)
    timings["model_load_s"] = time.perf_counter() - started
    started = time.perf_counter()
    backend = real_backend(model, ROOT / "data" / "cache", args.car_distances, args.car_distances_sha256)
    app = create_app(RoutingSettings(args.bundle.resolve(), CONFIG.resolve()), decision_backend=backend)
    timings["app_build_s"] = time.perf_counter() - started  # includes index load + compare_ayna precompute
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    started = time.perf_counter()
    thread.start()
    base = f"http://127.0.0.1:{args.port}"
    while True:
        try:
            if httpx.get(base + "/routing/ready", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.perf_counter() - started > 300:
            raise SystemExit("server not ready after 300 s")
        time.sleep(0.2)
    timings["server_ready_s"] = time.perf_counter() - started
    ref = json.loads(args.results.read_text())
    with httpx.Client(base_url=base, timeout=900) as client:
        try:
            answers = collect(client)
            collect_co2(client, ref, answers)
        finally:
            server.should_exit = True
            thread.join(timeout=30)
    checks = verify(answers, ref)
    missed = self_test(answers, ref)
    print(f"startup: model {timings['model_load_s']:.1f} s, app (index + compare_ayna) {timings['app_build_s']:.1f} s, "
          f"server ready {timings['server_ready_s']:.1f} s")
    for name, (seconds, _) in answers.items():
        print(f"{seconds:8.3f} s  {name}")
        for call, label, ok, detail in checks.rows:
            if call == name:
                print(f"           {'ok  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    print(f"{len(answers)} calls, {len(checks.rows)} checks, {checks.failures} failed")
    print("self-test (tampered expectations must fail): " + ("ok" if not missed else f"FAILED, not detected: {missed}"))
    return 1 if checks.failures or missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
