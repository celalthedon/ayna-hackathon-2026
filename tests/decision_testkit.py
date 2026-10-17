"""Shared test helpers for the v1 contract shapes. Synthetic, test-only."""
import json
from pathlib import Path

from citypilot.decision_engine import (
    CONTRACT_VERSION,
    EvaluationResult,
    ODResult,
    RequestContext,
    RoutingRequest,
    Scenario,
    ServiceGroup,
    is_within,
    no_patches,
)

FIXTURE_HASHES = {"normal": "fixture-normal", "disrupted": "fixture-disrupted"}
CLOSURE_ID = "closure-28may-nizami"
DEFAULT_SCENARIO = Scenario(1.0, 1.0, 3.0)


def fixture_context(profile="P", scenario=DEFAULT_SCENARIO, patches_for=no_patches) -> RequestContext:
    return RequestContext("fixture", "fixture-ods", CLOSURE_ID, profile, scenario, patches_for)


def make_request(ids, profile="P", thresholds=(40, 45, 50), t_min=45, cap=120) -> RoutingRequest:
    ids = tuple(sorted(set(ids)))
    return RoutingRequest(CONTRACT_VERSION, "fixture", "fixture-ods", "mitigated" if ids else "disrupted", CLOSURE_ID,
                          profile, (), 1.0, None, thresholds, t_min, cap, ids)


def write_objective(directory, objective, profile="P", hashes=FIXTURE_HASHES) -> Path:
    """Objective set explicitly for a fixture (the gate is not run); returns the objective directory."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"objective_decision_{profile}.json").write_text(json.dumps({
        "objective": objective, "profile": profile, "input_hashes": dict(hashes),
        "note": "set explicitly in test; gate not run"}))
    return directory


def make_evaluation(minutes, *, state="mitigated", profile="P", config_hash="t", cap=120, t_min=45,
                    thresholds=(40, 45, 50)) -> EvaluationResult:
    """Evaluation from per-OD minutes; None means no_path."""
    ods = tuple(
        ODResult(f"OD{i + 1}", "no_path", None, cap) if m is None
        else ODResult(f"OD{i + 1}", "over_cap" if m > cap else "reachable", m, min(m, cap))
        for i, m in enumerate(minutes)
    )
    within = {t: sum(1 for od in ods if is_within(od, t)) for t in thresholds}
    return EvaluationResult(CONTRACT_VERSION, "fixture", "fixture-ods", state, profile, config_hash, cap, 0.0, ods,
                            within, sum(od.capped_minutes for od in ods), t_min, ())


def service(sid, headway, km, speed, stops, dwell, layover, coverage="full", pattern_ids=()) -> ServiceGroup:
    status = "fixture"
    return ServiceGroup(sid, tuple(pattern_ids), headway, km, speed, stops, dwell, layover, coverage,
                        {f: status for f in ("base_headway_min", "full_cycle_km", "speed_kmh", "stops_per_cycle",
                                             "dwell_s", "layover_min")})
