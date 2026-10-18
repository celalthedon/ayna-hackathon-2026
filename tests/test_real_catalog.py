"""Real catalog (part B): R2/R14 cut variants + Celal's modelled M services; AYNA reference package."""
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot.decision_engine import Limits, enumerate_packages, violates_exclusions  # noqa: E402
from citypilot.decision_real import (  # noqa: E402
    AYNA_REFERENCE,
    AYNA_REFERENCE_LABEL,
    GATE_DIRS,
    M_ASSETS_NOT_LOADED,
    MAssetsNotLoaded,
    m_service_candidates,
    m_service_exclusions,
    real_catalog,
    real_problem,
)

M_IDS = [f"SVC_M{n}_{v}" for n in (1, 2, 3, 5, 6) for v in "AB"]


def fake_catalog(headways=None, drop=()):
    headways = headways or {}
    services = {i: SimpleNamespace(base_headway_min=headways.get(i, 6.0 if i.endswith("A") else 9.0))
                for i in M_IDS if i not in drop}
    return SimpleNamespace(service_groups={"SG_R2": None, "SG_R14": None}, prebuilt_services=services)


def test_m_candidates_and_one_exclusion_group_per_line():
    candidates = m_service_candidates(fake_catalog())
    assert sorted(candidates) == sorted(M_IDS)
    assert all(c.kind == "activate_service" and c.target_id == i for i, c in candidates.items())
    assert m_service_exclusions(candidates) == tuple((f"SVC_M{n}_A", f"SVC_M{n}_B") for n in (1, 2, 3, 5, 6))


def test_missing_m_assets_is_a_clear_status():
    with pytest.raises(MAssetsNotLoaded, match=M_ASSETS_NOT_LOADED):
        m_service_candidates(SimpleNamespace(prebuilt_services={}))
    with pytest.raises(MAssetsNotLoaded, match="SVC_M6_B"):
        m_service_candidates(fake_catalog(drop=("SVC_M6_B",)))


def test_m_headways_must_match_the_registered_variants():
    with pytest.raises(ValueError, match="SVC_M2_A"):
        m_service_candidates(fake_catalog({"SVC_M2_A": 7.5}))


def test_ayna_reference_package():
    assert AYNA_REFERENCE == ("SVC_M1_A", "SVC_M2_A", "SVC_M3_A", "SVC_M5_A", "SVC_M6_A")
    assert AYNA_REFERENCE_LABEL == ("AYNA-announced express lines "
                                    "(modelled: stops from official images, path and headway assumed)")


def test_real_catalog_groups():
    candidates, exclusions = real_catalog(fake_catalog())
    assert len(candidates) == 14 and len(exclusions) == 7
    assert sorted(i for g in exclusions for i in g) == sorted(candidates)


# --- with the bundle ---

@pytest.fixture(scope="module")
def models():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit:
        pytest.skip("Set CITYPILOT_TEST_BUNDLE to the explicit immutable C4 bundle")
    from citypilot.routing_engine import load_model
    bundle = Path(explicit)
    return {"original": load_model(bundle, bundle / "config"),
            "m": load_model(bundle, ROOT / "supplements" / "m_services_v1" / "config")}


def test_original_model_has_no_m_assets(models):
    from citypilot.routing_engine import get_catalog
    with pytest.raises(MAssetsNotLoaded, match=M_ASSETS_NOT_LOADED):
        real_catalog(get_catalog(models["original"]))


def expected_count(groups, n_a):
    """7 exclusion groups of 2 variants, no BIKE: sum over j <= N_a of C(7, j) * 2^j."""
    return sum(math.comb(groups, j) * 2 ** j for j in range(n_a + 1))


@pytest.mark.parametrize("n_a, count", [(3, 379), (4, 939), (5, 1611)])
def test_real_enumeration_counts(models, n_a, count):
    from citypilot.routing_engine import get_catalog
    candidates, exclusions = real_catalog(get_catalog(models["m"]))
    problem = real_problem(models["m"], "P", Limits(30.0, 2.0, n_a, 3000), candidates, exclusions, 3.0)
    assert problem.objective_dir == GATE_DIRS[1]
    assert len(list(enumerate_packages(problem))) == count == expected_count(7, n_a)


def test_ayna_reference_on_the_m_model(models):
    from citypilot.routing_engine import get_catalog
    candidates, exclusions = real_catalog(get_catalog(models["m"]))
    problem = real_problem(models["m"], "P", Limits(30.0, 2.0, 5, 3000), candidates, exclusions, 3.0)
    assert not violates_exclusions(problem, AYNA_REFERENCE)
    resources = problem.resources(AYNA_REFERENCE)
    assert resources.status == "known" and resources.added_bus_hours == 105.0 and resources.action_count == 5
