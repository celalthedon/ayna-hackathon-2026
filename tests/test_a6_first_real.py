"""A6 part 2 wiring: R2 / R14 cut candidates on the loaded model (no M lines, no BIKE)."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot.decision_engine import build_request, enumerate_packages  # noqa: E402
from citypilot.decision_real import (  # noqa: E402
    GATE_DIRS,
    real_limits,
    real_problem,
    route_cut_candidates,
    route_cut_exclusions,
)

CUT_IDS = ["R14_CUT25", "R14_CUT50", "R2_CUT25", "R2_CUT50"]


def test_cut_candidates_and_exclusions():
    candidates = route_cut_candidates(SimpleNamespace(service_groups={"SG_R2": None, "SG_R14": None}))
    assert sorted(candidates) == CUT_IDS
    assert {c: (v.kind, v.target_id, v.pct) for c, v in candidates.items()}["R2_CUT50"] == ("headway_cut", "SG_R2", 0.5)
    assert route_cut_exclusions(candidates) == (("R14_CUT25", "R14_CUT50"), ("R2_CUT25", "R2_CUT50"))


def test_missing_service_group_fails_loudly():
    with pytest.raises(ValueError, match="SG_R14"):
        route_cut_candidates(SimpleNamespace(service_groups={"SG_R2": None}))


@pytest.fixture(scope="module")
def model():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit:
        pytest.skip("Set CITYPILOT_TEST_BUNDLE to the explicit immutable C4 bundle")
    from citypilot.routing_engine import load_model
    return load_model(Path(explicit), Path(explicit) / "config")


@pytest.mark.parametrize("profile", ["P", "B"])
def test_real_problem(model, profile):
    from citypilot.routing_engine import get_catalog
    import json

    candidates = route_cut_candidates(get_catalog(model))
    problem = real_problem(model, profile, real_limits(), candidates, route_cut_exclusions(candidates), 3.0)
    assert problem.objective_dir == GATE_DIRS[0]
    assert len(list(enumerate_packages(problem))) == 9  # 3 x 3 with one exclusion group per route
    assert all(0 < d < float("inf") for d in problem.distance_m.values())
    gate = json.loads((GATE_DIRS[0] / f"objective_decision_{profile}.json").read_text())
    assert build_request(problem, ()).config_hash == gate["input_hashes"]["disrupted"]  # no action = disrupted
    request = build_request(problem, ("R2_CUT25",))
    assert request.state == "mitigated" and [p.target_id for p in request.patches] == ["SG_R2"]
    assert problem.resources(("R2_CUT25",)).added_bus_hours == 21.0
