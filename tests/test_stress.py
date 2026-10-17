"""stress_test and remove_action. Expected values were computed by hand."""
import copy
import json
import math
from pathlib import Path

import pytest

import citypilot.decision_engine as engine
from citypilot.decision_engine import (
    Candidate,
    DecisionProblem,
    Limits,
    ResourceResult,
    Scenario,
    StressGrid,
    StressSetup,
    compute_resources,
    load_fixture,
    make_catalog_patches,
    make_catalog_resources,
    make_fixture_evaluator,
    make_problem_for,
    optimize,
    remove_action,
    stress_grid_from_assumptions,
    stress_test,
)

from decision_testkit import (FIXTURE_HASHES, catalog as kit_catalog, fixture_context, link, parking,
                             service as kit_service, write_objective)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "decision"
STRESS = load_fixture(FIXTURES / "fixture_stress.json")
FOUR = load_fixture(FIXTURES / "fixture_4action.json")
LABEL = FOUR["label"]
DEFAULT = Scenario(1.0, 1.0, 3.0)


# --- stress fixture builders (test-only; the time model is synthetic) ---

def service(sid, v):
    return kit_service(sid, v["base_headway_min"], v["full_cycle_km"], v["speed_kmh"], v["stops_per_cycle"],
                       v["dwell_s"], v["layover_min"], v["coverage"])


def stress_catalog(fx):
    cat = fx["catalog"]
    return kit_catalog(
        service_groups={k: service(k, v) for k, v in cat["service_groups"].items()},
        prebuilt_services={k: service(k, v) for k, v in cat["prebuilt_services"].items()},
        links={k: link(k, v["kind"], v["length_m"], v["requires_construction"]) for k, v in cat["links"].items()},
        parking={k: parking(k, v.get("baseline_enabled", False)) for k, v in cat["parking"].items()},
    )


def stress_candidates(fx):
    out = {}
    for cid, a in fx["actions"].items():
        out[cid] = Candidate(cid, a["kind"], target_id=a.get("target_id"), pct=a.get("pct"),
                             link_ids=tuple(a.get("link_ids", ())), parking_ids=tuple(a.get("parking_ids", ())))
    return out


def objective_file(tmp_path, objective):
    return write_objective(tmp_path, objective)


def stress_setup(tmp_path, fx=STRESS):
    lim = fx["limits"]
    catalog, candidates = stress_catalog(fx), stress_candidates(fx)
    template = DecisionProblem(
        candidate_ids=tuple(sorted(candidates)),
        exclusions=tuple(tuple(g) for g in fx["exclusions"]),
        prerequisites={},
        distance_m={c: a["distance_m"] for c, a in fx["actions"].items()},
        limits=Limits(lim["B_h_bus_hours"], lim["K_new_infra_km"], lim["N_a_actions"], lim["max_exact_packages"]),
        thresholds_min=(40, 45, 50),
        primary_t_min=lim["T_min"],
        cap_min=lim["C_min"],
        objective_dir=objective_file(tmp_path, fx["objective"]),
        model_hashes=FIXTURE_HASHES,
        context=fixture_context(patches_for=make_catalog_patches(candidates, catalog, DEFAULT)),
        resources=make_catalog_resources(candidates, catalog, DEFAULT),
    )
    grid = StressGrid(fx["grid"]["speed_levels_kmh"], fx["grid"]["headway_levels_min"])
    return StressSetup(make_problem_for(template, candidates, catalog), stress_evaluator_for(fx), grid, lim["H_hours"])


def stress_evaluator_for(fx):
    """Synthetic time model: t' = walk + h'/2 + (t - walk - h0/2) / speed_factor."""
    walk = fx["walk_min"]
    catalog = fx["catalog"]

    def headway(rides, requires, scenario):
        if rides in catalog["prebuilt_services"]:
            return catalog["prebuilt_services"][rides]["base_headway_min"]
        group, kind = rides.split(":")
        h = catalog["service_groups"][group]["base_headway_min"] * scenario.group_headway_factor(group)
        if kind == "new":
            cut = [fx["actions"][c] for c in requires if fx["actions"][c].get("target_id") == group]
            h *= 1 - cut[0]["pct"]
        return h

    def at(t, rides, requires, scenario):
        h0, h1 = headway(rides, requires, DEFAULT), headway(rides, requires, scenario)
        return walk + h1 / 2 + (t - walk - h0 / 2) / scenario.speed_factor

    def evaluator_for(scenario):
        moved = copy.deepcopy(fx)
        for od in moved["ods"]:
            if od["disrupted_min"] is not None:
                od["disrupted_min"] = at(od["disrupted_min"], od["disrupted_rides"], (), scenario)
            for opt in od["options"]:
                opt["minutes"] = at(opt["minutes"], opt["rides"], opt["requires"], scenario)
        return make_fixture_evaluator(moved)

    return evaluator_for


def ids(outcome):
    return "".join(outcome.candidate_ids)


# --- default point ---

def test_default_recommendation(tmp_path):
    setup = stress_setup(tmp_path)
    r = optimize(setup.problem_for(DEFAULT), setup.evaluator_for(DEFAULT))
    rec = r.recommendation
    assert ids(rec) == "ACD"
    assert (rec.within_t, rec.capped_time_sum) == (7, 350.0)
    assert rec.resources.added_bus_hours == 24
    assert math.isclose(rec.resources.new_infra_km, 0.04)
    a = next(s for s in rec.resources.per_service if s.service_id == "SG_R2")
    assert round(a.base_cycle_min, 2) == 156.33 and a.base_vehicles == 21


# --- stress of ACD ---

EXPECTED = [  # speed level, headway level, feasible, bus-hours, ODs<=45, capped sum
    ("low", "low", False, 33, 0, 475.91),
    ("low", "default", True, 30, 0, 477.94),
    ("low", "high", True, 24, 0, 481.31),
    ("default", "low", True, 24, 7, 347.98),
    ("default", "default", True, 24, 7, 350.00),
    ("default", "high", True, 21, 7, 353.38),
    ("high", "low", True, 21, 8, 276.33),
    ("high", "default", True, 18, 8, 278.36),
    ("high", "high", True, 15, 8, 281.73),
]


@pytest.fixture
def acd_stress(tmp_path):
    return stress_test(stress_setup(tmp_path), ("A", "C", "D"))


def test_stress_points(acd_stress):
    r = acd_stress
    assert r.objective == "count"
    got = [(p.speed_level, p.headway_level, p.feasible, p.bus_hours, p.within_t) for p in r.points]
    assert got == [e[:5] for e in EXPECTED]
    for p, e in zip(r.points, EXPECTED):
        assert abs(p.capped_time_sum - e[5]) <= 0.01, (p.speed_level, p.headway_level)
        assert p.overrun == max(0, e[3] - 30)
        assert math.isclose(p.new_km, 0.04) and p.actions == 3


def test_stress_factors(acd_stress):
    p = acd_stress.points[0]
    assert math.isclose(p.scenario.speed_factor, 12 / 18)
    assert math.isclose(p.scenario.group_headway_factor("SG_R2"), 0.8)
    assert math.isclose(acd_stress.points[8].scenario.group_headway_factor("SG_R2"), 4 / 3)


def test_worst_point_and_reoptimisation(acd_stress):
    w = acd_stress.worst
    assert (w.speed_level, w.headway_level, w.overrun) == ("low", "low", 3)
    rec = acd_stress.reoptimization.recommendation
    assert ids(rec) == "CD"
    assert rec.within_t == 0 and abs(rec.capped_time_sum - 535.13) <= 0.01
    assert rec.resources.added_bus_hours == 15 and math.isclose(rec.resources.new_infra_km, 0.04)
    reason = acd_stress.reoptimization_reason
    assert "does not fit" in reason and "capped sum decides" in reason


def test_no_cost_rise_warning_on_fixture(acd_stress):
    assert not any(w.startswith("cost_rises_with_speed") for w in acd_stress.warnings)


def test_cost_rises_with_speed_warning(tmp_path):
    # cycle 104 min at low speed vs 100 at default; headway 10 -> 8:
    # low: 11 -> 13 vehicles (+2), default: 10 -> 13 (+3)
    fx = copy.deepcopy(STRESS)
    fx["catalog"]["service_groups"]["SG_R2"].update(full_cycle_km=100, speed_kmh=60, stops_per_cycle=0,
                                                    dwell_s=0, layover_min=0, base_headway_min=10)
    fx["actions"]["A"]["pct"] = 0.2
    fx["grid"] = {"speed_levels_kmh": {"low": 100 / 104, "default": 1, "high": 1.5},
                  "headway_levels_min": {"SG_R2": {"low": 10, "default": 10, "high": 10}}}
    r = stress_test(stress_setup(tmp_path, fx), ("A",))
    by = {(p.speed_level, p.headway_level): p.bus_hours for p in r.points}
    assert (by[("low", "default")], by[("default", "default")]) == (6, 9)
    assert any(w.startswith("cost_rises_with_speed") for w in r.warnings)


def test_stress_never_runs_gate(tmp_path, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("gate must not run inside stress or removal")

    for name in ("gate_decision", "gate_objective", "count_lost"):
        monkeypatch.setattr(engine, name, forbidden)
    setup = stress_setup(tmp_path)
    narrow = StressGrid({"low": 17, "default": 18, "high": 19}, {"SG_R2": {"low": 7, "default": 7.5, "high": 8}})
    for grid in (setup.grid, narrow):
        r = stress_test(StressSetup(setup.problem_for, setup.evaluator_for, grid, setup.H_hours), ("A", "C", "D"))
        assert r.objective == "count"


def test_grid_from_curated_assumptions():
    import csv
    with open(ROOT / "data" / "curated" / "assumptions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    grid = stress_grid_from_assumptions(rows, "P3", {"SG_R2": "P1", "SG_R14": "P2"})
    assert dict(grid.speed_levels_kmh) == {"low": 12, "default": 18, "high": 25}
    assert dict(grid.headway_levels_min["SG_R2"]) == {"low": 6, "default": 7.5, "high": 10}
    assert dict(grid.headway_levels_min["SG_R14"]) == {"low": 4.5, "default": 5, "high": 8}


# --- removals ---

def table_resources(table):
    def resources(ids_):
        ids_ = set(ids_)
        bus_hours = sum(table[i]["bus_hours"] for i in ids_)
        km = sum(table[i]["new_infra_km"] for i in ids_)
        return ResourceResult(bus_hours, bus_hours, km, len(ids_), "known", (), ())
    return resources


def static_problem(fx, objective_dir, prerequisites=None):
    lim = fx["limits"]
    return DecisionProblem(
        candidate_ids=tuple(sorted(fx["actions"])),
        exclusions=tuple(tuple(g) for g in fx.get("exclusions", [])),
        prerequisites=prerequisites or {},
        distance_m={a: v["distance_m"] for a, v in fx["actions"].items()},
        limits=Limits(lim["B_h_bus_hours"], lim["K_new_infra_km"], lim["N_a_actions"], 1024),
        thresholds_min=(40, 45, 50),
        primary_t_min=lim["T_min"],
        cap_min=lim["C_min"],
        objective_dir=objective_dir,
        model_hashes=FIXTURE_HASHES,
        context=fixture_context(),
        resources=table_resources(fx["actions"]),
    )


@pytest.mark.parametrize("action, remaining, n, capped, loss", [
    ("A", "CD", 5, 390, 2),
    ("C", "AD", 2, 467, 5),
    ("D", "AC", 5, 358, 2),
])
def test_single_removals(tmp_path, action, remaining, n, capped, loss):
    problem = static_problem(FOUR, objective_file(tmp_path, "count"))
    r = remove_action(problem, ("A", "C", "D"), action, make_fixture_evaluator(FOUR))
    assert r.objective == "count"
    assert ids(r.full) == "ACD" and (r.full.within_t, r.full.capped_time_sum) == (7, 350)
    assert ids(r.remaining) == remaining
    assert (r.remaining.within_t, r.remaining.capped_time_sum) == (n, capped)
    assert r.loss_within_t == loss
    assert r.remaining.feasible
    assert "not additive" in r.note


def test_removal_losses_are_not_additive(tmp_path):
    problem = static_problem(FOUR, objective_file(tmp_path, "count"))
    evaluate = make_fixture_evaluator(FOUR)
    losses = [remove_action(problem, ("A", "C", "D"), a, evaluate).loss_within_t for a in "ACD"]
    assert sum(losses) == 9  # while ACD saves 7 ODs over no action


def test_removing_prerequisite_removes_dependents(tmp_path):
    actions = {"P": {"bus_hours": 0, "new_infra_km": 0.5, "distance_m": 0},
               "L": {"bus_hours": 6, "new_infra_km": 0, "distance_m": 0},
               "X": {"bus_hours": 6, "new_infra_km": 0, "distance_m": 0}}
    ods = [{"od_id": "O1", "disrupted_min": 60, "options": [{"requires": ["L", "P"], "minutes": 40}]},
           {"od_id": "O2", "disrupted_min": 60, "options": [{"requires": ["X"], "minutes": 40}]}]
    fx = {"label": LABEL, "limits": FOUR["limits"], "actions": actions, "exclusions": [], "ods": ods}
    problem = static_problem(fx, objective_file(tmp_path, "count"), prerequisites={"L": ("P",)})
    r = remove_action(problem, ("L", "P", "X"), "P", make_fixture_evaluator(fx))
    assert ids(r.remaining) == "X"
    assert r.also_removed == ("L",)
    assert r.messages == ("removing P also removes L",)
    assert r.loss_within_t == 1


def test_removal_without_objective_decision(tmp_path):
    problem = static_problem(FOUR, tmp_path / "no_objective")
    with pytest.raises(FileNotFoundError):
        remove_action(problem, ("A", "C", "D"), "A", make_fixture_evaluator(FOUR))



# --- real model whose routing adapter rejects stress factors ---

def test_stress_not_available_when_adapter_rejects_factors(tmp_path):
    setup = stress_setup(tmp_path)
    fixture_evaluator_for = setup.evaluator_for

    def adapter_evaluator_for(scenario):
        default = scenario.speed_factor == 1 and all(f == 1 for f in (scenario.headway_factor_by_group or {}).values())
        if not default:
            def reject(request):
                raise engine.StressFactorsNotSupported("non-default stress factors are not supported yet")
            return reject
        return fixture_evaluator_for(scenario)

    r = stress_test(StressSetup(setup.problem_for, adapter_evaluator_for, setup.grid, setup.H_hours), ("A", "C", "D"))
    assert r.status == "not_available"
    assert r.message.startswith("stress not available for this model yet")
    assert r.points == () and r.worst is None and r.reoptimization is None


def test_fixture_stress_status_ok(acd_stress):
    assert acd_stress.status == "ok" and acd_stress.message == ""
