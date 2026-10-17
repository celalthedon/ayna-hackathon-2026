"""compile_package and validate_package on the fixture_stress catalog. Expected values were computed by hand."""
from pathlib import Path

import pytest

from citypilot.decision_engine import (
    Candidate,
    DecisionProblem,
    Limits,
    RoutingPatch,
    Scenario,
    build_request,
    compile_package,
    enumerate_packages,
    load_fixture,
    make_catalog_patches,
    make_catalog_resources,
    make_problem_for,
    patches_hash,
    validate_package,
)

from decision_testkit import FIXTURE_HASHES, catalog as kit_catalog, fixture_context, link, parking as kit_parking, service

FX = load_fixture(Path(__file__).resolve().parent / "fixtures" / "decision" / "fixture_stress.json")
DEFAULT = Scenario(1.0, 1.0, 3.0)


def catalog(parking=None):
    cat = FX["catalog"]
    svc = lambda k, v: service(k, v["base_headway_min"], v["full_cycle_km"], v["speed_kmh"], v["stops_per_cycle"],
                               v["dwell_s"], v["layover_min"], v["coverage"])
    return kit_catalog(
        service_groups={k: svc(k, v) for k, v in cat["service_groups"].items()},
        prebuilt_services={k: svc(k, v) for k, v in cat["prebuilt_services"].items()},
        links={k: link(k, v["kind"], v["length_m"], v["requires_construction"]) for k, v in cat["links"].items()},
        parking=parking or {},
    )


CATALOG = catalog()
CANDIDATES = {c: Candidate(c, a["kind"], target_id=a.get("target_id"), pct=a.get("pct"),
                           link_ids=tuple(a.get("link_ids", ()))) for c, a in FX["actions"].items()}


def problem(tmp_path, *, candidates=CANDIDATES, cat=CATALOG, prerequisites=None, requires_bike=frozenset(), profile="P"):
    lim = FX["limits"]
    return DecisionProblem(
        candidate_ids=tuple(sorted(candidates)),
        exclusions=(("A", "B"),),
        prerequisites=prerequisites or {},
        distance_m={c: 0 for c in candidates},
        limits=Limits(lim["B_h_bus_hours"], lim["K_new_infra_km"], lim["N_a_actions"], 1024),
        thresholds_min=(40, 45, 50),
        primary_t_min=45,
        cap_min=120,
        objective_dir=tmp_path,
        model_hashes=FIXTURE_HASHES,
        context=fixture_context(profile=profile, patches_for=make_catalog_patches(candidates, cat, DEFAULT)),
        resources=make_catalog_resources(candidates, cat, DEFAULT),
        requires_bike=frozenset(requires_bike),
    )


# --- compile_package ---

def test_headway_cut_is_a_final_exact_value():
    assert compile_package(["A"], CATALOG, DEFAULT, CANDIDATES) == (RoutingPatch(kind="set_service_headway", target_id="SG_R2", headway_min=6.375),)
    assert compile_package(["B"], CATALOG, DEFAULT, CANDIDATES)[0].headway_min == 5.25


def test_full_package_patches_in_canonical_order():
    assert compile_package(["A", "C", "D"], CATALOG, DEFAULT, CANDIDATES) == (
        RoutingPatch(kind="set_service_headway", target_id="SG_R2", headway_min=6.375),
        RoutingPatch(kind="activate_service", target_id="SVC_SHUTTLE"),
        RoutingPatch(kind="activate_link", target_id="L_D"),
    )


def test_order_never_changes_patches_or_hash(tmp_path):
    a = compile_package(["D", "C", "A"], CATALOG, DEFAULT, CANDIDATES)
    b = compile_package(["A", "C", "D"], CATALOG, DEFAULT, CANDIDATES)
    assert a == b and patches_hash(a) == patches_hash(b)
    p = problem(tmp_path)
    assert build_request(p, ("D", "C", "A")) == build_request(p, ("A", "C", "D"))


def test_stress_headway_factor_applied_once(tmp_path):
    # base 7.5 x factor 0.8 = 6.0, cut 15% -> 5.1 (never 7.5 x 0.8 x 0.8 x 0.85)
    scenario = Scenario(2 / 3, 1.0, 3.0, headway_factor_by_group={"SG_R2": 0.8})
    assert compile_package(["A"], CATALOG, scenario, CANDIDATES)[0].headway_min == 5.1
    p = make_problem_for(problem(tmp_path), CANDIDATES, CATALOG)(scenario)
    request = build_request(p, ("A",))
    assert request.patches == (RoutingPatch(kind="set_service_headway", target_id="SG_R2", headway_min=5.1),)
    assert request.speed_factor == 2 / 3 and request.headway_factor_by_group == {"SG_R2": 0.8}
    assert request.state == "mitigated" and build_request(p, ()).state == "disrupted"


def test_baseline_parking_produces_no_patch():
    cat = catalog({"P_OLD": kit_parking("P_OLD", True), "P_NEW": kit_parking("P_NEW", False)})
    candidates = CANDIDATES | {"E": Candidate("E", "link_bundle", link_ids=("L_D",), parking_ids=("P_OLD", "P_NEW"))}
    assert compile_package(["E"], cat, DEFAULT, candidates) == (
        RoutingPatch(kind="activate_link", target_id="L_D"),
        RoutingPatch(kind="enable_parking", target_id="P_NEW"),
    )


def test_compile_rejects_bad_targets():
    with pytest.raises(ValueError, match="X"):
        compile_package(["X"], CATALOG, DEFAULT, CANDIDATES)
    bad = CANDIDATES | {"S": Candidate("S", "activate_service", target_id="SG_R2")}
    with pytest.raises(ValueError, match="not a pre-built service"):
        compile_package(["S"], CATALOG, DEFAULT, bad)
    with pytest.raises(ValueError, match="two headway actions"):
        compile_package(["A", "B"], CATALOG, DEFAULT, CANDIDATES)


def test_patch_shape_rules():
    with pytest.raises(ValueError):
        RoutingPatch(kind="set_service_headway", target_id="SG_R2")          # needs a headway
    with pytest.raises(ValueError):
        RoutingPatch(kind="activate_link", target_id="L_D", headway_min=5.0)              # headway only for headway patches
    with pytest.raises(ValueError):
        RoutingPatch(kind="teleport", target_id="X")


# --- validate_package ---

def test_valid_package_returns_its_resources(tmp_path):
    res = validate_package(["A", "C", "D"], problem(tmp_path), Limits(30, 2, 3, 1024), "P")
    assert res.added_bus_hours == 24


@pytest.mark.parametrize("ids, message", [
    (["A", "X"], "unknown candidate ids"),
    (["A", "B"], "exclusion group conflict"),
])
def test_validate_rejects(tmp_path, ids, message):
    with pytest.raises(ValueError, match=message):
        validate_package(ids, problem(tmp_path), Limits(30, 2, 3, 1024), "P")


def test_validate_missing_prerequisite(tmp_path):
    p = problem(tmp_path, prerequisites={"D": ("C",)})
    with pytest.raises(ValueError, match="missing prerequisite: D needs"):
        validate_package(["D"], p, Limits(30, 2, 3, 1024), "P")


def test_validate_bike_only_action_in_profile_p(tmp_path):
    p = problem(tmp_path, requires_bike={"D"})
    with pytest.raises(ValueError, match="require a bike"):
        validate_package(["D"], p, Limits(30, 2, 3, 1024), "P")
    assert validate_package(["D"], p, Limits(30, 2, 3, 1024), "B").new_infra_km == 0.04
    assert all("D" not in pkg for pkg in enumerate_packages(p))


def test_validate_limits_name_the_limit(tmp_path):
    with pytest.raises(ValueError, match=r"bus-hours 24 > B_h 20"):
        validate_package(["A", "C", "D"], problem(tmp_path), Limits(20, 2, 3, 1024), "P")
    with pytest.raises(ValueError, match=r"actions 3 > N_a 2"):
        validate_package(["A", "C", "D"], problem(tmp_path), Limits(30, 2, 2, 1024), "P")
