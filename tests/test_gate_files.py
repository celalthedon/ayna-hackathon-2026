"""Committed real gate decisions (A6). Expected values agreed before any optimisation."""
import json
import os
from pathlib import Path

import pytest

from citypilot.decision_engine import count_lost, gate_objective, load_objective

ROOT = Path(__file__).resolve().parents[1]
OBJECTIVES = ROOT / "config" / "objective"
EXPECTED = {
    "P": ("count", {"40": 1424, "45": 1148, "50": 799}),
    "B": ("sum", {"40": 0, "45": 0, "50": 0}),
}
BUNDLE = os.environ.get("CITYPILOT_TEST_BUNDLE")


def record(profile):
    return json.loads((OBJECTIVES / f"objective_decision_{profile}.json").read_text())


@pytest.mark.parametrize("profile", ["P", "B"])
def test_committed_gate_file(profile):
    objective, lost = EXPECTED[profile]
    r = record(profile)
    assert (r["objective"], r["profile"], r["lost_T"], r["total_OD"]) == (objective, profile, lost, 2718)
    assert r["thresholds"] == {"T_min": [40, 45, 50], "min_lost": 20, "low_share": 0.15, "high_share": 0.9}
    assert all(len(h) == 64 for h in r["input_hashes"].values())
    assert load_objective(OBJECTIVES, profile, r["input_hashes"]) == objective


@pytest.mark.skipif(not BUNDLE, reason="Set CITYPILOT_TEST_BUNDLE to the explicit validated bundle path")
@pytest.mark.parametrize("profile", ["P", "B"])
def test_gate_file_matches_the_current_model(profile):
    from citypilot.routing_engine import baseline_request, evaluate_package, load_model

    model = load_model(Path(BUNDLE), Path(BUNDLE) / "config")
    normal = evaluate_package(model, baseline_request(model, "normal", profile))
    disrupted = evaluate_package(model, baseline_request(model, "disrupted", profile))
    r = record(profile)
    assert r["input_hashes"] == {"normal": normal.config_hash, "disrupted": disrupted.config_hash}
    lost = count_lost(normal, disrupted)
    assert {str(t): n for t, n in lost.items()} == r["lost_T"]
    assert gate_objective(lost, len(normal.od_results))[0] == r["objective"]
