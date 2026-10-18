"""Decision API router. Expected values were computed by hand."""
import dataclasses
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from citypilot.api_decision import DecisionBackend, build_decision_router
from citypilot.decision_dev import fixture_stress_backend
from citypilot.decision_engine import Limits, ResourceResult, load_fixture, make_fixture_evaluator

from decision_testkit import FIXTURE_HASHES, write_objective as kit_write_objective

FIXTURE = load_fixture(Path(__file__).resolve().parent / "fixtures" / "decision" / "fixture_4action.json")


def table_resources(table):
    """Test-only resources from the fixture's per-action table."""
    def resources(ids):
        ids = set(ids)
        bus_hours = sum(table[i]["bus_hours"] for i in ids)
        km = sum(table[i]["new_infra_km"] for i in ids)
        return ResourceResult(bus_hours, bus_hours, km, len(ids), "known", (), ())
    return resources


class CountingEvaluators:
    def __init__(self, fixture):
        self.calls = 0
        self.evaluate = make_fixture_evaluator(fixture)

    def evaluator_for(self, profile, scenario):
        def evaluator(request):
            self.calls += 1
            return self.evaluate(request)
        return evaluator


def write_objective(directory, objective="count", hashes=FIXTURE_HASHES):
    """Committed objective for both profiles (set explicitly; the gate is not run)."""
    for profile in ("P", "B"):
        kit_write_objective(directory, objective, profile, hashes)
    return directory


def four_action_backend(tmp_path, counter, reference=("B", "C", "D"), objective=True):
    lim = FIXTURE["limits"]
    objective_dir = tmp_path / "objectives"
    if objective:
        write_objective(objective_dir)
    return DecisionBackend(
        config_hash="fixture_4action",
        input_hashes={"fixture": "fixture_4action"},
        candidate_ids=tuple(sorted(FIXTURE["actions"])),
        exclusions=tuple(tuple(g) for g in FIXTURE["exclusions"]),
        prerequisites={},
        distance_m={a: v["distance_m"] for a, v in FIXTURE["actions"].items()},
        limits=Limits(lim["B_h_bus_hours"], lim["K_new_infra_km"], lim["N_a_actions"], 1024),
        thresholds_min=(40, 45, 50),
        primary_t_min=lim["T_min"],
        cap_min=lim["C_min"],
        objective_dirs=(objective_dir,),
        model_hashes={profile: FIXTURE_HASHES for profile in ("P", "B")},
        model_version="fixture",
        od_set_id="fixture-ods",
        closure_id="closure-28may-nizami",
        H_hours=3.0,
        resources_for=lambda scenario: table_resources(FIXTURE["actions"]),
        evaluator_for=counter.evaluator_for,
        cache_dir=tmp_path / "cache",
        N_a_max=4,
        B_h_max=120.0,
        reference_package_ids=reference,
    )


def client_for(backend):
    app = FastAPI()
    app.include_router(build_decision_router(backend))
    return TestClient(app)


def strict_json(response):
    def reject(constant):
        raise ValueError(f"non-finite JSON constant {constant}")
    return json.loads(response.text, parse_constant=reject)


def optimize(client, B_h, N_a=3, K=2.0, profile="P"):
    return client.post("/decision/optimize", json={"B_h": B_h, "K": K, "N_a": N_a, "profile": profile})


@pytest.fixture
def counter():
    return CountingEvaluators(FIXTURE)


@pytest.fixture
def client(tmp_path, counter):
    return client_for(four_action_backend(tmp_path, counter))


# --- state ---

def test_state(client):
    s = strict_json(client.get("/decision/state"))
    assert {p: (o["value"], o["status"]) for p, o in s["objective"].items()} == {"P": ("count", "committed"),
                                                                              "B": ("count", "committed")}
    assert s["objective"]["P"]["objective_dir"].endswith("objectives")
    assert s["limits"]["B_h_bus_hours"] == 24 and s["limits"]["N_a_actions"] == 3
    assert s["profiles"] == ["P", "B"]
    assert s["config_hash"] == "fixture_4action"


# --- optimize and caching ---

def test_optimize_then_rerank_without_evaluator_calls(client, counter):
    r = strict_json(optimize(client, 24))
    assert r["recommendation"]["candidate_ids"] == ["A", "C", "D"]
    assert r["label"] == "exact" and r["objective"] == "count"
    assert [a["candidate_ids"] for a in r["alternatives"]] == [["A", "C"], ["C", "D"], ["B"]]
    assert r["alternatives"][0]["reason"] == "2 fewer ODs within 45 min"
    assert r["baselines"]["greedy"]["label"] == "simple greedy (solo gain)"
    assert r["config_hash"] == "fixture_4action" and r["request_hash"]
    calls = counter.calls
    assert calls == 12  # every valid package with <= 4 actions, once

    r = strict_json(optimize(client, 15))
    assert r["recommendation"]["candidate_ids"] == ["C", "D"] and r["recommendation"]["within_t"] == 5
    assert counter.calls == calls

    r = strict_json(optimize(client, 0))
    assert r["recommendation"]["candidate_ids"] == []
    assert counter.calls == calls


def test_disk_cache_survives_a_new_router(tmp_path, counter):
    optimize(client_for(four_action_backend(tmp_path, counter)), 24)
    calls = counter.calls
    assert list((tmp_path / "cache" / "evaluations").glob("*.json"))
    r = strict_json(optimize(client_for(four_action_backend(tmp_path, counter)), 15))
    assert r["recommendation"]["candidate_ids"] == ["C", "D"]
    assert counter.calls == calls


def test_profile_has_its_own_cache(client, counter):
    optimize(client, 24, profile="P")
    calls = counter.calls
    optimize(client, 24, profile="B")
    assert counter.calls == 2 * calls


# --- compare with AYNA ---

@pytest.mark.parametrize("reference, optimizer, verdict", [
    ("BCD", "BCD", "equal (model confirms reference)"),
    ("AD", "A", "equal, cheaper"),
    ("B", "CD", "optimizer better"),
])
def test_compare_ayna(tmp_path, counter, reference, optimizer, verdict):
    c = client_for(four_action_backend(tmp_path, counter, reference=tuple(reference)))
    r = strict_json(c.post("/decision/compare_ayna", json={"profile": "P"}))
    assert r["reference"]["candidate_ids"] == list(reference)
    assert r["optimizer"]["recommendation"]["candidate_ids"] == list(optimizer)
    assert r["limits"]["N_a_actions"] == 4
    assert r["limits"]["B_h_bus_hours"] == r["reference"]["bus_hours"]
    assert r["verdict"] == verdict


def test_compare_ayna_bcd_difference(client):
    r = strict_json(client.post("/decision/compare_ayna", json={"profile": "P"}))
    assert r["reference"]["bus_hours"] == 30 and r["reference"]["within_t"] == 8
    assert r["difference"] == {"within_t": 0, "capped_time_sum": 0, "bus_hours": 0, "new_km": 0, "actions": 0}


def test_compare_without_reference(tmp_path, counter):
    c = client_for(four_action_backend(tmp_path, counter, reference=None))
    assert c.post("/decision/compare_ayna", json={"profile": "P"}).status_code == 409


# --- validation and errors ---

@pytest.mark.parametrize("body", [
    {"B_h": -1, "K": 2, "N_a": 3, "profile": "P"},
    {"B_h": 24, "K": 3.5, "N_a": 3, "profile": "P"},
    {"B_h": 24, "K": 2, "N_a": 0, "profile": "P"},
    {"B_h": 24, "K": 2, "N_a": 5, "profile": "P"},
    {"B_h": 24, "K": 2, "N_a": 3, "profile": "X"},
])
def test_out_of_range_is_422(client, body):
    r = client.post("/decision/optimize", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]


def test_missing_objective_is_409(tmp_path, counter):
    c = client_for(four_action_backend(tmp_path, counter, objective=False))
    r = optimize(c, 24)
    assert r.status_code == 409 and r.json()["detail"] == "objective not committed"
    assert strict_json(c.get("/decision/state"))["objective"]["P"] == {"value": None, "status": "not committed"}
    assert counter.calls == 0


def test_unknown_action_is_422(client):
    r = client.post("/decision/remove", json={"package_ids": ["A", "C", "D"], "action_id": "X", "profile": "P"})
    assert r.status_code == 422


# --- remove ---

def test_remove(client):
    r = strict_json(client.post("/decision/remove", json={"package_ids": ["A", "C", "D"], "action_id": "C", "profile": "P"}))
    assert r["remaining"]["candidate_ids"] == ["A", "D"]
    assert r["loss_within_t"] == 5
    assert "not additive" in r["note"]


# --- stress and CO2 on the stress fixture (catalog via compute_resources) ---

@pytest.fixture
def stress_client(tmp_path):
    return client_for(fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache"))


def test_stress(stress_client):
    r = strict_json(stress_client.post("/decision/stress", json={"package_ids": ["A", "C", "D"], "profile": "P"}))
    assert len(r["points"]) == 9
    first = r["points"][0]
    assert (first["speed_level"], first["headway_level"], first["feasible"], first["bus_hours"], first["overrun"]) == \
        ("low", "low", False, 33, 3)
    assert (r["worst"]["speed_level"], r["worst"]["headway_level"]) == ("low", "low")
    assert r["reoptimization"]["recommendation"]["candidate_ids"] == ["C", "D"]
    assert "capped sum decides" in r["reoptimization_reason"]


def test_stress_not_available_without_grid(client):
    assert client.post("/decision/stress", json={"package_ids": ["A"], "profile": "P"}).status_code == 409


def test_co2(stress_client):
    r = strict_json(stress_client.post("/decision/co2", json={"package_ids": ["A", "C", "D"], "car_trip_km": 6.0}))
    assert r["break_even_trips"] == 510 and r["status"] == "complete"
    assert abs(r["bus_kg"] - 382.705) < 0.001
    assert r["units"]["bus_vkm"] == "vehicle-km"
    r = strict_json(stress_client.post("/decision/co2", json={"package_ids": ["A", "C", "D"]}))
    assert r["status"] == "needs_car_trip_km" and r["break_even_trips"] is None
    assert r["reference_car_trip_km"] == 15.4
    assert r["car_trip_km_source"] == "not available: the OD table has no car_distance_km"


def test_co2_default_car_trip_km_from_od_table(tmp_path):
    # at the default point ACD restores OD1, OD2, OD4-OD8 (OD3 stays at 55 min)
    restored = {od: 6.0 for od in ("OD1", "OD2", "OD4", "OD5", "OD6", "OD7", "OD8")}
    backend = fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache",
                                     od_car_distance_km=restored | {"OD3": None})
    r = strict_json(client_for(backend).post("/decision/co2", json={"package_ids": ["A", "C", "D"], "profile": "P"}))
    assert r["car_trip_km"] == 6.0 and r["break_even_trips"] == 510
    assert r["car_trip_km_status"] == "modelled"
    assert "7 restored ODs" in r["car_trip_km_source"]


def test_co2_default_is_null_when_a_restored_od_lacks_car_distance(tmp_path):
    backend = fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache",
                                     od_car_distance_km={"OD1": 6.0, "OD2": None})
    r = strict_json(client_for(backend).post("/decision/co2", json={"package_ids": ["A", "C", "D"], "profile": "P"}))
    assert r["car_trip_km"] is None and r["status"] == "needs_car_trip_km"
    assert r["car_trip_km_source"].startswith("not available: car_distance_km missing")


def test_co2_needs_a_catalog(client):
    assert client.post("/decision/co2", json={"package_ids": ["A"], "car_trip_km": 6.0}).status_code == 409


def test_co2_negative_input_is_422(stress_client):
    r = stress_client.post("/decision/co2", json={"package_ids": ["A"], "car_trip_km": -1})
    assert r.status_code == 422



def test_objective_for_another_model_is_409(tmp_path, counter):
    backend = four_action_backend(tmp_path, counter, objective=False)
    write_objective(tmp_path / "objectives", hashes={"normal": "old-normal", "disrupted": "old-disrupted"})
    c = client_for(backend)
    r = optimize(c, 24)
    assert r.status_code == 409 and r.json()["detail"] == "objective decided for another model"
    assert strict_json(c.get("/decision/state"))["objective"]["P"]["status"] == "objective decided for another model"
    assert counter.calls == 0


def test_objective_is_read_per_profile(tmp_path, counter):
    backend = four_action_backend(tmp_path, counter, objective=False)
    kit_write_objective(tmp_path / "objectives", "count", "P")
    c = client_for(backend)
    assert optimize(c, 24, profile="P").status_code == 200
    r = optimize(c, 24, profile="B")
    assert r.status_code == 409 and r.json()["detail"] == "objective not committed"


def test_stress_not_available_from_adapter(tmp_path):
    from citypilot.decision_engine import StressFactorsNotSupported

    backend = fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache")
    fixture_evaluator_for = backend.evaluator_for

    def adapter(profile, scenario):
        if scenario.speed_factor != 1 or any(f != 1 for f in (scenario.headway_factor_by_group or {}).values()):
            def reject(request):
                raise StressFactorsNotSupported("non-default stress factors")
            return reject
        return fixture_evaluator_for(profile, scenario)

    from dataclasses import replace
    c = client_for(replace(backend, evaluator_for=adapter))
    r = c.post("/decision/stress", json={"package_ids": ["A", "C", "D"], "profile": "P"})
    assert r.status_code == 200
    body = strict_json(r)
    assert body["status"] == "not_available"
    assert body["message"].startswith("stress not available for this model yet")
    assert body["points"] == [] and body["worst"] is None


# --- N_a_max and findings ---

def test_n_a_max_comes_from_the_backend(tmp_path, counter):
    c = client_for(dataclasses.replace(four_action_backend(tmp_path, counter), N_a_max=3))
    assert strict_json(c.get("/decision/state"))["N_a_max"] == 3
    r = optimize(c, 24, N_a=4)
    assert r.status_code == 422 and "exceeds N_a_max 3" in r.json()["detail"]
    assert optimize(c, 24, N_a=3).status_code == 200


def test_default_n_a_cannot_exceed_n_a_max(tmp_path, counter):
    with pytest.raises(ValueError, match="exceeds N_a_max"):
        dataclasses.replace(four_action_backend(tmp_path, counter), N_a_max=2)


FIXTURE_IDENTITY = {"config_hash": "fixture_4action", "input_hashes": {"fixture": "fixture_4action"}}


def test_finding_is_shown_not_an_error(tmp_path, counter):
    from citypilot.api_decision import Finding
    finding = "B: no catalog action changes bike travel times"
    c = client_for(dataclasses.replace(four_action_backend(tmp_path, counter),
                                       findings={"B": Finding(finding, FIXTURE_IDENTITY, None)}))
    assert strict_json(c.get("/decision/state"))["findings"] == {"B": finding}
    r = optimize(c, 24, profile="B")
    assert r.status_code == 200 and r.json()["finding"] == finding
    assert optimize(c, 24, profile="P").json()["finding"] is None


@pytest.mark.parametrize("stale", [
    {"model_identity": {"config_hash": "other-model", "input_hashes": {"fixture": "fixture_4action"}}},
    {"catalog_hash": "design_only-catalog"},
])
def test_a_finding_for_another_model_or_catalog_is_never_shown(tmp_path, counter, stale):
    from citypilot.api_decision import Finding
    f = Finding(**({"text": "B: no catalog action changes bike travel times", "model_identity": FIXTURE_IDENTITY,
                    "catalog_hash": None} | stale))
    c = client_for(dataclasses.replace(four_action_backend(tmp_path, counter), findings={"B": f}))
    assert strict_json(c.get("/decision/state"))["findings"] == {}
    assert optimize(c, 24, profile="B").json()["finding"] is None


def test_co2_coverage_then_break_even_from_the_entered_trip_length(tmp_path):
    backend = fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache",
                                     od_car_distance_km={"OD1": 6.0, "OD2": None})
    c = client_for(backend)
    r = strict_json(c.post("/decision/co2", json={"package_ids": ["A", "C", "D"], "profile": "P"}))
    assert r["status"] == "needs_car_trip_km" and r["break_even_trips"] is None
    assert r["car_distance_coverage"] == {"restored": 7, "missing": 6, "by_reason": {"absent": 6}}
    r = strict_json(c.post("/decision/co2", json={"package_ids": ["A", "C", "D"], "profile": "P", "car_trip_km": 6.0}))
    assert r["status"] == "complete" and r["car_trip_km_status"] == "user" and r["car_trip_km"] == 6.0
    assert r["break_even_trips"] == 510  # same as the modelled 6 km default
    assert r["car_distance_coverage"]["missing"] == 6


def test_stress_evaluates_only_what_it_needs(tmp_path):
    from collections import Counter
    from citypilot.decision_engine import enumerate_packages
    backend = fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache")
    calls = Counter()

    def counting(profile, scenario):
        evaluate = backend.evaluator_for(profile, scenario)
        def wrapped(request):
            calls[(scenario.speed_factor, tuple(sorted((scenario.headway_factor_by_group or {}).items())))] += 1
            return evaluate(request)
        return wrapped

    c = client_for(dataclasses.replace(backend, evaluator_for=counting))
    r = strict_json(c.post("/decision/stress", json={"package_ids": ["A", "C", "D"], "profile": "P"}))
    assert r["status"] == "ok" and len(r["points"]) == 9
    stressed = {sc: n for sc, n in calls.items() if sc[0] != 1.0 or any(f != 1.0 for _, f in sc[1])}
    assert stressed and max(stressed.values()) < 12  # no first-use pass over every package at a grid point


def test_b_h_up_to_b_h_max_is_accepted_above_is_422(client):
    r = optimize(client, 105, N_a=3)
    assert r.status_code == 200 and r.json()["limits"]["B_h_bus_hours"] == 105
    assert optimize(client, 120, N_a=3).status_code == 200
    r = optimize(client, 120.5, N_a=3)
    assert r.status_code == 422 and "exceeds B_h_max 120.0" in r.json()["detail"]
    s = strict_json(client.get("/decision/state"))
    assert s["B_h_max"] == 120.0 and s["reference_bus_hours"] == 30  # fixture B 15 + C 15 + D 0


def test_b_h_max_comes_from_config_and_bounds_the_default(tmp_path, counter):
    from citypilot.decision_real import LIMITS_PATH, load_b_h_max
    import yaml
    assert load_b_h_max() == 120.0 == yaml.safe_load(LIMITS_PATH.read_text())["B_h_max"]
    with pytest.raises(ValueError, match="exceeds B_h_max"):
        dataclasses.replace(four_action_backend(tmp_path, counter), B_h_max=10.0)
