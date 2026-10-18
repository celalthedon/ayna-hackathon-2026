"""Real results on the M-supplement model, from the precomputed evaluation cache.

P and B at the default limits (config/limits.yaml), compare_ayna through the real decision API,
the stress grid and one re-optimisation for the P recommendation, and CO2 break-even for the
P recommendation and the AYNA package. Numbers only. Writes outputs/m_results_<commit>.json (git-ignored).

    python tools/run_m_results.py --bundle <bundle> --config supplements/m_services_v1/config \
        --car-distances <Celal's original od_car_distances.csv> --car-distances-sha256 <its documented SHA-256>
"""
import argparse
import csv
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from citypilot.api_decision import EvaluationCache, build_decision_router, cache_identity  # noqa: E402
from citypilot.decision_engine import (  # noqa: E402
    PROFILES,
    Scenario,
    StressSetup,
    build_request,
    enumerate_packages,
    is_feasible,
    load_objective,
    load_scenario,
    optimize,
    rank_key,
    stress_grid_from_assumptions,
    stress_test,
)
from citypilot.decision_real import (  # noqa: E402
    AYNA_REFERENCE,
    AYNA_REFERENCE_LABEL,
    LIMITS_PATH,
    baseline_request,
    real_backend,
    real_catalog,
    real_evaluator,
    real_input_hashes,
    real_limits,
    real_problem,
)
from run_a6_first_real import commit, package_row, within_ids  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
ASSUMPTIONS = ROOT / "data" / "curated" / "assumptions.csv"
STRESS_PARAMS = ("P3", {"SG_R2": "P1", "SG_R14": "P2"})


class Counted:
    """Evaluator that counts fresh (cache-miss) evaluations."""
    def __init__(self, model):
        self.calls, self._evaluate = 0, real_evaluator(model)

    def __call__(self, request):
        self.calls += 1
        return self._evaluate(request)


def default_run(model, profile, limits, candidates, exclusions, H_hours, cache):
    problem = real_problem(model, profile, limits, candidates, exclusions, H_hours)
    objective = load_objective(problem.objective_dir, profile, problem.model_hashes)
    result = optimize(problem, cache.evaluate)
    normal = cache.evaluate(baseline_request(model, "normal", profile))
    disrupted = cache.evaluate(build_request(problem, ()))
    t = problem.primary_t_min
    ctx = {"normal_within": within_ids(normal, t), "disrupted_sum": disrupted.capped_time_sum}
    ctx["lost"] = ctx["normal_within"] - within_ids(disrupted, t)

    def row(ids):
        res = problem.resources(ids)
        return package_row(ids, cache.evaluate(build_request(problem, ids)), res, is_feasible(res, limits), ctx)

    rec = result.recommendation.candidate_ids
    feasible = [ids for ids in enumerate_packages(problem) if is_feasible(problem.resources(ids), limits)]
    keys = {ids: rank_key(cache.evaluate(build_request(problem, ids)), problem.resources(ids), objective, ids)
            for ids in feasible}
    ranked = sorted((ids for ids in feasible if ids != rec), key=keys.get)
    alternatives = ranked[:3]
    if len(ranked) > 3:
        alternatives += [ids for ids in ranked[3:] if keys[ids][0] == keys[ranked[2]][0]]  # ties of the 3rd
    metric = "restored_within_t" if objective == "count" else "capped_time_sum_reduction"
    rec_row = row(rec)
    return problem, objective, {
        "objective": objective,
        "objective_dir": str(problem.objective_dir.relative_to(ROOT)),
        "label": result.label,
        "enumerated_count": result.enumerated_count,
        "feasible_count": result.feasible_count,
        "recommendation": rec_row,
        "recommendation_source": result.recommendation_source,
        "alternatives": [row(ids) for ids in alternatives],
        "baselines": {name: {"label": b.label, "package": row(b.package.candidate_ids),
                             "optimizer_margin": rec_row[metric] - row(b.package.candidate_ids)[metric]}
                      for name, b in result.baselines.items()},
        "margin_metric": metric,
        "normal": {"within_t": len(ctx["normal_within"]), "capped_time_sum": normal.capped_time_sum},
        "disrupted": {"within_t": len(within_ids(disrupted, t)), "capped_time_sum": disrupted.capped_time_sum,
                      "lost_t": len(ctx["lost"])},
    }


def stress_run(model, problem_template, limits, candidates, exclusions, H_hours, identity, make_evaluator, package):
    with open(ASSUMPTIONS, newline="", encoding="utf-8") as f:
        grid = stress_grid_from_assumptions(list(csv.DictReader(f)), *STRESS_PARAMS)
    profile = problem_template.context.profile

    def problem_for(scenario):
        return real_problem(model, profile, limits, candidates, exclusions, H_hours, scenario=scenario)

    def evaluator_for(scenario):
        return EvaluationCache(CACHE_DIR, identity, scenario, make_evaluator).evaluate

    r = stress_test(StressSetup(problem_for, evaluator_for, grid, H_hours), package)
    point = lambda p: {"speed_level": p.speed_level, "headway_level": p.headway_level,  # noqa: E731
                       "speed_factor": p.scenario.speed_factor,
                       "headway_factor_by_group": dict(p.scenario.headway_factor_by_group or {}),
                       "feasible": p.feasible, "bus_hours": p.bus_hours, "overrun": p.overrun,
                       "within_t": p.within_t, "capped_time_sum": p.capped_time_sum, "warnings": list(p.warnings)}
    reopt = r.reoptimization
    return {
        "status": r.status, "message": r.message, "package": list(r.package_ids),
        "grid": {"speed_levels_kmh": dict(grid.speed_levels_kmh),
                 "headway_levels_min": {g: dict(v) for g, v in grid.headway_levels_min.items()}},
        "points": [point(p) for p in r.points],
        "worst": point(r.worst) if r.worst else None,
        "reoptimization": None if reopt is None else {
            "label": reopt.label, "recommendation": list(reopt.recommendation.candidate_ids),
            "within_t": reopt.recommendation.within_t, "capped_time_sum": reopt.recommendation.capped_time_sum,
            "bus_hours": reopt.recommendation.resources.added_bus_hours,
            "feasible_count": reopt.feasible_count, "enumerated_count": reopt.enumerated_count},
        "reoptimization_reason": r.reoptimization_reason,
        "warnings": list(r.warnings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--car-distances", required=True, type=Path)
    parser.add_argument("--car-distances-sha256", required=True, help="checked before use; a mismatch fails")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from citypilot.routing_engine import get_catalog, load_model

    model = load_model(args.bundle, args.config)
    catalog = get_catalog(model)
    candidates, exclusions = real_catalog(catalog)
    limits = real_limits()
    H_hours = load_scenario(LIMITS_PATH, 1.0, 1.0).H_hours
    scenario = Scenario(1.0, 1.0, H_hours)
    identity = cache_identity(catalog.model_version, real_input_hashes(model))
    counted = Counted(model)
    make_evaluator = lambda: counted  # noqa: E731
    cache = EvaluationCache(CACHE_DIR, identity, scenario, make_evaluator)

    backend = real_backend(model, CACHE_DIR, args.car_distances, args.car_distances_sha256)
    assert cache_identity(backend.config_hash, backend.input_hashes) == identity
    backend = dataclasses.replace(backend, evaluator_for=lambda profile, sc: counted)
    app = FastAPI()
    app.include_router(build_decision_router(backend))
    client = TestClient(app)

    def api(path, body):
        response = client.post(f"/decision/{path}", json=body)
        if response.status_code != 200:
            raise RuntimeError(f"/decision/{path} {body}: {response.status_code} {response.text}")
        return response.json()

    report = {"commit": commit(), "model_version": catalog.model_version, **real_input_hashes(model),
              "limits": dataclasses.asdict(limits) | {"H_hours": H_hours, "N_a_max": backend.N_a_max},
              "candidates": sorted(candidates), "exclusions": [list(g) for g in exclusions],
              "car_distances": {"file": args.car_distances.name, "source": "Celal's original build (od_car_distances_v1)",
                                "sha256": hashlib.sha256(args.car_distances.read_bytes()).hexdigest(),
                                "expected_sha256": args.car_distances_sha256, "verified": True},
              "default": {}, "compare_ayna": {}}
    problems = {}
    for profile in PROFILES:
        problems[profile], _, report["default"][profile] = default_run(model, profile, limits, candidates, exclusions,
                                                                      H_hours, cache)
        c = api("compare_ayna", {"profile": profile})
        report["compare_ayna"][profile] = {
            "label": AYNA_REFERENCE_LABEL, "verdict": c["verdict"], "limits": c["limits"],
            "reference": c["reference"], "citypilot": c["optimizer"]["recommendation"],
            "citypilot_label": c["optimizer"]["label"], "difference": c["difference"]}

    p_rec = tuple(report["default"]["P"]["recommendation"]["candidate_ids"])
    report["stress_P"] = stress_run(model, problems["P"], limits, candidates, exclusions, H_hours, identity,
                                    make_evaluator, p_rec)
    report["co2"] = {name: api("co2", {"package_ids": list(ids), "profile": "P"})
                     for name, ids in (("P_recommendation", p_rec), ("AYNA_reference", AYNA_REFERENCE))}
    report["fresh_evaluations"] = counted.calls
    out = args.out or ROOT / "outputs" / f"m_results_{report['commit']}.json"
    out.write_text(json.dumps(report, indent=2, allow_nan=False))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
