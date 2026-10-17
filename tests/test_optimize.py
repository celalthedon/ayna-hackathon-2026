"""Gate, exact search, baselines and alternatives. Expected values were computed by hand."""
import json
import math
from pathlib import Path

import pytest

from citypilot.decision_engine import (
    Candidate,
    DecisionProblem,
    EvaluationResult,
    Limits,
    Link,
    ModelCatalog,
    ODResult,
    ResourceResult,
    RoutingRequest,
    Scenario,
    ServiceGroup,
    count_lost,
    enumerate_packages,
    gate_decision,
    gate_objective,
    load_fixture,
    load_limits,
    make_catalog_resources,
    make_fixture_evaluator,
    optimize,
    rank_key,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = load_fixture(ROOT / "tests" / "fixtures" / "decision" / "fixture_4action.json")
LABEL = FIXTURE["label"]


# --- test-only helpers (table resources never live in decision_export cells) ---

def table_resources(table):
    """Resources summed from a per-action table; a set, so shared actions count once."""
    def resources(ids):
        ids = set(ids)
        bus_hours = sum(table[i]["bus_hours"] for i in ids)
        km = sum(table[i]["new_infra_km"] for i in ids)
        return ResourceResult(bus_hours, bus_hours, km, len(ids), "known", (), ())
    return resources


def objective_file(tmp_path, objective):
    path = tmp_path / "objective_decision.json"
    path.write_text(json.dumps({"objective": objective, "note": "set explicitly in test; gate not run"}))
    return path


def problem_from(fixture, objective_path, *, max_exact=1024, n_a=None, b_h=None, prerequisites=None):
    lim = fixture["limits"]
    actions = fixture["actions"]
    return DecisionProblem(
        candidate_ids=tuple(sorted(actions)),
        exclusions=tuple(tuple(g) for g in fixture.get("exclusions", [])),
        prerequisites=prerequisites or {},
        distance_m={a: v["distance_m"] for a, v in actions.items()},
        limits=Limits(
            B_h_bus_hours=lim["B_h_bus_hours"] if b_h is None else b_h,
            K_new_infra_km=lim["K_new_infra_km"],
            N_a_actions=lim["N_a_actions"] if n_a is None else n_a,
            max_exact_packages=max_exact,
        ),
        thresholds_min=(40, 45, 50),
        primary_t_min=lim["T_min"],
        cap_min=lim["C_min"],
        objective_path=objective_path,
        resources=table_resources(actions),
    )


def run(tmp_path, objective, fixture=FIXTURE, **kw):
    problem = problem_from(fixture, objective_file(tmp_path, objective), **kw)
    return optimize(problem, make_fixture_evaluator(fixture))


def ids(outcome):
    return "".join(outcome.candidate_ids)


def steps(baseline):
    return [(s.candidate_id, s.outcome) for s in baseline.steps]


def scores(baseline):
    return {s.candidate_id: s.score for s in baseline.steps}


def synthetic_fixture(actions, ods):
    return {"label": LABEL, "limits": {"B_h_bus_hours": 24, "N_a_actions": 3, "K_new_infra_km": 2.0,
                                       "T_min": 45, "C_min": 120},
            "actions": actions, "exclusions": [], "ods": ods}


def od(od_id, requires, disrupted=60, minutes=40):
    return {"od_id": od_id, "disrupted_min": disrupted, "options": [{"requires": requires, "minutes": minutes}]}


# --- fixture, objective "count" ---

@pytest.fixture
def count_result(tmp_path):
    return run(tmp_path, "count")


def test_count_exact(count_result):
    r = count_result
    rec = r.recommendation
    assert r.objective == "count" and r.label == "exact" and r.recommendation_source == "exact"
    assert ids(rec) == "ACD"
    assert (rec.within_t, rec.capped_time_sum) == (7, 350)
    assert rec.resources.added_bus_hours == 21
    assert math.isclose(rec.resources.new_infra_km, 0.04)
    assert rec.resources.action_count == 3
    assert r.feasible_count == 10
    assert r.enumerated_count == 12
    assert r.not_ranked == ()
    assert r.approximate_reason is None


def test_count_greedy(count_result):
    g = count_result.baselines["greedy"]
    assert g.label == "simple greedy (solo gain)"
    assert ids(g.package) == "B"
    assert (g.package.within_t, g.package.capped_time_sum) == (4, 437)
    s = scores(g)
    assert math.isclose(s["A"], 6.0) and math.isclose(s["B"], 6.4) and math.isclose(s["C"], 4.8) and s["D"] == 0
    assert steps(g) == [("B", "added"), ("A", "excluded"), ("C", "does_not_fit"), ("D", "no_gain")]


def test_count_nearest_gap(count_result):
    n = count_result.baselines["nearest_gap"]
    assert ids(n.package) == "ACD"
    assert (n.package.within_t, n.package.capped_time_sum) == (7, 350)
    assert steps(n) == [("C", "added"), ("A", "added"), ("B", "excluded"), ("D", "added")]


def test_count_no_action(count_result):
    p = count_result.baselines["no_action"].package
    assert p.candidate_ids == ()
    assert (p.within_t, p.capped_time_sum) == (0, 507)


def test_count_alternatives(count_result):
    alts = count_result.alternatives
    assert [ids(a) for a in alts] == ["AC", "CD", "B"]
    assert [a.reason for a in alts] == [
        "2 fewer ODs within 45 min", "2 fewer ODs within 45 min", "3 fewer ODs within 45 min"]


# --- fixture, objective "sum" ---

def test_sum(tmp_path):
    r = run(tmp_path, "sum")
    assert ids(r.recommendation) == "ACD" and r.recommendation.capped_time_sum == 350
    g = r.baselines["greedy"]
    assert ids(g.package) == "AC" and g.package.capped_time_sum == 358
    s = scores(g)
    assert math.isclose(s["A"], 120) and math.isclose(s["B"], 112) and math.isclose(s["C"], 174.4) and s["D"] == 0
    assert steps(g)[:3] == [("C", "added"), ("A", "added"), ("B", "excluded")]
    assert ids(r.baselines["nearest_gap"].package) == "ACD"


def test_sum_ranking():
    evaluate = make_fixture_evaluator(FIXTURE)
    res = table_resources(FIXTURE["actions"])
    problem = problem_from(FIXTURE, Path("unused"))
    feasible = ["", "A", "B", "C", "D", "AC", "AD", "BD", "CD", "ACD"]

    def key(p):
        req = RoutingRequest(tuple(p), problem.thresholds_min, problem.primary_t_min, problem.cap_min)
        return rank_key(evaluate(req), res(tuple(p)), objective="sum")

    assert sorted(feasible, key=key) == ["ACD", "AC", "CD", "C", "B", "BD", "A", "AD", "", "D"]


# --- gate ---

@pytest.mark.parametrize("lost, objective", [
    ((8, 8, 9), "sum"),
    ((60, 75, 90), "count"),
    ((470, 480, 490), "sum"),
    ((10, 100, 10), "count"),
])
def test_gate_objective(lost, objective):
    got, _ = gate_objective(dict(zip((40, 45, 50), lost)), 500)
    assert got == objective


def test_gate_zero_total():
    with pytest.raises(ValueError):
        gate_objective({40: 0, 45: 0, 50: 0}, 0)


def evaluation(minutes, tag):
    od_results = tuple(ODResult(f"OD{i + 1}", m, "reachable") for i, m in enumerate(minutes))
    return EvaluationResult(tag, (), od_results, {}, 45, sum(minutes))


def test_gate_lost_counting():
    normal = evaluation([30, 44, 46, 50], "normal-hash")
    disrupted = evaluation([50, 46, 60, 40], "disrupted-hash")
    assert count_lost(normal, disrupted, (40, 45, 50)) == {40: 1, 45: 2, 50: 1}


def test_gate_decision_file(tmp_path):
    path = tmp_path / "objective_decision.json"
    record = gate_decision(evaluation([30, 44, 46, 50], "n"), evaluation([50, 46, 60, 40], "d"), path)
    saved = json.loads(path.read_text())
    assert saved == record
    assert saved["objective"] == "sum"
    assert saved["total_OD"] == 4
    assert saved["lost_T"] == {"40": 1, "45": 2, "50": 1}
    assert saved["share_T"] == {"40": 0.25, "45": 0.5, "50": 0.25}
    assert saved["input_hashes"] == {"normal": "n", "disrupted": "d"}
    assert {"thresholds", "timestamp"} <= saved.keys()
    with pytest.raises(FileExistsError):
        gate_decision(evaluation([30], "n"), evaluation([50], "d"), path)


def test_optimize_without_objective_decision(tmp_path):
    problem = problem_from(FIXTURE, tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        optimize(problem, make_fixture_evaluator(FIXTURE))


# --- approximate ---

def test_approximate_fixture(tmp_path):
    r = run(tmp_path, "count", max_exact=5)
    assert r.label == "approximate"
    assert ids(r.recommendation) == "ACD" and r.recommendation.within_t == 7
    assert r.recommendation_source == "nearest_gap"
    assert r.approximate_reason == "catalog too large for exact search (12 > 5)"
    assert r.alternatives == () and r.feasible_count is None
    assert r.enumerated_count == 12
    assert ids(r.baselines["greedy"].package) == "B" and r.baselines["greedy"].package.within_t == 4
    assert ids(r.baselines["nearest_gap"].package) == "ACD"
    assert r.baselines["no_action"].package.candidate_ids == ()


def test_approximate_source_greedy(tmp_path):
    # X is nearest but reaches 1 OD; Y is far but reaches 3; only one action fits
    fx = synthetic_fixture(
        {"X": {"bus_hours": 6, "new_infra_km": 0, "distance_m": 0},
         "Y": {"bus_hours": 6, "new_infra_km": 0, "distance_m": 100}},
        [od("O1", ["X"]), od("O2", ["Y"]), od("O3", ["Y"]), od("O4", ["Y"])],
    )
    r = run(tmp_path, "count", fixture=fx, max_exact=1, n_a=1)
    assert r.label == "approximate" and r.enumerated_count == 3
    assert ids(r.baselines["nearest_gap"].package) == "X"
    assert ids(r.recommendation) == "Y" and r.recommendation_source == "greedy"


# --- ties ---

def test_ties_show_all_alternatives(tmp_path):
    actions = {f"S{i}": {"bus_hours": 6, "new_infra_km": 0, "distance_m": i} for i in range(1, 7)}
    fx = synthetic_fixture(actions, [od(f"O{i}", [f"S{i}"]) for i in range(1, 7)])
    r = run(tmp_path, "count", fixture=fx, n_a=1)
    assert ids(r.recommendation) == "S1"
    assert [ids(a) for a in r.alternatives] == ["S2", "S3", "S4", "S5", "S6"]


# --- prerequisites: L needs P ---

PREREQ_ACTIONS = {
    "L": {"bus_hours": 24, "new_infra_km": 0, "distance_m": 0},
    "P": {"bus_hours": 0, "new_infra_km": 0.5, "distance_m": 10},
}
PREREQ_ODS = [od("O1", ["P"]), od("O2", ["P"]), od("O3", ["L", "P"]), od("O4", ["L", "P"]), od("O5", ["L", "P"])]


def prereq_run(tmp_path, ods=PREREQ_ODS, **kw):
    fx = synthetic_fixture(PREREQ_ACTIONS, ods)
    return run(tmp_path, "count", fixture=fx, prerequisites={"L": ("P",)}, **kw)


def test_exact_never_l_without_p(tmp_path):
    fx = synthetic_fixture(PREREQ_ACTIONS, PREREQ_ODS)
    problem = problem_from(fx, objective_file(tmp_path, "count"), prerequisites={"L": ("P",)})
    assert list(enumerate_packages(problem)) == [(), ("P",), ("L", "P")]
    r = prereq_run(tmp_path)
    assert ids(r.recommendation) == "LP"
    assert all(not ("L" in a.candidate_ids and "P" not in a.candidate_ids) for a in r.alternatives)


def test_greedy_l_cost_on_l_plus_p_and_p_not_counted_twice(tmp_path):
    # P: gain 2 / max(0, 0.25, 1/3) = 6.0; {L,P}: gain 5 / max(24/24, 0.25, 2/3) = 5.0
    g = prereq_run(tmp_path).baselines["greedy"]
    assert math.isclose(scores(g)["P"], 6.0) and math.isclose(scores(g)["L"], 5.0)
    assert steps(g) == [("P", "added"), ("L", "added")]
    assert g.package.resources.action_count == 2
    assert math.isclose(g.package.resources.new_infra_km, 0.5)


def test_greedy_skips_l_when_l_plus_p_does_not_fit(tmp_path):
    # N_a = 1: {L,P} needs 2 actions
    g = prereq_run(tmp_path, n_a=1).baselines["greedy"]
    assert ("L", "does_not_fit") in steps(g)
    assert "L" not in g.package.candidate_ids


# --- production resources wrapper ---

def test_catalog_resources_wrapper(tmp_path):
    def svc(sid, headway, km, speed, stops, dwell, layover):
        return ServiceGroup(sid, (), headway, km, speed, stops, dwell, layover, "full", "fixture", "fixture")

    catalog = ModelCatalog(
        service_groups={"SG_R2": svc("SG_R2", 10, 12, 15, 30, 20, 5)},
        prebuilt_services={"SVC_SHUTTLE": svc("SVC_SHUTTLE", 8, 9, 18, 6, 30, 4)},
        links={"L2": Link("L2", "bike", 1200, True, "fixture")},
        parking={},
    )
    candidates = {
        "a1": Candidate("a1", "headway_cut", target_id="SG_R2", pct=0.20),
        "a3": Candidate("a3", "activate_service", target_id="SVC_SHUTTLE"),
    }
    resources = make_catalog_resources(candidates, catalog, Scenario(1.0, 1.0, 3.0))
    assert resources(("a1", "a3")).added_bus_hours == 18


def test_limits_yaml():
    limits = load_limits(ROOT / "config" / "limits.yaml")
    assert limits.max_exact_packages == 1024
    assert (limits.B_h_bus_hours, limits.K_new_infra_km, limits.N_a_actions) == (30.0, 2.0, 3)
