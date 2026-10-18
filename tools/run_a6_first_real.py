"""A6 part 2: first real optimisation, R2 / R14 headway cuts only (no M lines, no BIKE).

Runs optimize() for profiles P and B on the loaded bundle with config/limits.yaml defaults and writes
outputs/a6_first_real_<commit>.json (git-ignored). Sanity checks are reported, never corrected.

    python tools/run_a6_first_real.py --bundle outputs/c4_model_alpha_20261017_155941_581069
"""
import argparse
import dataclasses
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from citypilot.decision_engine import (  # noqa: E402
    PROFILES,
    build_request,
    enumerate_packages,
    is_feasible,
    is_within,
    load_objective,
    load_scenario,
    optimize,
    rank_key,
)
from citypilot.decision_real import (  # noqa: E402
    LIMITS_PATH,
    baseline_request,
    real_evaluator,
    real_limits,
    real_problem,
    route_cut_candidates,
    route_cut_exclusions,
)


def commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.strip()
    return head.stdout.strip() + ("-dirty" if dirty else "")


def within_ids(evaluation, t_min):
    return {od.od_id for od in evaluation.od_results if is_within(od, t_min)}


def vehicles(resources):
    deltas = [s.delta_vehicles for s in resources.per_service]
    return None if any(d is None for d in deltas) else sum(deltas)


def package_row(ids, evaluation, resources, feasible, ctx):
    t = evaluation.primary_t_min
    within = within_ids(evaluation, t)
    return {
        "candidate_ids": list(ids),
        "within_t": len(within),
        "restored_within_t": len(within & ctx["lost"]),
        "newly_within_t_not_in_normal": len(within - ctx["normal_within"]),
        "capped_time_sum": evaluation.capped_time_sum,
        "capped_time_sum_reduction": ctx["disrupted_sum"] - evaluation.capped_time_sum,
        "bus_hours": resources.added_bus_hours,
        "vehicles": vehicles(resources),
        "actions": resources.action_count,
        "feasible": feasible,
        "duration_ms": evaluation.duration_ms,
    }


def run_profile(model, profile, limits, candidates, exclusions, H_hours):
    problem = real_problem(model, profile, limits, candidates, exclusions, H_hours)
    objective = load_objective(problem.objective_dir, profile, problem.model_hashes)
    evaluate = real_evaluator(model)
    normal = evaluate(baseline_request(model, "normal", profile))
    seen = {}

    def recording(request):
        result = evaluate(request)
        seen[request.candidate_ids] = result
        return result

    started = time.perf_counter()
    result = optimize(problem, recording)
    wall_s = time.perf_counter() - started

    disrupted = seen[()]
    t = problem.primary_t_min
    ctx = {"normal_within": within_ids(normal, t), "disrupted_sum": disrupted.capped_time_sum}
    ctx["lost"] = ctx["normal_within"] - within_ids(disrupted, t)
    gate = json.loads(Path(problem.objective_dir, f"objective_decision_{profile}.json").read_text())

    optimizer_evaluations = dict(seen)
    rows, keys = {}, {}
    for ids in enumerate_packages(problem):
        res = problem.resources(ids)
        if ids not in seen:  # skipped by optimize (over the limits); evaluated only for the checks
            seen[ids] = evaluate(build_request(problem, ids))
        rows[ids] = package_row(ids, seen[ids], res, is_feasible(res, limits), ctx)
        keys[ids] = rank_key(seen[ids], res, objective, ids)

    rec = result.recommendation.candidate_ids
    ranked = sorted((ids for ids in rows if rows[ids]["feasible"] and ids != rec), key=lambda ids: keys[ids])
    alternatives = ranked[:3]
    if len(ranked) > 3:
        alternatives += [ids for ids in ranked[3:] if keys[ids][0] == keys[ranked[2]][0]]  # all ties of the 3rd on the objective

    metric = "restored_within_t" if objective == "count" else "capped_time_sum_reduction"
    baselines = {}
    for name, b in result.baselines.items():
        row = rows[b.package.candidate_ids]
        baselines[name] = {"label": b.label, "package": row, "optimizer_margin": rows[rec][metric] - row[metric],
                           "steps": [[s.candidate_id, s.score, s.outcome] for s in b.steps]}

    # sanity checks (reported, not fixed)
    gate_lost = gate["lost_T"][str(t)]
    over_gate = [list(ids) for ids, r in rows.items() if r["restored_within_t"] > gate_lost]
    monotone = []
    for small in rows:
        for big in rows:
            if small != big and set(small) < set(big) and rows[big]["within_t"] < rows[small]["within_t"]:
                monotone.append({"package": list(big), "contains": list(small),
                                 "within_t": [rows[big]["within_t"], rows[small]["within_t"]]})
    sum_monotone = [{"package": list(big), "contains": list(small)}
                    for small in rows for big in rows
                    if small != big and set(small) < set(big)
                    and rows[big]["capped_time_sum"] > rows[small]["capped_time_sum"] + 1e-6]
    durations = [e.duration_ms for e in optimizer_evaluations.values()]
    return {
        "profile": profile,
        "objective": objective,
        "objective_dir": str(problem.objective_dir.relative_to(ROOT)),
        "label": result.label,
        "enumerated_count": result.enumerated_count,
        "feasible_count": result.feasible_count,
        "recommendation": rows[rec],
        "recommendation_source": result.recommendation_source,
        "alternatives": [rows[ids] for ids in alternatives],
        "optimizer_alternatives": [list(a.candidate_ids) for a in result.alternatives],
        "baselines": baselines,
        "normal": {"within_t": len(ctx["normal_within"]), "capped_time_sum": normal.capped_time_sum},
        "disrupted": {"within_t": rows[()]["within_t"], "capped_time_sum": disrupted.capped_time_sum,
                      "lost_t": len(ctx["lost"])},
        "gate_lost_t": gate_lost,
        "max_capped_time_sum_reduction_to_normal": disrupted.capped_time_sum - normal.capped_time_sum,
        "checks": {
            "restored_exceeds_gate_lost": over_gate,
            "superset_with_fewer_within_t": monotone,
            "superset_with_higher_capped_sum": sum_monotone,
            "no_action_equals_disrupted": rows[()]["within_t"] == len(within_ids(disrupted, t))
                                          and len(ctx["lost"]) == gate_lost,
            "no_action_lost_t": len(ctx["lost"]),
            "no_action_config_hash_is_gate_disrupted": build_request(problem, ()).config_hash
                                                       == gate["input_hashes"]["disrupted"],
        },
        "evaluations": {"count": len(optimizer_evaluations), "checks_only": len(seen) - len(optimizer_evaluations),
                        "mean_duration_ms": statistics.fmean(durations),
                        "max_duration_ms": max(durations), "optimize_wall_s": wall_s,
                        "optimize_runtime_s": result.runtime_s},
        "packages": sorted(rows.values(), key=lambda r: r["candidate_ids"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="routing config dir (default: <bundle>/config)")
    parser.add_argument("--out", type=Path, help="default: outputs/a6_first_real_<commit>.json")
    args = parser.parse_args()
    from citypilot.routing_engine import get_catalog, load_model

    model = load_model(args.bundle, args.config or args.bundle / "config")
    catalog = get_catalog(model)
    candidates = route_cut_candidates(catalog)
    exclusions = route_cut_exclusions(candidates)
    limits = real_limits()
    H_hours = load_scenario(LIMITS_PATH, 1.0, 1.0).H_hours
    rev = commit()
    report = {
        "commit": rev,
        "model_version": catalog.model_version,
        "od_set_id": catalog.od_set_id,
        "limits": {"path": str(LIMITS_PATH.relative_to(ROOT)), "H_hours": H_hours, **dataclasses.asdict(limits)},
        "candidates": {cid: {"target_id": c.target_id, "pct": c.pct} for cid, c in sorted(candidates.items())},
        "exclusions": [list(g) for g in exclusions],
        "profiles": {p: run_profile(model, p, limits, candidates, exclusions, H_hours) for p in PROFILES},
    }
    out = args.out or ROOT / "outputs" / f"a6_first_real_{rev}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
