"""compute_resources and vehicles tests. Expected values were computed by hand."""
import math
from pathlib import Path

import pytest

from citypilot.decision_engine import (
    Candidate,
    Link,
    ModelCatalog,
    Parking,
    Scenario,
    ServiceGroup,
    compute_resources,
    load_scenario,
    vehicles,
)

LIMITS_PATH = Path(__file__).resolve().parents[1] / "config" / "limits.yaml"
FIXTURE = "fixture"


def service(sid, headway, km, speed, stops, dwell, layover, coverage="full"):
    return ServiceGroup(
        service_group_id=sid, pattern_ids=(f"{sid}_out", f"{sid}_in"), base_headway_min=headway,
        full_cycle_km=km, speed_kmh=speed, stops_per_cycle=stops, dwell_s=dwell, layover_min=layover,
        coverage=coverage, status=FIXTURE, speed_status=FIXTURE,
    )


@pytest.fixture
def catalog():
    return ModelCatalog(
        service_groups={
            "SG_R2": service("SG_R2", 10, 12, 15, 30, 20, 5),
            "SG_R14": service("SG_R14", 12, None, None, None, None, None, coverage="partial"),
        },
        prebuilt_services={
            "SVC_SHUTTLE": service("SVC_SHUTTLE", 8, 9, 18, 6, 30, 4),
            "SVC_LOOP": service("SVC_LOOP", 20, 4, 20, 4, 30, 3),
        },
        links={
            "L1": Link("L1", "walk", 300, False, FIXTURE),
            "L2": Link("L2", "bike", 1200, True, FIXTURE),
            "L3": Link("L3", "walk", 40, True, FIXTURE),
        },
        parking={"P1": Parking("P1", FIXTURE)},
    )


C = {
    "a1": Candidate("a1", "headway_cut", target_id="SG_R2", pct=0.20),
    "a1b": Candidate("a1b", "headway_cut", target_id="SG_R2", pct=0.30),
    "a8": Candidate("a8", "headway_cut", target_id="SG_R2", pct=0.05),
    "a2": Candidate("a2", "headway_cut", target_id="SG_R14", pct=0.20),
    "a3": Candidate("a3", "activate_service", target_id="SVC_SHUTTLE"),
    "a3b": Candidate("a3b", "activate_service", target_id="SVC_SHUTTLE"),
    "a9": Candidate("a9", "activate_service", target_id="SVC_LOOP"),
    "a45": Candidate("a45", "link_bundle", link_ids=("L2",), parking_ids=("P1",)),
    "a6": Candidate("a6", "link_bundle", link_ids=("L1",)),
    "a7": Candidate("a7", "link_bundle", link_ids=("L2", "L3")),
}

BASE = Scenario(speed_factor=1.0, headway_factor=1.0, H_hours=3.0)


def run(catalog, *ids, scenario=BASE):
    return compute_resources([C[i] for i in ids], catalog, scenario)


def svc(result, sid):
    return next(s for s in result.per_service if s.service_id == sid)


def test_e1_cut_20pct(catalog):
    r = run(catalog, "a1")
    assert r.added_bus_hours == 3
    assert (svc(r, "SG_R2").base_vehicles, svc(r, "SG_R2").new_vehicles) == (7, 8)
    assert r.new_infra_km == 0
    assert r.action_count == 1
    assert r.status == "known"
    assert r.warnings == ()


def test_e2_exact_ratio_not_rounded_up(catalog):
    r = run(catalog, "a1b")
    assert r.added_bus_hours == 6
    assert (svc(r, "SG_R2").base_vehicles, svc(r, "SG_R2").new_vehicles) == (7, 9)


def test_e3_cut_without_extra_vehicles(catalog):
    r = run(catalog, "a8")
    s = svc(r, "SG_R2")
    assert r.added_bus_hours == 0
    assert math.isclose(s.new_headway_min, 9.5)
    assert (s.base_vehicles, s.new_vehicles) == (7, 7)
    assert r.warnings == ("zero_cost_uses_slack",)
    assert s.warnings == ("zero_cost_uses_slack",)


def test_e4_activate_shuttle(catalog):
    r = run(catalog, "a3")
    s = svc(r, "SVC_SHUTTLE")
    assert r.added_bus_hours == 15
    assert math.isclose(s.new_cycle_min, 37)
    assert (s.base_vehicles, s.new_vehicles) == (0, 5)
    assert r.status == "known"


def test_e5_headway_exceeds_cycle(catalog):
    r = run(catalog, "a9")
    s = svc(r, "SVC_LOOP")
    assert r.added_bus_hours == 3
    assert math.isclose(s.new_cycle_min, 17)
    assert (s.base_vehicles, s.new_vehicles) == (0, 1)
    assert r.warnings == ("headway_exceeds_cycle",)
    assert s.warnings == ("headway_exceeds_cycle",)


def test_e6_mixed_package(catalog):
    r = run(catalog, "a1", "a3", "a45")
    assert r.added_bus_hours == 18
    assert math.isclose(r.new_infra_km, 1.2)
    assert r.action_count == 3
    assert r.status == "known"


def test_e7_shared_link_counted_once(catalog):
    r = run(catalog, "a45", "a7")
    assert math.isclose(r.new_infra_km, 1.24)
    assert r.action_count == 2


def test_e8_link_without_construction(catalog):
    r = run(catalog, "a6")
    assert r.new_infra_km == 0
    assert r.action_count == 1


def test_e9_partial_coverage_is_unknown(catalog):
    r = run(catalog, "a1", "a2")
    assert r.status == "unknown"
    assert r.added_bus_hours is None
    assert r.known_part_bus_hours == 3


def test_e10_two_cuts_on_same_group(catalog):
    with pytest.raises(ValueError) as exc:
        run(catalog, "a1", "a1b")
    assert "a1" in str(exc.value) and "a1b" in str(exc.value)


def test_two_activations_of_same_service(catalog):
    with pytest.raises(ValueError) as exc:
        run(catalog, "a3", "a3b")
    assert "a3" in str(exc.value) and "a3b" in str(exc.value)


def test_e11_slower_speed(catalog):
    r = run(catalog, "a1", scenario=Scenario(speed_factor=0.8, headway_factor=1.0, H_hours=3.0))
    s = svc(r, "SG_R2")
    assert math.isclose(s.new_cycle_min, 75)
    assert (s.base_vehicles, s.new_vehicles) == (8, 10)
    assert r.added_bus_hours == 6


def test_e12_scenario_base_headway(catalog):
    r = run(catalog, "a1", scenario=Scenario(speed_factor=1.0, headway_factor=0.8, H_hours=3.0))
    s = svc(r, "SG_R2")
    assert math.isclose(s.base_headway_min, 8)
    assert math.isclose(s.new_headway_min, 6.4)
    assert (s.base_vehicles, s.new_vehicles) == (8, 10)
    assert r.added_bus_hours == 6


def test_e13_package_order(catalog):
    assert run(catalog, "a3", "a1") == run(catalog, "a1", "a3")


def test_e14_missing_h(tmp_path):
    with pytest.raises(TypeError):
        Scenario(speed_factor=1.0, headway_factor=1.0)
    with pytest.raises(ValueError):
        Scenario(speed_factor=1.0, headway_factor=1.0, H_hours=None)
    no_h = tmp_path / "limits.yaml"
    no_h.write_text("B_h_bus_hours: 30.0\n")
    with pytest.raises(ValueError):
        load_scenario(no_h, speed_factor=1.0, headway_factor=1.0)


@pytest.mark.parametrize("name", ["speed_factor", "headway_factor", "H_hours"])
def test_scenario_rejects_bool(name):
    values = {"speed_factor": 1.0, "headway_factor": 1.0, "H_hours": 3.0, name: True}
    with pytest.raises(ValueError):
        Scenario(**values)


def test_h_from_limits_yaml():
    assert load_scenario(LIMITS_PATH, speed_factor=1.0, headway_factor=1.0).H_hours == 3.0


def test_e15_vehicle_rounding():
    assert vehicles(66.00000000000001, 6) == 11
    assert vehicles(66.06, 6) == 12
    assert vehicles(63, 10) == 7


@pytest.mark.parametrize("headway", [0, -5])
def test_e16_bad_headway(headway):
    with pytest.raises(ValueError):
        vehicles(63, headway)


@pytest.mark.parametrize("pct", [0, -0.1, 1, 1.5])
def test_e17_bad_pct(pct):
    with pytest.raises(ValueError):
        Candidate("bad", "headway_cut", target_id="SG_R2", pct=pct)
