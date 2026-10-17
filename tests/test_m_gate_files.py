"""M-bound gates use actual loaded-model request identities; no OD recomputation."""
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot.decision_engine import ObjectiveModelMismatch, load_objective
from citypilot.routing_engine import baseline_request, load_model

BASE_GATES = ROOT / "config/objective"
M_GATES = BASE_GATES / "m_services_v1"
EXPECTED = {
    "P": ("count", {"40": 1424, "45": 1148, "50": 799}),
    "B": ("sum", {"40": 0, "45": 0, "50": 0}),
}


@pytest.fixture(scope="module")
def identities():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit:
        pytest.skip("Set CITYPILOT_TEST_BUNDLE to the explicit immutable C4 bundle")
    bundle = Path(explicit)
    models = {
        "original": load_model(bundle, bundle / "config"),
        "m": load_model(bundle, ROOT / "supplements/m_services_v1/config"),
    }
    assert not models["original"].get("supplement_hash")
    assert models["m"]["supplement_hash"] == "42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a"
    hashes = {}
    for kind, model in models.items():
        for profile in EXPECTED:
            requests = {state: baseline_request(model, state, profile)
                        for state in ("normal", "disrupted")}
            assert all(not r.patches and r.speed_factor == 1.0 and r.headway_factor_by_group is None
                       for r in requests.values())
            hashes[kind, profile] = {state: r.config_hash for state, r in requests.items()}
    return hashes


@pytest.mark.parametrize("profile", EXPECTED)
def test_m_record_scope_counts_and_shares(profile):
    record = json.loads((M_GATES / f"objective_decision_{profile}.json").read_text())
    objective, lost = EXPECTED[profile]
    assert record["profile"] == profile
    assert record["objective"] == objective
    assert record["lost_T"] == lost
    assert record["total_OD"] == 2718
    assert record["thresholds"] == {
        "T_min": [40, 45, 50], "min_lost": 20, "low_share": 0.15, "high_share": 0.9,
    }
    assert record["share_T"] == {threshold: value / 2718 for threshold, value in lost.items()}


@pytest.mark.parametrize("profile", EXPECTED)
def test_m_records_accept_actual_m_baseline_requests(profile, identities):
    record = json.loads((M_GATES / f"objective_decision_{profile}.json").read_text())
    actual = identities["m", profile]
    assert record["input_hashes"] == actual
    assert load_objective(M_GATES, profile, actual) == EXPECTED[profile][0]


@pytest.mark.parametrize("profile", EXPECTED)
def test_original_records_still_accept_actual_original_baseline_requests(profile, identities):
    record = json.loads((BASE_GATES / f"objective_decision_{profile}.json").read_text())
    actual = identities["original", profile]
    assert record["input_hashes"] == actual
    assert load_objective(BASE_GATES, profile, actual) == EXPECTED[profile][0]


@pytest.mark.parametrize("profile", EXPECTED)
@pytest.mark.parametrize("record_kind", ["original", "m"])
def test_cross_model_records_are_rejected(profile, record_kind, identities):
    directory = BASE_GATES if record_kind == "original" else M_GATES
    other = "m" if record_kind == "original" else "original"
    assert identities[record_kind, profile] != identities[other, profile]
    with pytest.raises(ObjectiveModelMismatch, match="objective decided for another model"):
        load_objective(directory, profile, identities[other, profile])


@pytest.mark.parametrize("profile", EXPECTED)
@pytest.mark.parametrize("record_kind", ["original", "m"])
def test_profiles_cannot_share_one_hash_pair(profile, record_kind, identities):
    directory = BASE_GATES if record_kind == "original" else M_GATES
    other_profile = "B" if profile == "P" else "P"
    with pytest.raises(ObjectiveModelMismatch, match="objective decided for another model"):
        load_objective(directory, profile, identities[record_kind, other_profile])
