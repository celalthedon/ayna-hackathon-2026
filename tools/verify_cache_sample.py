"""Cross-platform check of the precomputed cache: re-evaluate a fixed list of packages and compare.

    make the list (Ali):   python tools/verify_cache_sample.py make --bundle <bundle> --out check_list.json
    check it (anyone):     python tools/verify_cache_sample.py check --bundle <bundle> --list check_list.json

`check` rebuilds each request on this machine (its config_hash must equal the listed one: same model,
OD set, patches and thresholds), evaluates it fresh with the routing engine, and compares within_counts
(exact), capped_time_sum and every OD's status and minutes (|delta| reported, tolerance 1e-6 min).
Config is always supplements/m_services_v1/config (the M-supplement model).
"""
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from citypilot.api_decision import EvaluationCache, cache_identity  # noqa: E402
from citypilot.decision_engine import Limits, Scenario, build_request, load_scenario  # noqa: E402
from citypilot.decision_real import (AYNA_REFERENCE, LIMITS_PATH, load_n_a_max, real_catalog,  # noqa: E402
                                     real_evaluator, real_input_hashes, real_limits, real_problem)

CONFIG = ROOT / "supplements" / "m_services_v1" / "config"
CACHE_DIR = ROOT / "data" / "cache"
MINUTES_TOL = 1e-6
SAMPLE = {  # 5 per profile: no action, recommendations, compare_ayna packages, the AYNA reference, a cut pair
    "P": [(), ("SVC_M5_A",), ("R2_CUT25",), AYNA_REFERENCE,
          ("R14_CUT25", "R2_CUT25", "SVC_M3_A", "SVC_M5_A", "SVC_M6_A")],
    "B": [(), ("SVC_M6_A",), ("SVC_M1_A", "SVC_M2_A", "SVC_M3_A", "SVC_M6_A"), AYNA_REFERENCE,
          ("R14_CUT50", "R2_CUT50")],
}


def ods_digest(result) -> str:
    rows = [[o.od_id, o.status, o.minutes] for o in sorted(result.od_results, key=lambda o: o.od_id)]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def setup(bundle: Path):
    from citypilot.routing_engine import get_catalog, load_model

    model = load_model(bundle, CONFIG)
    catalog = get_catalog(model)
    candidates, exclusions = real_catalog(catalog)
    base = real_limits()
    limits = Limits(base.B_h_bus_hours, base.K_new_infra_km, load_n_a_max(), base.max_exact_packages)
    H_hours = load_scenario(LIMITS_PATH, 1.0, 1.0).H_hours
    problems = {p: real_problem(model, p, limits, candidates, exclusions, H_hours) for p in SAMPLE}
    identity = cache_identity(catalog.model_version, real_input_hashes(model))
    return model, problems, identity, Scenario(1.0, 1.0, H_hours)


def make(args) -> int:
    model, problems, identity, scenario = setup(args.bundle)
    cache = EvaluationCache(CACHE_DIR, identity, scenario, lambda: None)
    items = []
    for profile, packages in SAMPLE.items():
        for ids in packages:
            request = build_request(problems[profile], tuple(sorted(ids)))
            full = cache.lookup_full(request)
            if full is None:
                raise SystemExit(f"{profile} {ids}: not in the cache")
            items.append({"profile": profile, "candidate_ids": list(request.candidate_ids),
                          "config_hash": request.config_hash,
                          "cache_file": cache.path_for(cache.key_for(request)).name,
                          "within_counts": {str(t): n for t, n in full.within_counts.items()},
                          "capped_time_sum": full.capped_time_sum, "ods_sha256": ods_digest(full),
                          "od_count": len(full.od_results)})
    args.out.write_text(json.dumps({"model": identity, "made_on": platform.platform(), "items": items}, indent=2))
    print(args.out, len(items), "packages")
    return 0


def check(args) -> int:
    model, problems, identity, scenario = setup(args.bundle)
    listed = json.loads(args.list.read_text())
    cache = EvaluationCache(CACHE_DIR, identity, scenario, lambda: None)
    evaluate = real_evaluator(model)
    report, bad = [], 0
    for item in listed["items"]:
        request = build_request(problems[item["profile"]], tuple(item["candidate_ids"]))
        fresh = evaluate(request)
        stored = cache.lookup_full(request)
        row = {"profile": item["profile"], "candidate_ids": item["candidate_ids"],
               "config_hash_equal": request.config_hash == item["config_hash"],
               "within_counts_equal": {str(t): n for t, n in fresh.within_counts.items()} == item["within_counts"],
               "capped_time_sum_delta": fresh.capped_time_sum - item["capped_time_sum"],
               "ods_sha256_equal": ods_digest(fresh) == item["ods_sha256"]}
        if stored is not None:
            by_id = {o.od_id: o for o in stored.od_results}
            deltas = [abs(o.minutes - by_id[o.od_id].minutes) for o in fresh.od_results
                      if o.minutes is not None and by_id[o.od_id].minutes is not None]
            row["status_differences"] = sum(o.status != by_id[o.od_id].status for o in fresh.od_results)
            row["max_abs_minutes_delta"] = max(deltas, default=0.0)
        ok = (row["config_hash_equal"] and row["within_counts_equal"] and abs(row["capped_time_sum_delta"]) <= 1e-6
              and row.get("status_differences", 0) == 0 and row.get("max_abs_minutes_delta", 0.0) <= MINUTES_TOL)
        row["ok"] = ok
        bad += not ok
        report.append(row)
    out = {"platform": platform.platform(), "python": sys.version.split()[0], "items": report, "failed": bad}
    print(json.dumps(out, indent=2))
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--bundle", required=True, type=Path)
    m.add_argument("--out", required=True, type=Path)
    c = sub.add_parser("check")
    c.add_argument("--bundle", required=True, type=Path)
    c.add_argument("--list", required=True, type=Path)
    args = parser.parse_args()
    return make(args) if args.cmd == "make" else check(args)


if __name__ == "__main__":
    raise SystemExit(main())
