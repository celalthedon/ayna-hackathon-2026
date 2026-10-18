"""Real-model wiring for the decision layer: gate folders, gate hashes per profile and limits.

The decision maths stays in citypilot.decision_engine; this module only reads committed config
(config/limits.yaml, config/objective/...) and the loaded routing model's request identities.
"""
from pathlib import Path
from typing import Any, Mapping

from citypilot.decision_engine import (
    PROFILES,
    Candidate,
    DecisionProblem,
    Limits,
    RequestContext,
    Scenario,
    load_limits,
    make_catalog_patches,
    make_catalog_resources,
    select_objective_dir,
)

ROOT = Path(__file__).resolve().parents[2]
LIMITS_PATH = ROOT / "config" / "limits.yaml"
# original-bundle gates and the M-service-supplement gates (#21); the one decided on the loaded model is used
GATE_DIRS = (ROOT / "config" / "objective", ROOT / "config" / "objective" / "m_services_v1")


def real_limits(path: str | Path = LIMITS_PATH) -> Limits:
    """Limits come only from config/limits.yaml."""
    return load_limits(path)


def baseline_request(model: Any, state: str, profile: str):
    from citypilot.routing_engine import baseline_request as routing_baseline

    return routing_baseline(model, state, profile)


def gate_hashes(model: Any) -> dict[str, dict[str, str]]:
    """Per profile: the config_hash of the loaded model's canonical normal and disrupted requests."""
    return {profile: {state: baseline_request(model, state, profile).config_hash for state in ("normal", "disrupted")}
            for profile in PROFILES}


def gate_dirs_for(model_hashes: Mapping[str, Mapping[str, str]], directories=GATE_DIRS) -> dict[str, Path]:
    """Per profile: the gate folder decided on these hashes; raises 'objective decided for another model' otherwise."""
    return {profile: select_objective_dir(directories, profile, model_hashes[profile]) for profile in PROFILES}


# --- first real optimisation (A6 part 2): R2 / R14 headway cuts only ---

# brief A7: route 2 and route 14 headway -25 % or -50 % vs baseline, mutually exclusive per route
ROUTE_CUTS = {"SG_R2": "R2", "SG_R14": "R14"}
CUT_PCTS = (0.25, 0.50)


def route_cut_candidates(catalog) -> dict[str, Candidate]:
    """R2_CUT25, R2_CUT50, R14_CUT25, R14_CUT50 on the catalog's existing service groups; fails if one is missing."""
    missing = sorted(set(ROUTE_CUTS) - set(catalog.service_groups))
    if missing:
        raise ValueError(f"service groups {missing} not in the loaded model's catalog")
    return {f"{route}_CUT{round(pct * 100)}": Candidate(f"{route}_CUT{round(pct * 100)}", "headway_cut",
                                                        target_id=group, pct=pct)
            for group, route in ROUTE_CUTS.items() for pct in CUT_PCTS}


def route_cut_exclusions(candidates: Mapping[str, Candidate]) -> tuple[tuple[str, ...], ...]:
    """One exclusion group per route: its cut variants cannot be combined."""
    by_group: dict[str, list[str]] = {}
    for cid, c in candidates.items():
        by_group.setdefault(c.target_id, []).append(cid)
    return tuple(tuple(sorted(ids)) for _, ids in sorted(by_group.items()) if len(ids) > 1)


def closure_distance_m(model: Any, candidates: Mapping[str, Candidate]) -> dict[str, float]:
    """Straight-line metres (metric CRS) from the nearest stop served by the candidate's group to the nearer
    closure-link station. Used only to order the nearest-gap baseline, never for any journey."""
    from pyproj import Transformer

    links = model["links"]
    closure = links[links["is_closure_link"]]
    if len(closure) != 1:
        raise ValueError(f"expected one closure link, got {len(closure)}")
    station_ids = (closure.iloc[0]["from_station_id"], closure.iloc[0]["to_station_id"])
    to_metric = Transformer.from_crs("EPSG:4326", model["runtime"]["metric_crs"], always_xy=True)
    stations = [to_metric.transform(*model["stations"][s]["geometry"]["coordinates"]) for s in station_ids]
    stops = model["stops"].set_index("stop_id")
    nodes = model["bus_nodes"]
    result = {}
    for cid, c in candidates.items():
        served = sorted(set(nodes.loc[nodes["service_group_id"] == c.target_id, "stop_id"]))
        if not served:
            raise ValueError(f"{cid}: no stops served by {c.target_id}")
        points = [to_metric.transform(stops.at[s, "lon"], stops.at[s, "lat"]) for s in served]
        result[cid] = min(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5 for x, y in points for sx, sy in stations)
    return result


def real_problem(model: Any, profile: str, limits: Limits, candidates: Mapping[str, Candidate],
                 exclusions: tuple[tuple[str, ...], ...], H_hours: float, directories=GATE_DIRS) -> DecisionProblem:
    """DecisionProblem on the loaded model: catalog resources and patches, gate folder and hashes per profile."""
    from citypilot.routing_engine import get_catalog

    catalog = get_catalog(model)
    scenario = Scenario(1.0, 1.0, H_hours)
    hashes = gate_hashes(model)[profile]
    base = baseline_request(model, "disrupted", profile)
    return DecisionProblem(
        candidate_ids=tuple(sorted(candidates)), exclusions=exclusions, prerequisites={},
        distance_m=closure_distance_m(model, candidates), limits=limits,
        thresholds_min=tuple(base.thresholds_min), primary_t_min=base.primary_t_min, cap_min=base.cap_min,
        objective_dir=select_objective_dir(directories, profile, hashes), model_hashes=hashes,
        context=RequestContext(base.model_version, base.od_set_id, base.closure_id, profile, scenario,
                               make_catalog_patches(candidates, catalog, scenario)),
        resources=make_catalog_resources(candidates, catalog, scenario),
    )


def real_evaluator(model: Any):
    """The routing engine's evaluate_package on the loaded model."""
    from citypilot.routing_engine import evaluate_package

    return lambda request: evaluate_package(model, request)
