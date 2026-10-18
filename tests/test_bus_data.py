"""Checks on data/curated bus files written by the 'Bus data curation' notebook section."""
import csv
import json
import math
from pathlib import Path

import pytest

from citypilot.contracts import ModelCatalog, Provenance, ServiceGroup, ServicePattern
from citypilot.decision_engine import Candidate, Scenario, compute_resources

CURATED = Path(__file__).resolve().parents[1] / "data" / "curated"
EXPECTED_STOPS = {("2", "A"): 46, ("2", "B"): 45, ("14", "A"): 30, ("14", "B"): 29}
INTERMEDIATE = {"2": 87, "14": 55}
SNAP_LIMIT_M = 50
DWELL_S = 25


def read_csv(name):
    path = CURATED / name
    assert path.exists(), f"missing curated file {path}"
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def patterns():
    return read_csv("bus_patterns.csv")


@pytest.fixture(scope="module")
def services():
    return {r["route"]: r for r in read_csv("bus_services.csv")}


@pytest.fixture(scope="module")
def stops():
    return read_csv("bus_stops.csv")


def by_direction(patterns):
    groups = {}
    for r in patterns:
        groups.setdefault((r["route"], r["direction"]), []).append(r)
    return {k: sorted(v, key=lambda r: int(r["seq"])) for k, v in groups.items()}


def test_stop_counts_and_seq_without_gaps(patterns):
    groups = by_direction(patterns)
    assert set(groups) == set(EXPECTED_STOPS)
    for key, rows in groups.items():
        assert len(rows) == EXPECTED_STOPS[key], key
        assert [int(r["seq"]) for r in rows] == list(range(1, len(rows) + 1)), key


def test_every_pattern_stop_is_in_bus_stops(patterns, stops):
    ids = [r["stop_id"] for r in stops]
    assert len(ids) == len(set(ids))
    assert {r["stop_id"] for r in patterns} <= set(ids)
    for r in stops:
        assert r["name"] and r["source"] and r["evidence"]
        assert -90 < float(r["lat"]) < 90 and -180 < float(r["lon"]) < 180


def test_intermediate_stops(services):
    for route, n in INTERMEDIATE.items():
        assert int(services[route]["intermediate_stops"]) == n


def test_geometry_has_one_linestring_per_route_direction():
    with open(CURATED / "bus_route_geometry.geojson", encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj["features"]
    assert {(f["properties"]["route"], f["properties"]["direction"]) for f in feats} == set(EXPECTED_STOPS)
    assert len(feats) == len(EXPECTED_STOPS)
    assert all(f["geometry"]["type"] == "LineString" and len(f["geometry"]["coordinates"]) > 2 for f in feats)


def test_speed_formula_roundtrip_and_routlength_basis(services):
    expected_rounded = {"2": 24.2, "14": 24.1}
    for route, s in services.items():
        dur, n = float(s["duration_min"]), int(s["intermediate_stops"])
        geom_speed = float(s["speed_kmh"])
        formula = 60 * float(s["cycle_km_geometry"]) / (2 * dur - n * DWELL_S / 60)
        assert math.isclose(geom_speed, formula, rel_tol=0, abs_tol=1e-12)
        # plugging the stored speed back reproduces twice the mean one-way duration
        back = 60 * float(s["cycle_km_geometry"]) / geom_speed + n * DWELL_S / 60
        assert abs(back - 2 * dur) < 1e-6
        # published routLength basis (cross-check only)
        rl_speed = 60 * float(s["routLength_km"]) / (2 * dur - n * DWELL_S / 60)
        assert round(rl_speed, 1) == expected_rounded[route]
        print(f"route {route}: speed routLength basis {rl_speed!r}, geometry basis {geom_speed!r}")


def test_segments_sum_to_polyline_length_between_first_and_last_stop(patterns):
    for key, rows in by_direction(patterns).items():
        total = sum(float(r["segment_m"]) for r in rows if r["segment_m"] != "")
        span = float(rows[-1]["chainage_m"]) - float(rows[0]["chainage_m"])
        assert abs(total - span) < 1, key
        assert rows[-1]["segment_m"] == ""
        for a, b in zip(rows, rows[1:]):
            assert math.isclose(float(a["segment_m"]), float(b["chainage_m"]) - float(a["chainage_m"]), abs_tol=1e-6)


def test_violations_are_flagged_in_notes(patterns):
    for key, rows in by_direction(patterns).items():
        for prev, r in zip([None] + rows, rows):
            bad = float(r["snap_m"]) > SNAP_LIMIT_M
            if prev is not None and float(r["chainage_m"]) <= float(prev["chainage_m"]):
                bad = True
            if bad:
                assert r["notes"].strip(), (key, r["seq"])


def test_statuses_and_inputs(services):
    assert set(services) == set(INTERMEDIATE)
    for s in services.values():
        assert s["speed_status"] == "assumption"
        assert s["duration_status"] == "published"
        assert s["dwell_status"] == "assumption" and s["layover_status"] == "assumption"
        assert float(s["dwell_s"]) == DWELL_S
        assert float(s["layover_min"]) == 10  # 5 min per terminal x 2
        assert s["coverage"] == "full"
        assert s["speed_method"] and s["headway_source"] and s["notes"]
    assert float(services["2"]["duration_min"]) == 73
    assert float(services["14"]["duration_min"]) == 45


def test_headways(services):
    expected = {"2": (6, 7.5, 10, "published"), "14": (4.5, 5, 11, "assumption")}
    for route, (lo, default, hi, status) in expected.items():
        s = services[route]
        got = (float(s["headway_low_min"]), float(s["headway_default_min"]), float(s["headway_high_min"]))
        assert got == (lo, default, hi)
        assert s["headway_status"] == status


RAW_ASSUMPTIONS = CURATED.parent / "raw" / "ayna_bus" / "phase1" / "templates" / "assumptions.csv"
HEADWAY_PARAM = {"2": "P1", "14": "P2"}
APPLIES_TO_CHANGES = {"P6": {"applies_to": "metro_all_adjacent_stations"},
                      "P8": {"applies_to": "metro_platform_street_both_directions"}}
ADDED_PARAMS = ("P19", "P20", "P21")
RAW_ASSUMPTIONS_P16_P18 = CURATED.parent / "raw" / "ayna_bus" / "phase2" / "templates" / "assumptions_P16_P18.csv"


@pytest.fixture(scope="module")
def assumptions():
    return {r["param_id"]: r for r in read_csv("assumptions.csv")}


def test_curated_p1_p2_replace_first_round_estimate(assumptions):
    expected = {
        "P1": ("6", "7.5", "10", "published", "2026-08-31"),
        "P2": ("4.5", "5", "11", "assumption", "2025-10-01"),
    }
    for pid, (lo, default, hi, status, date) in expected.items():
        r = assumptions[pid]
        assert (float(r["value_low"]), float(r["value_default"]), float(r["value_high"])) == (float(lo), float(default), float(hi))
        assert r["status"] == status and r["source_date"] == date
        assert r["filled_by"] == "Ali"
        assert "superseded: 4/6/10, first-round estimate without sources" in r["notes"]
        assert r["source_url"].startswith("https://")
    assert "oxu.az" in assumptions["P1"]["source_url"]
    assert "lot 333" in assumptions["P2"]["justification"].lower()


def test_p2_high_raised_from_eta_observations(assumptions):
    notes = assumptions["P2"]["notes"]
    assert "previous value_high 8" in notes and "4.5-13 min" in notes and "not measured" in notes


def test_p21_m_express_design_headway(assumptions):
    r = assumptions["P21"]
    assert (r["unit"], float(r["value_low"]), float(r["value_default"]), float(r["value_high"])) == ("min", 4, 6, 10)
    assert r["applies_to"] == "M1 M2 M3 M5 M6" and r["status"] == "assumption" and r["filled_by"] == "Ali"
    assert r["source_url"] == "data/raw/ayna_bus/m_research/" and r["source_date"] == "2026-08-04"
    assert "AZERTAC 2026-08-04" in r["justification"] and "not human-verified" in r["notes"]


def test_curated_assumptions_keep_other_rows_unchanged(assumptions):
    raw = {}
    for path in (RAW_ASSUMPTIONS, RAW_ASSUMPTIONS_P16_P18):
        with open(path, newline="", encoding="utf-8-sig") as f:
            raw.update({r["param_id"]: r for r in csv.DictReader(f)})
    assert set(assumptions) == set(raw) | set(ADDED_PARAMS)
    for pid, r in raw.items():
        if pid in HEADWAY_PARAM.values():
            continue
        changed = APPLIES_TO_CHANGES.get(pid, {})
        assert {k: assumptions[pid][k] for k in r if k not in changed} == {k: v for k, v in r.items() if k not in changed}, pid


def test_service_headways_come_from_curated_assumptions(services, assumptions):
    for route, pid in HEADWAY_PARAM.items():
        s, a = services[route], assumptions[pid]
        got = tuple(float(s[k]) for k in ("headway_low_min", "headway_default_min", "headway_high_min"))
        assert got == tuple(float(a[k]) for k in ("value_low", "value_default", "value_high"))
        assert s["headway_status"] == a["status"]
        assert pid in s["headway_source"]


def test_length_diff_matches_columns(services):
    for s in services.values():
        diff = 100 * (float(s["cycle_km_geometry"]) - float(s["routLength_km"])) / float(s["routLength_km"])
        assert math.isclose(diff, float(s["length_diff_pct"]), abs_tol=1e-9)


def test_compute_resources_route2_base_cycle(services, patterns):
    source = Provenance(source_id="ayna-map-api", status="published", source="AYNA map API getBusById",
                        evidence="data/curated/bus_services.csv")
    stops = {}
    for r in sorted(patterns, key=lambda r: (r["pattern_id"], int(r["seq"]))):
        stops.setdefault((r["route"], r["direction"], r["pattern_id"]), []).append(r["stop_id"])
    service_patterns = tuple(ServicePattern(pattern_id=pid, route_id=route, direction_id=d, stop_ids=tuple(ids),
                                            provenance=source) for (route, d, pid), ids in stops.items())
    groups = {}
    for route, s in services.items():
        sid = f"SG_R{route}"
        groups[sid] = ServiceGroup(
            service_group_id=sid, pattern_ids=tuple(s["pattern_ids"].split(";")),
            base_headway_min=float(s["headway_default_min"]), full_cycle_km=float(s["cycle_km_geometry"]),
            speed_kmh=float(s["speed_kmh"]), stops_per_cycle=int(s["intermediate_stops"]),
            dwell_s=float(s["dwell_s"]), layover_min=float(s["layover_min"]), coverage=s["coverage"],
            field_status={"pattern_ids": "curated", "base_headway_min": s["headway_status"],
                          "full_cycle_km": "modelled", "speed_kmh": s["speed_status"], "stops_per_cycle": "curated",
                          "dwell_s": s["dwell_status"], "layover_min": s["layover_status"], "coverage": "curated"},
            provenance=source,
        )
    catalog = ModelCatalog(model_version="curated-bus", od_set_id="none", service_groups=groups, prebuilt_services={},
                           links={}, parking={}, patterns=service_patterns, sources=(source,),
                           stop_ids=tuple(sorted({sid for ids in stops.values() for sid in ids})))
    cut = Candidate("cut", "headway_cut", target_id="SG_R2", pct=0.2)
    result = compute_resources([cut], catalog, Scenario(speed_factor=1.0, headway_factor=1.0, H_hours=3.0))
    base_cycle = next(x for x in result.per_service if x.service_id == "SG_R2").base_cycle_min
    assert abs(base_cycle - (2 * 73 + float(services["2"]["layover_min"]))) < 1


def test_source_provenance_tracked():
    curated = json.loads((CURATED / "SOURCE_ayna_bus.json").read_text(encoding="utf-8"))
    raw_path = CURATED.parent / "raw" / "ayna_bus" / "SOURCE.json"
    if raw_path.exists():
        assert curated["zip_sha256"] == json.loads(raw_path.read_text(encoding="utf-8"))["zip_sha256"]


def test_assumptions_p1_to_p21_complete(assumptions):
    assert [f"P{i}" for i in range(1, 22)] == sorted(assumptions, key=lambda p: int(p[1:]))
    for pid, r in assumptions.items():
        assert r["status"].strip(), pid
        try:
            low, default, high = (float(r[k]) for k in ("value_low", "value_default", "value_high"))
        except ValueError:
            continue  # non-numeric parameter (P15: yes/no)
        assert low <= default <= high, pid


def test_p6_p8_scope_decisions(assumptions):
    p6, p8 = assumptions["P6"], assumptions["P8"]
    assert p6["applies_to"] == "metro_all_adjacent_stations"
    assert "applied to all lines; no per-line or per-station measurement (decision Ali 2026-10-17)" in p6["notes"]
    assert p8["applies_to"] == "metro_platform_street_both_directions"
    assert "entry assumed symmetric to exit; train waiting (headway/2) is added separately" in p8["notes"]
    assert (p6["value_low"], p6["value_default"], p6["value_high"]) == ("1.5", "2.5", "4")
    assert (p8["value_low"], p8["value_default"], p8["value_high"]) == ("2", "4", "7")


@pytest.mark.parametrize("pid, value, applies_to, evidence", [
    ("P19", 2.5, "metro_red", ["closure_measures.csv C34"]),
    ("P20", 8, "metro_purple", ["official_facts.csv F2", "closure_measures.csv C36"]),
])
def test_metro_headways_p19_p20(assumptions, pid, value, applies_to, evidence):
    r = assumptions[pid]
    assert (float(r["value_low"]), float(r["value_default"]), float(r["value_high"])) == (value, value, value)
    assert r["unit"] == "min" and r["applies_to"] == applies_to
    assert r["status"] == "published" and r["filled_by"] == "Ali"
    assert r["source_url"] == "https://metro.gov.az/route-change"
    assert r["justification"] == "official construction-period regime; no range published"
    for e in evidence:
        assert e in r["notes"]


def test_m_research_source_recorded():
    curated = json.loads((CURATED / "SOURCE_ayna_bus.json").read_text(encoding="utf-8"))
    (m,) = [s for s in curated["additional_sources"] if s["target"] == "data/raw/ayna_bus/m_research/"]
    assert m["zip_file"] == "CityPilot_M_lines_research.zip" and len(m["zip_sha256"]) == 64
    assert m["status"] == "AI research, not human-verified" and "P21" in m["used_by"]
    folder = CURATED.parent / "raw" / "ayna_bus" / "m_research"
    if folder.exists():  # raw data is local only (git-ignored)
        import hashlib
        assert {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()} == m["files_sha256"]
