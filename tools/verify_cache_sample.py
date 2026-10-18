"""Cross-platform check of the precomputed cache: re-evaluate a fixed list of packages and compare.

    make the list (Ali):   python tools/verify_cache_sample.py make --bundle <bundle> --out check_list.json
    check it (anyone):     python tools/verify_cache_sample.py check --bundle <bundle> --list check_list.json

`check` rebuilds each request on this machine and evaluates it fresh. Cross-platform acceptance rule
(agreed with Celal after the Windows check of the Linux-built cache):
  exact:            request identity (config_hash), within_counts, OD ids, every OD's status
  within 1e-6 min:  every OD's minutes and capped_minutes, capped_time_sum
  reported only:    exact OD hash (SHA-256 of [od_id, status, minutes, capped_minutes]): "exact hash: k/n match"
The check list (version 2) carries every OD's [od_id, status, minutes, capped_minutes].
Config is always supplements/m_services_v1/config (the M-supplement model).
"""
import argparse
import hashlib
import json
import math
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
MINUTES_TOL = 1e-6  # minutes, capped_minutes and capped sums; everything else is compared exactly
LIST_VERSION = 2
RULE = ("exact: config_hash, within_counts, OD ids, statuses; within 1e-6 min: minutes, capped_minutes, "
        "capped sums; exact OD hash reported, not required")
SAMPLE = {  # 5 per profile: no action, recommendations, compare_ayna packages, the AYNA reference, a cut pair
    "P": [(), ("SVC_M5_A",), ("R2_CUT25",), AYNA_REFERENCE,
          ("R14_CUT25", "R2_CUT25", "SVC_M3_A", "SVC_M5_A", "SVC_M6_A")],
    "B": [(), ("SVC_M6_A",), ("SVC_M1_A", "SVC_M2_A", "SVC_M3_A", "SVC_M6_A"), AYNA_REFERENCE,
          ("R14_CUT50", "R2_CUT50")],
}


def ods_digest(result) -> str:
    """Canonical OD-level result: SHA-256 of [od_id, status, minutes, capped_minutes] for every OD, sorted by od_id."""
    rows = [[o.od_id, o.status, o.minutes, o.capped_minutes] for o in sorted(result.od_results, key=lambda o: o.od_id)]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def ods_rows(result) -> list:
    return [[o.od_id, o.status, o.minutes, o.capped_minutes] for o in sorted(result.od_results, key=lambda o: o.od_id)]


def _delta(a, b) -> float:
    """|a - b| in minutes; None (no_path) only matches None."""
    if a is None or b is None:
        return 0.0 if a is b else math.inf
    return abs(a - b)


def compare_item(item: dict, config_hash: str, fresh) -> dict:
    """One check-list item vs a fresh evaluation, under the cross-platform acceptance rule."""
    if "ods" not in item:
        raise ValueError(f"check list item {item['candidate_ids']} has no per-OD rows: make a version-{LIST_VERSION} list")
    listed = {r[0]: r for r in item["ods"]}
    got = {r[0]: r for r in ods_rows(fresh)}
    same_ids = listed.keys() == got.keys()
    common = listed.keys() & got.keys()
    row = {"profile": item["profile"], "candidate_ids": item["candidate_ids"],
           "config_hash_equal": config_hash == item["config_hash"],
           "within_counts_equal": {str(t): n for t, n in fresh.within_counts.items()} == item["within_counts"],
           "od_ids_equal": same_ids,
           "status_differences": sum(got[k][1] != listed[k][1] for k in common),
           "max_abs_minutes_delta": max((_delta(got[k][2], listed[k][2]) for k in common), default=0.0),
           "max_abs_capped_minutes_delta": max((_delta(got[k][3], listed[k][3]) for k in common), default=0.0),
           "capped_time_sum_delta": abs(fresh.capped_time_sum - item["capped_time_sum"]),
           "exact_hash_equal": ods_digest(fresh) == item["ods_sha256"]}  # reported, not required
    row["ok"] = (row["config_hash_equal"] and row["within_counts_equal"] and same_ids
                 and row["status_differences"] == 0 and row["max_abs_minutes_delta"] <= MINUTES_TOL
                 and row["max_abs_capped_minutes_delta"] <= MINUTES_TOL and row["capped_time_sum_delta"] <= MINUTES_TOL)
    return row


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
                          "od_count": len(full.od_results), "ods": ods_rows(full)})
    args.out.write_text(json.dumps({"list_version": LIST_VERSION, "model": identity, "made_on": platform.platform(),
                                    "rule": RULE, "items": items}, indent=1))
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
        row = compare_item(item, request.config_hash, evaluate(request))
        bad += not row["ok"]
        report.append(row)
    exact = sum(r["exact_hash_equal"] for r in report)
    out = {"platform": platform.platform(), "python": sys.version.split()[0], "rule": RULE, "items": report,
           "failed": bad, "exact_hash": f"{exact}/{len(report)} match"}
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
