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
    """Straight-line metres (metric CRS) from the nearest stop served by the candidate's service to the nearer
    closure-link station. Used only to order the nearest-gap baseline, never for any journey."""
    from pyproj import Transformer

    from citypilot.routing_engine import get_catalog

    links = model["links"]
    closure = links[links["is_closure_link"]]
    if len(closure) != 1:
        raise ValueError(f"expected one closure link, got {len(closure)}")
    station_ids = (closure.iloc[0]["from_station_id"], closure.iloc[0]["to_station_id"])
    to_metric = Transformer.from_crs("EPSG:4326", model["runtime"]["metric_crs"], always_xy=True)
    stations = [to_metric.transform(*model["stations"][s]["geometry"]["coordinates"]) for s in station_ids]
    catalog = get_catalog(model)
    services = {**catalog.service_groups, **catalog.prebuilt_services}
    stop_ids = {p.pattern_id: p.stop_ids for p in catalog.patterns}
    curated = model["stops"].set_index("stop_id")
    prebuilt = model.get("prebuilt_stops", {})

    def lonlat(stop_id):
        if stop_id in prebuilt:
            return prebuilt[stop_id]["coordinates"]
        return curated.at[stop_id, "lon"], curated.at[stop_id, "lat"]

    result = {}
    for cid, c in candidates.items():
        if c.target_id not in services:
            raise ValueError(f"{cid}: {c.target_id} not in the loaded model's catalog")
        served = sorted({s for pid in services[c.target_id].pattern_ids for s in stop_ids[pid]})
        points = [to_metric.transform(*lonlat(s)) for s in served]
        result[cid] = min(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5 for x, y in points for sx, sy in stations)
    return result


def real_problem(model: Any, profile: str, limits: Limits, candidates: Mapping[str, Candidate],
                 exclusions: tuple[tuple[str, ...], ...], H_hours: float, directories=GATE_DIRS,
                 scenario: Scenario | None = None) -> DecisionProblem:
    """DecisionProblem on the loaded model: catalog resources and patches, gate folder and hashes per profile.
    scenario defaults to speed and headway factors 1 (the stress test passes its grid points)."""
    from citypilot.routing_engine import get_catalog

    catalog = get_catalog(model)
    scenario = scenario or Scenario(1.0, 1.0, H_hours)
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


# --- real catalog (part B): R2 / R14 cuts + Celal's modelled M-service supplement ---

M_LINES = (1, 2, 3, 5, 6)  # M4 not announced; M9 excluded from the supplement
M_VARIANTS = {"A": 6.0, "B": 9.0}  # service suffix -> design headway (min), as registered in the supplement
AYNA_REFERENCE = tuple(f"SVC_M{n}_A" for n in M_LINES)
AYNA_REFERENCE_LABEL = ("AYNA-announced express lines "
                        "(modelled: stops from official images, path and headway assumed)")
M_ASSETS_NOT_LOADED = "M assets not loaded"


class MAssetsNotLoaded(ValueError):
    """The loaded model has no (or an incomplete) M-service supplement."""


def m_service_candidates(catalog) -> dict[str, Candidate]:
    """activate_service candidates SVC_M<n>_A (6 min) and SVC_M<n>_B (9 min) from the catalog's prebuilt services."""
    ids = [f"SVC_M{n}_{v}" for n in M_LINES for v in M_VARIANTS]
    missing = [i for i in ids if i not in catalog.prebuilt_services]
    if missing:
        raise MAssetsNotLoaded(f"{M_ASSETS_NOT_LOADED}: catalog lacks {missing}")
    wrong = {i: catalog.prebuilt_services[i].base_headway_min for i in ids
             if catalog.prebuilt_services[i].base_headway_min != M_VARIANTS[i[-1]]}
    if wrong:
        raise ValueError(f"M-service headways differ from the registered variants {M_VARIANTS}: {wrong}")
    return {i: Candidate(i, "activate_service", target_id=i) for i in ids}


def m_service_exclusions(candidates: Mapping[str, Candidate]) -> tuple[tuple[str, ...], ...]:
    """One exclusion group per M line: its 6-min and 9-min variants cannot be combined."""
    return tuple(tuple(sorted(c for c in candidates if c.startswith(f"SVC_M{n}_"))) for n in M_LINES)


def real_catalog(catalog) -> tuple[dict[str, Candidate], tuple[tuple[str, ...], ...]]:
    """R2/R14 cut variants plus the M services; raises MAssetsNotLoaded without the supplement. No BIKE:
    the routing engine does not implement activate_link and the catalog has no links."""
    cuts, m = route_cut_candidates(catalog), m_service_candidates(catalog)
    return cuts | m, route_cut_exclusions(cuts) + m_service_exclusions(m)


# --- precompute support ---

def load_n_a_max(path: str | Path = LIMITS_PATH) -> int:
    """N_a_max from config/limits.yaml: the largest N_a the API offers and the precompute enumerates."""
    import yaml

    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    value = raw.get("N_a_max")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path}: N_a_max must be an int >= 1, got {value!r}")
    return value


def real_input_hashes(model: Any) -> dict[str, str]:
    """Bundle, OD and supplement identity of the loaded model (cache key and manifest)."""
    hashes = {"bundle_hash": model["manifest"]["bundle_hash"], "od_hash": model["od"]["od_hash"]}
    if model.get("supplement_hash"):
        hashes["supplement_hash"] = model["supplement_hash"]
    return hashes


def catalog_hash(candidates: Mapping[str, Candidate], exclusions: tuple[tuple[str, ...], ...]) -> str:
    """Identity of a candidate catalog: every candidate's definition and the exclusion groups (SHA-256)."""
    import hashlib
    import json

    body = {"candidates": {cid: {"kind": c.kind, "target_id": c.target_id, "pct": c.pct, "link_ids": list(c.link_ids),
                                 "parking_ids": list(c.parking_ids), "requires_bike": c.requires_bike}
                           for cid, c in sorted(candidates.items())},
            "exclusions": sorted(sorted(g) for g in exclusions)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def design_only(candidates: Mapping[str, Candidate],
                exclusions: tuple[tuple[str, ...], ...]) -> tuple[dict[str, Candidate], tuple[tuple[str, ...], ...]]:
    """Drop the 9-min M variants (SVC_M*_B); groups left with one member are no longer exclusions."""
    kept = {c: v for c, v in candidates.items() if not (c.startswith("SVC_M") and c.endswith("_B"))}
    groups = tuple(g for g in (tuple(i for i in group if i in kept) for group in exclusions) if len(g) > 1)
    return kept, groups


def strongest_package(candidates: Mapping[str, Candidate], exclusions: tuple[tuple[str, ...], ...],
                      catalog) -> tuple[str, ...]:
    """The strongest variant of every exclusion group plus every ungrouped candidate: the deepest headway cut,
    the shortest-headway service. Adding options never makes a trip longer, so if this package changes no
    travel time, no smaller package can."""
    services = {**catalog.service_groups, **catalog.prebuilt_services}

    def strength(cid):
        c = candidates[cid]
        if c.kind == "headway_cut":
            return c.pct
        if c.kind == "activate_service":
            return -services[c.target_id].base_headway_min
        raise ValueError(f"{cid}: no strength order for kind {c.kind}")

    grouped = {i for g in exclusions for i in g}
    picked = [max(g, key=lambda i: (strength(i), i)) for g in exclusions]
    return tuple(sorted(picked + [c for c in candidates if c not in grouped]))


# --- real decision API backend ---

ASSUMPTIONS_PATH = ROOT / "data" / "curated" / "assumptions.csv"


def assumption_default(param_id: str, path: str | Path = ASSUMPTIONS_PATH) -> tuple[float, str]:
    """value_default and status of one assumptions.csv row; exactly one row must exist."""
    import csv

    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["param_id"] == param_id]
    if len(rows) != 1:
        raise ValueError(f"{path}: need exactly one {param_id} row, got {len(rows)}")
    return float(rows[0]["value_default"]), rows[0]["status"]


def verified_file(path: str | Path, sha256: str) -> Path:
    """The file, after checking its SHA-256; a mismatch fails loudly."""
    import hashlib

    path = Path(path)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != sha256:
        raise ValueError(f"{path}: SHA-256 {got} is not the expected {sha256}")
    return path


def real_backend(model: Any, cache_dir: str | Path, car_distances: str | Path, car_distances_sha256: str):
    """DecisionBackend on the loaded model with the real catalog (R2/R14 cuts + M services), limits and N_a_max
    from config/limits.yaml, gate folders per profile, the AYNA reference package and CO2 factors P12/P13.
    Its cache identity equals the precompute's (catalog model_version + real_input_hashes)."""
    from citypilot.api_decision import Co2Inputs, DecisionBackend
    from citypilot.decision_engine import load_od_car_distances, load_scenario
    from citypilot.routing_engine import get_catalog

    catalog = get_catalog(model)
    candidates, exclusions = real_catalog(catalog)
    H_hours = load_scenario(LIMITS_PATH, 1.0, 1.0).H_hours
    base = baseline_request(model, "disrupted", "P")
    bus_factor, bus_status = assumption_default("P13")
    car_factor, car_status = assumption_default("P12")
    return DecisionBackend(
        config_hash=catalog.model_version,
        input_hashes=real_input_hashes(model),
        candidate_ids=tuple(sorted(candidates)),
        exclusions=exclusions,
        prerequisites={},
        distance_m=closure_distance_m(model, candidates),
        limits=real_limits(),
        thresholds_min=tuple(base.thresholds_min),
        primary_t_min=base.primary_t_min,
        cap_min=base.cap_min,
        objective_dirs=GATE_DIRS,
        model_hashes=gate_hashes(model),
        model_version=base.model_version,
        od_set_id=base.od_set_id,
        closure_id=base.closure_id,
        H_hours=H_hours,
        resources_for=lambda scenario: make_catalog_resources(candidates, catalog, scenario),
        evaluator_for=lambda profile, scenario: real_evaluator(model),
        cache_dir=Path(cache_dir),
        N_a_max=load_n_a_max(),
        reference_package_ids=AYNA_REFERENCE,
        co2=Co2Inputs(candidates, catalog, bus_factor, car_factor,
                      {"bus_kg_per_vkm": f"P13 {bus_status}", "car_kg_per_pkm": f"P12 {car_status}"}),
        od_car_distance_km=load_od_car_distances(verified_file(car_distances, car_distances_sha256)),
        patches_for=lambda scenario: make_catalog_patches(candidates, catalog, scenario),
        catalog_hash=catalog_hash(candidates, exclusions),
    )
