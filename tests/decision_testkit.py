"""Shared test helpers for the contract v1 shapes. Synthetic, test-only."""
import hashlib
import json
from pathlib import Path

from citypilot.contracts import (
    CONTRACT_VERSION,
    EvaluationResult,
    Link,
    ModelCatalog,
    ODResult,
    Parking,
    Provenance,
    RoutingRequest,
    ServiceGroup,
    ServicePattern,
)
from citypilot.decision_engine import RequestContext, Scenario, is_within, no_patches


def h(tag: str) -> str:
    """Contract-valid SHA-256 for a readable test tag."""
    return hashlib.sha256(tag.encode()).hexdigest()


FIXTURE_HASHES = {"normal": h("fixture-normal"), "disrupted": h("fixture-disrupted")}
CLOSURE_ID = "closure-28may-nizami"
DEFAULT_SCENARIO = Scenario(1.0, 1.0, 3.0)
SYNTHETIC = Provenance(source_id="synthetic-test-fixture", status="assumption", source="synthetic test fixture",
                       evidence="synthetic test fixture, not a city result", synthetic=True)
SERVICE_FIELDS = ("pattern_ids", "base_headway_min", "full_cycle_km", "speed_kmh", "stops_per_cycle", "dwell_s",
                  "layover_min", "coverage")


def fixture_context(profile="P", scenario=DEFAULT_SCENARIO, patches_for=no_patches) -> RequestContext:
    return RequestContext("fixture", "fixture-ods", CLOSURE_ID, profile, scenario, patches_for)


def make_request(ids, profile="P", thresholds=(40, 45, 50), t_min=45, cap=120) -> RoutingRequest:
    ids = tuple(sorted(set(ids)))
    return RoutingRequest(contract_version=CONTRACT_VERSION, model_version="fixture", od_set_id="fixture-ods",
                          state="mitigated" if ids else "disrupted", closure_id=CLOSURE_ID, profile=profile,
                          patches=(), speed_factor=1.0, headway_factor_by_group=None, thresholds_min=thresholds,
                          primary_t_min=t_min, cap_min=cap, candidate_ids=ids)


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
    """Evaluation from per-OD minutes; None means no_path. config_hash is a readable tag, hashed with h()."""
    ods = tuple(
        ODResult(od_id=f"OD{i + 1}", status="no_path", minutes=None, capped_minutes=cap) if m is None
        else ODResult(od_id=f"OD{i + 1}", status="over_cap" if m > cap else "reachable", minutes=m,
                      capped_minutes=min(m, cap))
        for i, m in enumerate(minutes)
    )
    within = {t: sum(1 for od in ods if is_within(od, t)) for t in thresholds}
    return EvaluationResult(contract_version=CONTRACT_VERSION, model_version="fixture", od_set_id="fixture-ods",
                            state=state, profile=profile, config_hash=h(config_hash), cap_min=cap, duration_ms=0.0,
                            od_results=ods, within_counts=within, capped_time_sum=sum(od.capped_minutes for od in ods),
                            primary_t_min=t_min, warnings=())


def service(sid, headway, km, speed, stops, dwell, layover, coverage="full", pattern_ids=None, status="assumption"):
    values = {"full_cycle_km": km, "speed_kmh": speed, "stops_per_cycle": stops, "dwell_s": dwell, "layover_min": layover}
    field_status = {f: "unverified" if values.get(f, 0) is None else status for f in SERVICE_FIELDS}
    return ServiceGroup(service_group_id=sid, pattern_ids=tuple(pattern_ids or (f"{sid}_A",)), base_headway_min=headway,
                        coverage=coverage, field_status=field_status, provenance=SYNTHETIC, **values)


def link(link_id, kind, length_m, requires_construction, status="assumption"):
    return Link(link_id=link_id, kind=kind, length_m=length_m, requires_construction=requires_construction,
                status=status, provenance=SYNTHETIC)


def parking(parking_id, baseline_enabled=False, status="assumption"):
    return Parking(parking_id=parking_id, status=status, baseline_enabled=baseline_enabled, provenance=SYNTHETIC)


def catalog(service_groups=None, prebuilt_services=None, links=None, parking=None) -> ModelCatalog:
    """Contract-valid catalog: one synthetic two-stop pattern per pattern id and one synthetic source."""
    groups = {**(service_groups or {}), **(prebuilt_services or {})}
    patterns = tuple(
        ServicePattern(pattern_id=p, route_id=sid, direction_id="A", stop_ids=(f"{p}_s1", f"{p}_s2"), provenance=SYNTHETIC)
        for sid, g in groups.items() for p in g.pattern_ids
    )
    return ModelCatalog(model_version="fixture", od_set_id="fixture-ods", service_groups=service_groups or {},
                        prebuilt_services=prebuilt_services or {}, links=links or {}, parking=parking or {},
                        patterns=patterns, sources=(SYNTHETIC,), stop_ids=tuple(s for p in patterns for s in p.stop_ids))
