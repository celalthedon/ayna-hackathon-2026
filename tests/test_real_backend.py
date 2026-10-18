"""Real decision API backend on the M-supplement model."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot.api_decision import cache_identity  # noqa: E402
from citypilot.decision_real import (  # noqa: E402
    AYNA_REFERENCE,
    GATE_DIRS,
    assumption_default,
    real_backend,
    real_input_hashes,
    verified_file,
)

HEADER = "od_id,origin_id,destination_id,profile,car_distance_km,status,snap_m,origin_snap_m,destination_snap_m\n"


def car_table(tmp_path):
    path = tmp_path / "od_car_distances.csv"
    path.write_text(HEADER + "od:P:x,origin:a,destination:b,P,4.0,modelled,1.0,1.0,1.0\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_file_fails_on_another_hash(tmp_path):
    path, sha = car_table(tmp_path)
    assert verified_file(path, sha) == path
    with pytest.raises(ValueError, match="is not the expected"):
        verified_file(path, "0" * 64)


def test_assumption_default():
    assert assumption_default("P13") == (0.97992, "assumption")
    with pytest.raises(ValueError, match="exactly one P99"):
        assumption_default("P99")


@pytest.fixture(scope="module")
def m_model():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit:
        pytest.skip("Set CITYPILOT_TEST_BUNDLE to the explicit immutable C4 bundle")
    from citypilot.routing_engine import load_model
    return load_model(Path(explicit), ROOT / "supplements" / "m_services_v1" / "config")


def test_real_backend_on_the_m_model(m_model, tmp_path):
    from citypilot.routing_engine import get_catalog
    path, sha = car_table(tmp_path)
    backend = real_backend(m_model, tmp_path / "cache", path, sha)
    catalog = get_catalog(m_model)
    assert cache_identity(backend.config_hash, backend.input_hashes) == cache_identity(
        catalog.model_version, real_input_hashes(m_model))  # same cache entries as the precompute
    assert len(backend.candidate_ids) == 14 and len(backend.exclusions) == 7
    assert backend.N_a_max == 5 and backend.limits.max_exact_packages == 3000
    assert backend.objective_dirs == GATE_DIRS and backend.reference_package_ids == AYNA_REFERENCE
    from citypilot.decision_engine import Scenario
    assert backend.resources_for(Scenario(1.0, 1.0, backend.H_hours))(AYNA_REFERENCE).added_bus_hours == 105.0
    with pytest.raises(ValueError, match="is not the expected"):
        real_backend(m_model, tmp_path / "cache", path, "0" * 64)
