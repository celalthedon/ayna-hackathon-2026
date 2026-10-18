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


class Smoke:
    def __init__(self, client):
        self.client, self.rows, self.failures = client, [], 0

    def call(self, name, method, path, body=None):
        started = time.perf_counter()
        r = self.client.request(method, path, json=body)
        seconds = time.perf_counter() - started
        if r.status_code != 200:
            raise RuntimeError(f"{name}: {method} {path} {body} -> {r.status_code} {r.text[:300]}")
        self.rows.append({"call": name, "s": seconds, "checks": []})
        return r.json()

    def check(self, label, ok, detail=""):
        self.rows[-1]["checks"].append((label, bool(ok), detail))
        self.failures += not ok

    def same(self, label, got, want):
        ok = (abs(got - want) <= TOL) if isinstance(want, float) and isinstance(got, (int, float)) else got == want
        self.check(label, ok, "" if ok else f"got {got!r}, want {want!r}")


def run(smoke, ref):
    s = smoke.call("state", "GET", "/decision/state")
    for p in ("P", "B"):
        smoke.same(f"index {p} loaded, 0 dropped", (s["index"][p]["loaded"], s["index"][p]["dropped"]), (True, 0))
    smoke.same("objective P / B", (s["objective"]["P"]["value"], s["objective"]["B"]["value"]), ("count", "sum"))
    smoke.same("N_a_max", s["N_a_max"], 5)

    for p in ("P", "B"):
        d, c = ref["default"][p], ref["compare_ayna"][p]
        r = smoke.call(f"optimize {p} defaults", "POST", "/decision/optimize",
                       {"B_h": 30, "K": 2.0, "N_a": 3, "profile": p})
        rec = r["recommendation"]
        smoke.same("recommendation", rec["candidate_ids"], d["recommendation"]["candidate_ids"])
        smoke.same("within_t", rec["within_t"], d["recommendation"]["within_t"])
        smoke.same("capped_time_sum", rec["capped_time_sum"], d["recommendation"]["capped_time_sum"])
        smoke.same("bus_hours", rec["bus_hours"], d["recommendation"]["bus_hours"])
        n = min(len(r["alternatives"]), 3)
        smoke.same(f"top-{n} alternatives", [a["candidate_ids"] for a in r["alternatives"][:n]],
                   [a["candidate_ids"] for a in d["alternatives"][:n]])
        for name, b in d["baselines"].items():
            smoke.same(f"baseline {name}", r["baselines"][name]["package"]["candidate_ids"], b["package"]["candidate_ids"])

        r = smoke.call(f"optimize {p} N_a 5, B_h 105", "POST", "/decision/optimize",
                       {"B_h": 105, "K": 2.0, "N_a": 5, "profile": p})
        smoke.same("recommendation = compare_ayna CityPilot package", r["recommendation"]["candidate_ids"],
                   c["citypilot"]["candidate_ids"])

        r = smoke.call(f"compare_ayna {p}", "POST", "/decision/compare_ayna", {"profile": p})
        smoke.same("verdict", r["verdict"], c["verdict"])
        smoke.same("reference", r["reference"], c["reference"])
        smoke.same("CityPilot package", r["optimizer"]["recommendation"]["candidate_ids"], c["citypilot"]["candidate_ids"])
        smoke.same("limits", r["limits"], c["limits"])

        package = d["recommendation"]["candidate_ids"]
        r = smoke.call(f"stress {p} {'+'.join(package)}", "POST", "/decision/stress", {"package_ids": package, "profile": p})
        smoke.same("status / points", (r["status"], len(r["points"])), ("ok", 9))
        if p == "P":
            want = ref["stress_P"]
            got = [(q["speed_level"], q["headway_level"], q["within_t"], q["bus_hours"]) for q in r["points"]]
            smoke.same("grid points (within_t, bus_hours)", got,
                       [(q["speed_level"], q["headway_level"], q["within_t"], q["bus_hours"]) for q in want["points"]])
            smoke.same("grid capped sums", [round(q["capped_time_sum"], 6) for q in r["points"]],
                       [round(q["capped_time_sum"], 6) for q in want["points"]])
            smoke.same("worst point", (r["worst"]["speed_level"], r["worst"]["headway_level"]),
                       (want["worst"]["speed_level"], want["worst"]["headway_level"]))
            smoke.same("re-optimisation", r["reoptimization"]["recommendation"]["candidate_ids"],
                       want["reoptimization"]["recommendation"])
        else:
            smoke.check("no m_results reference for B stress", True,
                        f"worst {r['worst']['speed_level']}/{r['worst']['headway_level']}, re-opt "
                        f"{r['reoptimization']['recommendation']['candidate_ids']}")

        r = smoke.call(f"remove {p} {package[0]}", "POST", "/decision/remove",
                       {"package_ids": package, "action_id": package[0], "profile": p})
        smoke.same("remaining", r["remaining"]["candidate_ids"], [i for i in package if i != package[0]])
        if p == "P":
            smoke.same("loss within 45", r["loss_within_t"],
                       d["recommendation"]["within_t"] - d["disrupted"]["within_t"])
        else:
            smoke.same("capped time increase", r["capped_time_increase"], d["recommendation"]["capped_time_sum_reduction"])

    for name, ids, profile in (("P recommendation", ref["default"]["P"]["recommendation"]["candidate_ids"], "P"),
                               ("AYNA reference", ref["compare_ayna"]["P"]["reference"]["candidate_ids"], "P"),
                               ("B recommendation", ref["default"]["B"]["recommendation"]["candidate_ids"], "B")):
        r = smoke.call(f"co2 {name}", "POST", "/decision/co2", {"package_ids": ids, "profile": profile})
        want = ref["co2"].get({"P recommendation": "P_recommendation", "AYNA reference": "AYNA_reference"}.get(name, ""))
        if want:
            smoke.same("bus_kg", r["bus_kg"], want["bus_kg"])
            smoke.same("status", r["status"], want["status"])
        cov = r["car_distance_coverage"]
        smoke.check("coverage", True, f"{cov['missing']} of {cov['restored']} restored lack a car distance "
                                      f"{cov['by_reason']}; status {r['status']}")
        r = smoke.call(f"co2 {name}, 10 km entered", "POST", "/decision/co2",
                       {"package_ids": ids, "profile": profile, "car_trip_km": 10.0})
        expected = math.ceil(r["bus_kg"] / (10.0 * r["car_kg_per_pkm"])) if r["bus_kg"] > 0 else 0
        smoke.same("break-even from the entered value", (r["status"], r["break_even_trips"]), ("complete", expected))


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
        smoke = Smoke(client)
        try:
            run(smoke, ref)
        finally:
            server.should_exit = True
            thread.join(timeout=30)
    print(f"startup: model {timings['model_load_s']:.1f} s, app (index + compare_ayna) {timings['app_build_s']:.1f} s, "
          f"server ready {timings['server_ready_s']:.1f} s")
    for row in smoke.rows:
        print(f"{row['s']:8.3f} s  {row['call']}")
        for label, ok, detail in row["checks"]:
            print(f"           {'ok  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    print(f"{len(smoke.rows)} calls, {sum(len(r['checks']) for r in smoke.rows)} checks, {smoke.failures} failed")
    return 1 if smoke.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
