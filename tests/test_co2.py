"""CO2 calculator. Expected values were computed by hand."""
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
    co2_for_package,
    load_fixture,
)

FIXTURE = load_fixture(Path(__file__).resolve().parent / "fixtures" / "decision" / "fixture_stress.json")
BUS_KG_PER_VKM = 0.97992  # P13 default
CAR_KG_PER_PKM = 0.125211  # P12 default
SCENARIO = Scenario(1.0, 1.0, 3.0)


def service(sid, v):
    return ServiceGroup(sid, (), v["base_headway_min"], v["full_cycle_km"], v["speed_kmh"], v["stops_per_cycle"],
                        v["dwell_s"], v["layover_min"], v["coverage"], "fixture", "fixture")


CAT = FIXTURE["catalog"]
CATALOG = ModelCatalog(
    service_groups={k: service(k, v) for k, v in CAT["service_groups"].items()},
    prebuilt_services={k: service(k, v) for k, v in CAT["prebuilt_services"].items()},
    links={k: Link(k, v["kind"], v["length_m"], v["requires_construction"], "fixture") for k, v in CAT["links"].items()},
    parking={k: Parking(k, "fixture") for k in CAT["parking"]},
)
CANDIDATES = {
    cid: Candidate(cid, a["kind"], target_id=a.get("target_id"), pct=a.get("pct"), link_ids=tuple(a.get("link_ids", ())))
    for cid, a in FIXTURE["actions"].items()
}


def co2(**kw):
    args = dict(bus_kg_per_vkm=BUS_KG_PER_VKM, car_kg_per_pkm=CAR_KG_PER_PKM)
    args.update(kw)
    return co2_for_package([CANDIDATES[c] for c in "ACD"], CATALOG, SCENARIO, **args)


def test_bus_vkm_per_action_and_total():
    r = co2(car_trip_km=6.0)
    assert abs(r.per_action_vkm["A"] - 188.047) < 0.001
    assert abs(r.per_action_vkm["C"] - 202.5) < 0.001
    assert r.per_action_vkm["D"] == 0
    assert abs(r.bus_vkm - 390.547) < 0.001
    assert abs(r.bus_kg - 382.705) < 0.001
    assert r.period_hours == 3


def test_break_even_at_6_km():
    r = co2(car_trip_km=6.0)
    assert abs(r.per_trip_car_kg - 0.7513) < 0.0001
    assert r.break_even_trips == 510
    assert r.status == "complete"


def test_break_even_at_national_reference():
    r = co2(car_trip_km=15.4)
    assert abs(r.per_trip_car_kg - 1.9282) < 0.0001
    assert r.break_even_trips == 199


def test_net_with_avoided_trips_keeps_negative():
    r = co2(car_trip_km=6.0, avoided_car_trips=300)
    assert abs(r.net_kg - (-157.33)) < 0.01


def test_without_car_trip_km_asks_the_user():
    r = co2()
    assert r.car_trip_km is None and r.per_trip_car_kg is None and r.break_even_trips is None
    assert r.status == "needs_car_trip_km"
    assert abs(r.bus_kg - 382.705) < 0.001
    assert r.reference_car_trip_km == 15.4
    assert "national" in r.reference_car_trip_km_label and "not corridor" in r.reference_car_trip_km_label


def test_avoided_trips_never_derived():
    assert co2(car_trip_km=6.0).net_kg is None


def test_units_and_notes():
    r = co2(car_trip_km=6.0)
    assert r.units == {
        "bus_vkm": "vehicle-km", "bus_kg": "kg CO2", "bus_kg_per_vkm": "kg CO2 / vehicle-km",
        "car_trip_km": "km", "car_kg_per_pkm": "kg CO2 / passenger-km", "per_trip_car_kg": "kg CO2 / trip",
        "break_even_trips": "car trips", "net_kg": "kg CO2", "period_hours": "h",
    }
    notes = " ".join(r.notes)
    assert "embodied emissions excluded" in notes
    assert "380 CNG buses (2021)" in notes and "consumption assumed" in notes


@pytest.mark.parametrize("bad", [{"car_trip_km": -1.0}, {"bus_kg_per_vkm": float("nan")}, {"avoided_car_trips": -5}])
def test_invalid_inputs_fail(bad):
    with pytest.raises(ValueError):
        co2(**({"car_trip_km": 6.0} | bad))


def test_partial_coverage_service_fails_loudly():
    partial = ServiceGroup("SG_R2", (), 7.5, None, None, None, None, None, "partial", "fixture", "fixture")
    catalog = ModelCatalog({"SG_R2": partial}, CATALOG.prebuilt_services, CATALOG.links, CATALOG.parking)
    with pytest.raises(ValueError, match="SG_R2"):
        co2_for_package([CANDIDATES["A"]], catalog, SCENARIO, bus_kg_per_vkm=BUS_KG_PER_VKM, car_kg_per_pkm=CAR_KG_PER_PKM)


# --- default car trip length: mean car_distance_km of the restored ODs (OD table, not the journey) ---

from citypilot.decision_engine import EvaluationResult, ODResult, mean_car_distance_km  # noqa: E402


def evaluation(minutes):
    ods = tuple(ODResult(f"OD{i + 1}", m if m is not None else 120, "reachable" if m is not None else "no_path")
                for i, m in enumerate(minutes))
    return EvaluationResult("t", (), ods, {}, 45, 0)


BEFORE = evaluation([60, 40, None, 50])   # OD2 already within 45
AFTER = evaluation([44, 40, 39, 50])      # restores OD1 and OD3


def test_mean_car_distance_of_restored_ods():
    km, source = mean_car_distance_km(AFTER, BEFORE, {"OD1": 4.0, "OD2": 100.0, "OD3": 8.0, "OD4": None})
    assert km == 6.0
    assert "2 restored ODs" in source and "car_distance_km" in source


@pytest.mark.parametrize("table", [None, {"OD1": 4.0}, {"OD1": 4.0, "OD3": None}])
def test_mean_car_distance_missing_is_null(table):
    km, source = mean_car_distance_km(AFTER, BEFORE, table)
    assert km is None and source.startswith("not available")


def test_mean_car_distance_nothing_restored():
    km, source = mean_car_distance_km(BEFORE, BEFORE, {"OD1": 4.0, "OD2": 1.0, "OD3": 8.0, "OD4": 2.0})
    assert km is None and "restores no OD" in source
