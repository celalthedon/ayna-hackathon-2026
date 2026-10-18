"""Decision API router (prefix /decision).

The app mounts it once:  app.include_router(build_decision_router(backend))
All decision maths lives in citypilot.decision_engine; this module validates, caches and serialises.
"""
import hashlib
import json
import math
import uuid
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from citypilot.decision_engine import (
    Candidate,
    DecisionProblem,
    EvaluationResult,
    Limits,
    ModelCatalog,
    ODResult,
    ObjectiveModelMismatch,
    OdCarDistance,
    OptimizationResult,
    PackageOutcome,
    RequestContext,
    ResourceResult,
    RoutingPatch,
    RoutingRequest,
    Scenario,
    StressGrid,
    StressSetup,
    build_request,
    co2_for_package,
    enumerate_packages,
    is_feasible,
    load_objective,
    select_objective_dir,
    mean_car_distance_km,
    no_patches,
    optimize,
    rank_key,
    remove_action,
    stress_test,
)

PROFILES = ("P", "B")
MAX_ACTIONS = 4
OBJECTIVE_NOT_COMMITTED = "objective not committed"
OBJECTIVE_OTHER_MODEL = "objective decided for another model"


@dataclass(frozen=True)
class Co2Inputs:
    candidates: Mapping[str, Candidate]
    catalog: ModelCatalog
    bus_kg_per_vkm: float  # P13 default
    car_kg_per_pkm: float  # P12 default
    factor_statuses: Mapping[str, str]


@dataclass(frozen=True)
class DecisionBackend:
    """Everything the router needs; built once by the app from the model and config."""
    config_hash: str
    input_hashes: Mapping[str, str]
    candidate_ids: tuple[str, ...]
    exclusions: tuple[tuple[str, ...], ...]
    prerequisites: Mapping[str, tuple[str, ...]]
    distance_m: Mapping[str, float]
    limits: Limits
    thresholds_min: tuple[int, ...]
    primary_t_min: int
    cap_min: float
    objective_dirs: tuple[Path, ...]  # gate folders; per profile the one decided on this model is used
    model_hashes: Mapping[str, Mapping[str, str]]  # per profile: current normal / disrupted config_hash
    model_version: str
    od_set_id: str
    closure_id: str
    H_hours: float
    resources_for: Callable[[Scenario], Callable[[tuple[str, ...]], ResourceResult]]
    evaluator_for: Callable[[str, Scenario], Callable[[RoutingRequest], EvaluationResult]]  # (profile, scenario)
    cache_dir: Path
    reference_package_ids: tuple[str, ...] | None = None  # the AYNA real response, from the catalog
    stress_grid: StressGrid | None = None
    co2: Co2Inputs | None = None
    od_car_distance_km: Mapping[str, OdCarDistance] | None = None  # OD table car_distance_km
    patches_for: Callable[[Scenario], Callable[[tuple[str, ...]], tuple[RoutingPatch, ...]]] = lambda scenario: no_patches
    requires_bike: frozenset[str] = frozenset()

    def __post_init__(self):
        if set(self.model_hashes) != set(PROFILES):
            raise ValueError(f"model_hashes needs one normal/disrupted pair per profile {PROFILES}, got {sorted(self.model_hashes)}")
        for profile, pair in self.model_hashes.items():
            if set(pair) != {"normal", "disrupted"}:
                raise ValueError(f"model_hashes[{profile}] needs normal and disrupted, got {sorted(pair)}")
        if not self.objective_dirs:
            raise ValueError("objective_dirs is empty")


# --- request bodies (out of range -> 422) ---

class OptimizeBody(BaseModel):
    B_h: float = Field(ge=0, le=70, description="bus-hour budget")
    K: float = Field(ge=0, le=3, description="new infrastructure km budget")
    N_a: int = Field(ge=1, le=MAX_ACTIONS, description="maximum number of actions")
    profile: Literal["P", "B"]


class ProfileBody(BaseModel):
    profile: Literal["P", "B"]


class PackageBody(BaseModel):
    package_ids: list[str]
    profile: Literal["P", "B"]


class RemoveBody(PackageBody):
    action_id: str


class Co2Body(BaseModel):
    package_ids: list[str]
    profile: Literal["P", "B"] = "P"  # selects which ODs count as restored
    car_trip_km: float | None = Field(default=None, ge=0)
    bus_kg_per_vkm: float | None = Field(default=None, ge=0)
    car_kg_per_pkm: float | None = Field(default=None, ge=0)
    avoided_car_trips: float | None = Field(default=None, ge=0)


# --- JSON: never NaN/inf ---

def jsonable(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in fields(value) if not callable(getattr(value, f.name))}
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def package_json(o: PackageOutcome) -> dict:
    known = o.evaluation is not None
    return {
        "candidate_ids": list(o.candidate_ids),
        "within_t": o.within_t if known else None,
        "capped_time_sum": jsonable(o.capped_time_sum) if known else None,
        "bus_hours": jsonable(o.resources.added_bus_hours),
        "new_km": jsonable(o.resources.new_infra_km),
        "actions": o.resources.action_count,
        "feasible": o.feasible,
        "resources_status": o.resources.status,
        "warnings": list(o.resources.warnings),
        "reason": o.reason or None,
    }


def optimization_json(r: OptimizationResult) -> dict:
    return {
        "objective": r.objective,
        "label": r.label,
        "recommendation": package_json(r.recommendation),
        "recommendation_source": r.recommendation_source,
        "alternatives": [package_json(a) for a in r.alternatives],
        "baselines": {
            name: {"label": b.label, "package": package_json(b.package),
                   "steps": [jsonable(s) for s in b.steps]}
            for name, b in r.baselines.items()
        },
        "not_ranked": [package_json(o) for o in r.not_ranked],
        "feasible_count": r.feasible_count,
        "enumerated_count": r.enumerated_count,
        "approximate_reason": r.approximate_reason,
        "runtime_s": jsonable(r.runtime_s),
    }


# --- evaluation cache: one file per canonical request, data/cache/evaluations/<sha256>.json ---

def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _evaluator_scenario_key(scenario: Scenario) -> dict:
    """Scenario values the evaluator is built from. H_hours only changes resources, so it is left out;
    the scalar headway_factor is kept because a scenario without per-group factors falls back to it."""
    return {"speed_factor": scenario.speed_factor, "headway_factor": scenario.headway_factor,
            "headway_factor_by_group": dict(sorted((scenario.headway_factor_by_group or {}).items()))}


def _evaluation_to_dict(e: EvaluationResult) -> dict:
    d = {f.name: getattr(e, f.name) for f in fields(e)}
    d["od_results"] = [[o.od_id, o.status, o.minutes, o.capped_minutes] for o in e.od_results]
    d["within_counts"] = {str(t): n for t, n in e.within_counts.items()}
    d["warnings"] = list(e.warnings)
    return d


def _evaluation_from_dict(d: dict) -> EvaluationResult:
    return EvaluationResult(**(d | {
        "od_results": tuple(ODResult(od_id=o[0], status=o[1], minutes=o[2], capped_minutes=o[3])
                            for o in d["od_results"]),
        "within_counts": {int(t): n for t, n in d["within_counts"].items()},
        "warnings": tuple(d["warnings"]),
    }))


def _answers(result: EvaluationResult, request: RoutingRequest) -> bool:
    """result.validate_request(request) as a yes/no: contract, model_version, od_set_id, state, profile,
    config_hash, primary_t, cap and thresholds must all match the request."""
    try:
        result.validate_request(request)
    except ValueError:  # ContractError
        return False
    return True


class EvaluationCache:
    """Evaluates each canonical request once and keeps the result on disk.

    Key = the full routing request (contract_version, model_version, od_set_id, state, profile, closure,
    sorted patches, speed_factor, headway_factor_by_group, thresholds, primary_t, cap, candidate_ids)
    plus the model identity (config_hash, input_hashes) and the evaluator scenario. Limits (B_h, K, N_a)
    are not part of it. Each file stores its key; a stored key that differs from the recomputed one,
    an unreadable file or a result that does not match the request is a miss: re-evaluate and overwrite.
    Every returned result passes result.validate_request(request): a cached one that fails (disk or RAM)
    is discarded and recomputed; a fresh one that fails raises and is never cached.
    """

    def __init__(self, cache_dir: Path, model_identity: dict, scenario: Scenario, make_evaluator: Callable[[], Callable]):
        self.directory = Path(cache_dir) / "evaluations"
        self.model_identity = model_identity
        self.scenario_key = _evaluator_scenario_key(scenario)
        self._make_evaluator = make_evaluator
        self._evaluator = None
        self.results: dict[str, tuple[str, EvaluationResult]] = {}  # digest -> (canonical key, result)

    def key_for(self, request: RoutingRequest) -> str:
        return _canonical({"request": request.to_dict(), "model": self.model_identity, "scenario": self.scenario_key})

    def path_for(self, key: str) -> Path:
        return self.directory / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def lookup(self, request: RoutingRequest) -> EvaluationResult | None:
        """The valid stored result for this exact request (RAM, then disk), or None; never evaluates."""
        key = self.key_for(request)
        path = self.path_for(key)
        held = self.results.get(path.stem)
        if held is not None:
            if held[0] == key and _answers(held[1], request):
                return held[1]
            del self.results[path.stem]  # invalid RAM entry: discard
        result = self._read(path, key, request)
        if result is not None:
            self.results[path.stem] = (key, result)
        return result

    def evaluate(self, request: RoutingRequest) -> EvaluationResult:
        result = self.lookup(request)
        if result is not None:
            return result
        if self._evaluator is None:
            self._evaluator = self._make_evaluator()
        result = self._evaluator(request)
        result.validate_request(request)  # raises ContractError; nothing is cached
        key = self.key_for(request)
        path = self.path_for(key)
        self._write(path, key, result)
        self.results[path.stem] = (key, result)
        return result

    @staticmethod
    def _read(path: Path, key: str, request: RoutingRequest) -> EvaluationResult | None:
        try:
            stored = json.loads(path.read_text())
            if _canonical(stored["key"]) != key:
                return None
            result = _evaluation_from_dict(stored["result"])
            return result if _answers(result, request) else None
        except (OSError, ValueError, KeyError, TypeError):  # missing, corrupt or mismatched -> re-evaluate
            return None

    def _write(self, path: Path, key: str, result: EvaluationResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(_canonical({"key": json.loads(key), "result": _evaluation_to_dict(result)}))
        tmp.replace(path)


# --- router ---

def build_decision_router(backend: DecisionBackend) -> APIRouter:
    router = APIRouter(prefix="/decision", tags=["decision"])
    caches: dict[str, EvaluationCache] = {}

    model_identity = {"config_hash": backend.config_hash, "input_hashes": dict(sorted(backend.input_hashes.items()))}

    def cache_for(profile: str, scenario: Scenario) -> EvaluationCache:
        name = _canonical({"profile": profile, "scenario": _evaluator_scenario_key(scenario)})
        if name not in caches:
            caches[name] = EvaluationCache(backend.cache_dir, model_identity, scenario,
                                           lambda: backend.evaluator_for(profile, scenario))
        return caches[name]

    def default_scenario() -> Scenario:
        return Scenario(1.0, 1.0, backend.H_hours)

    def problem(scenario: Scenario, limits: Limits, profile: str) -> DecisionProblem:
        context = RequestContext(backend.model_version, backend.od_set_id, backend.closure_id, profile, scenario,
                                 backend.patches_for(scenario))
        return DecisionProblem(
            candidate_ids=backend.candidate_ids, exclusions=backend.exclusions, prerequisites=backend.prerequisites,
            distance_m=backend.distance_m, limits=limits, thresholds_min=backend.thresholds_min,
            primary_t_min=backend.primary_t_min, cap_min=backend.cap_min, objective_dir=objective_dir_for(profile),
            model_hashes=backend.model_hashes[profile], context=context, resources=backend.resources_for(scenario),
            requires_bike=backend.requires_bike,
        )

    def evaluator(profile: str, scenario: Scenario):
        """Cached evaluator; on first use it evaluates every valid package with <= MAX_ACTIONS once,
        so later limit changes only re-filter and re-rank."""
        cache = cache_for(profile, scenario)
        widest = problem(scenario, Limits(backend.limits.B_h_bus_hours, backend.limits.K_new_infra_km, MAX_ACTIONS,
                                          backend.limits.max_exact_packages), profile)  # enumeration uses N_a only
        packages = list(enumerate_packages(widest))
        if len(packages) <= backend.limits.max_exact_packages:
            for package in packages:
                cache.evaluate(build_request(widest, package))
        return cache.evaluate

    def objective_dir_for(profile: str) -> Path:
        return select_objective_dir(backend.objective_dirs, profile, backend.model_hashes[profile])

    def committed_objective(profile: str) -> str:
        try:
            return load_objective(objective_dir_for(profile), profile, backend.model_hashes[profile])
        except FileNotFoundError:
            raise HTTPException(409, OBJECTIVE_NOT_COMMITTED)
        except ObjectiveModelMismatch:
            raise HTTPException(409, OBJECTIVE_OTHER_MODEL)
        except ValueError as e:
            raise HTTPException(409, f"{OBJECTIVE_NOT_COMMITTED}: {e}")

    def stamp(result: dict, body: BaseModel | None, endpoint: str) -> dict:
        request = {"endpoint": endpoint, "body": body.model_dump() if body else None, "config_hash": backend.config_hash}
        result["config_hash"] = backend.config_hash
        result["request_hash"] = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
        return jsonable(result)

    def limits_from(body: OptimizeBody) -> Limits:
        return Limits(body.B_h, body.K, body.N_a, backend.limits.max_exact_packages)

    def run_optimize(limits: Limits, profile: str) -> OptimizationResult:
        scenario = default_scenario()
        return optimize(problem(scenario, limits, profile), evaluator(profile, scenario))

    def unprocessable(e: Exception) -> HTTPException:
        return HTTPException(422, str(e))

    @router.get("/state")
    def state() -> dict:
        objective = {}
        for profile in PROFILES:
            try:
                directory = objective_dir_for(profile)
                objective[profile] = {"value": load_objective(directory, profile, backend.model_hashes[profile]),
                                      "status": "committed", "objective_dir": str(directory)}
            except ObjectiveModelMismatch:
                objective[profile] = {"value": None, "status": OBJECTIVE_OTHER_MODEL}
            except (FileNotFoundError, ValueError):
                objective[profile] = {"value": None, "status": "not committed"}
        co2 = backend.co2
        return stamp({
            "limits": jsonable(backend.limits),
            "objective": objective,
            "input_hashes": dict(backend.input_hashes),
            "model_hashes": {p: dict(pair) for p, pair in backend.model_hashes.items()},
            "profiles": list(PROFILES),
            "thresholds_min": list(backend.thresholds_min),
            "primary_t_min": backend.primary_t_min,
            "H_hours": backend.H_hours,
            "reference_package_ids": list(backend.reference_package_ids) if backend.reference_package_ids else None,
            "stress_available": backend.stress_grid is not None,
            "co2_available": co2 is not None,
            "co2_defaults": None if co2 is None else {
                "bus_kg_per_vkm": co2.bus_kg_per_vkm, "car_kg_per_pkm": co2.car_kg_per_pkm,
                "statuses": dict(co2.factor_statuses)},
        }, None, "state")

    @router.post("/optimize")
    def post_optimize(body: OptimizeBody) -> dict:
        committed_objective(body.profile)
        try:
            result = run_optimize(limits_from(body), body.profile)
        except ValueError as e:
            raise unprocessable(e)
        return stamp(optimization_json(result) | {"limits": jsonable(limits_from(body))}, body, "optimize")

    @router.post("/compare_ayna")
    def post_compare(body: ProfileBody) -> dict:
        objective = committed_objective(body.profile)
        reference_ids = backend.reference_package_ids
        if not reference_ids:
            raise HTTPException(409, "no AYNA reference package in the catalog")
        scenario = default_scenario()
        try:
            reference_problem = problem(scenario, backend.limits, body.profile)
            reference_resources = reference_problem.resources(tuple(sorted(reference_ids)))
            if reference_resources.added_bus_hours is None:
                raise ValueError(f"reference package {reference_ids}: bus-hours unknown")
            limits = Limits(reference_resources.added_bus_hours, backend.limits.K_new_infra_km, MAX_ACTIONS,
                            backend.limits.max_exact_packages)
            result = optimize(problem(scenario, limits, body.profile), evaluator(body.profile, scenario))
            ref_eval = evaluator(body.profile, scenario)(build_request(reference_problem, reference_ids))
        except ValueError as e:
            raise unprocessable(e)
        rec = result.recommendation
        ref_key = rank_key(ref_eval, reference_resources, objective, reference_ids)
        rec_key = rank_key(rec.evaluation, rec.resources, objective, rec.candidate_ids)
        if not is_feasible(reference_resources, limits):
            verdict = "reference infeasible under these limits"
        elif rec_key[:2] < ref_key[:2]:
            verdict = "optimizer better"
        elif rec_key[2:5] < ref_key[2:5]:
            verdict = "equal, cheaper"
        else:
            verdict = "equal (model confirms reference)"
        reference = package_json(PackageOutcome(tuple(sorted(reference_ids)), ref_eval, reference_resources, True))
        best = package_json(rec)
        difference = {k: best[k] - reference[k] for k in ("within_t", "capped_time_sum", "bus_hours", "new_km", "actions")}
        return stamp({"reference": reference, "optimizer": optimization_json(result), "limits": jsonable(limits),
                      "difference": difference, "verdict": verdict}, body, "compare_ayna")

    @router.post("/stress")
    def post_stress(body: PackageBody) -> dict:
        committed_objective(body.profile)
        if backend.stress_grid is None:
            raise HTTPException(409, "stress grid not available for this model")
        setup = StressSetup(lambda sc: problem(sc, backend.limits, body.profile), lambda sc: evaluator(body.profile, sc),
                            backend.stress_grid, backend.H_hours)
        try:
            r = stress_test(setup, body.package_ids)
        except ValueError as e:
            raise unprocessable(e)
        if r.status != "ok":
            return stamp({"status": r.status, "message": r.message, "objective": r.objective,
                          "package_ids": list(r.package_ids), "points": [], "worst": None, "reoptimization": None,
                          "reoptimization_reason": "", "warnings": []}, body, "stress")
        points = [{"speed_level": p.speed_level, "headway_level": p.headway_level,
                   "speed_factor": p.scenario.speed_factor,
                   "headway_factors": dict(p.scenario.headway_factor_by_group or {}),
                   "feasible": p.feasible, "bus_hours": p.bus_hours, "overrun": p.overrun, "new_km": p.new_km,
                   "actions": p.actions, "within_t": p.within_t, "capped_time_sum": p.capped_time_sum,
                   "warnings": list(p.warnings)} for p in r.points]
        worst = next(pt for pt, p in zip(points, r.points) if p is r.worst)
        return stamp({"status": r.status, "message": r.message,
                      "objective": r.objective, "package_ids": list(r.package_ids), "points": points, "worst": worst,
                      "reoptimization": optimization_json(r.reoptimization),
                      "reoptimization_reason": r.reoptimization_reason, "warnings": list(r.warnings)}, body, "stress")

    @router.post("/remove")
    def post_remove(body: RemoveBody) -> dict:
        committed_objective(body.profile)
        scenario = default_scenario()
        try:
            r = remove_action(problem(scenario, backend.limits, body.profile), body.package_ids, body.action_id,
                              evaluator(body.profile, scenario))
        except ValueError as e:
            raise unprocessable(e)
        return stamp({"objective": r.objective, "removed": r.removed, "also_removed": list(r.also_removed),
                      "messages": list(r.messages), "full": package_json(r.full), "remaining": package_json(r.remaining),
                      "loss_within_t": r.loss_within_t, "capped_time_increase": r.capped_time_increase,
                      "note": r.note}, body, "remove")

    @router.post("/co2")
    def post_co2(body: Co2Body) -> dict:
        co2 = backend.co2
        if co2 is None:
            raise HTTPException(409, "CO2 needs a service catalog; not available for this model")
        unknown = set(body.package_ids) - set(co2.candidates)
        if unknown:
            raise HTTPException(422, f"unknown candidate ids {sorted(unknown)}")
        car_trip_km, status, source = body.car_trip_km, "user", "user"
        try:
            if car_trip_km is None:
                scenario = default_scenario()
                evaluate = evaluator(body.profile, scenario)
                p = problem(scenario, backend.limits, body.profile)
                car_trip_km, source = mean_car_distance_km(evaluate(build_request(p, body.package_ids)),
                                                           evaluate(build_request(p, ())), backend.od_car_distance_km)
                status = None if car_trip_km is None else "modelled"
            r = co2_for_package(
                [co2.candidates[c] for c in body.package_ids], co2.catalog, default_scenario(),
                bus_kg_per_vkm=co2.bus_kg_per_vkm if body.bus_kg_per_vkm is None else body.bus_kg_per_vkm,
                car_kg_per_pkm=co2.car_kg_per_pkm if body.car_kg_per_pkm is None else body.car_kg_per_pkm,
                car_trip_km=car_trip_km, avoided_car_trips=body.avoided_car_trips,
            )
        except ValueError as e:
            raise unprocessable(e)
        return stamp(jsonable(r) | {"car_trip_km_source": source, "car_trip_km_status": status,
                                    "factor_statuses": dict(co2.factor_statuses)},
                     body, "co2")

    return router
