"""Real-model wiring for the decision layer: gate folders, gate hashes per profile and limits.

The decision maths stays in citypilot.decision_engine; this module only reads committed config
(config/limits.yaml, config/objective/...) and the loaded routing model's request identities.
"""
from pathlib import Path
from typing import Any, Mapping

from citypilot.decision_engine import Limits, PROFILES, load_limits, select_objective_dir

ROOT = Path(__file__).resolve().parents[2]
LIMITS_PATH = ROOT / "config" / "limits.yaml"
# original-bundle gates and the M-service-supplement gates (#21); the one decided on the loaded model is used
GATE_DIRS = (ROOT / "config" / "objective", ROOT / "config" / "objective" / "m_services_v1")


def real_limits(path: str | Path = LIMITS_PATH) -> Limits:
    """Limits come only from config/limits.yaml."""
    return load_limits(path)


def gate_hashes(model: Any) -> dict[str, dict[str, str]]:
    """Per profile: the config_hash of the loaded model's canonical normal and disrupted requests."""
    from citypilot.routing_engine import baseline_request

    return {profile: {state: baseline_request(model, state, profile).config_hash for state in ("normal", "disrupted")}
            for profile in PROFILES}


def gate_dirs_for(model_hashes: Mapping[str, Mapping[str, str]], directories=GATE_DIRS) -> dict[str, Path]:
    """Per profile: the gate folder decided on these hashes; raises 'objective decided for another model' otherwise."""
    return {profile: select_objective_dir(directories, profile, model_hashes[profile]) for profile in PROFILES}
