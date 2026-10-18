"""Decision API router (prefix /decision).

The app mounts it once:  app.include_router(build_decision_router(backend))
All decision maths lives in citypilot.decision_engine; this module validates, caches and serialises.
"""
import hashlib
import json
import logging
import math
import uuid
import weakref
from dataclasses import dataclass, field, fields, is_dataclass
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
    car_distance_coverage,
    co2_for_package,
    enumerate_packages,
    is_feasible,
    load_objective,
    select_objective_dir,
    mean_car_distance_km,
    no_patches,
    objective_path_for,
    optimize,
    rank_key,
    remove_action,
    stress_test,
)

PROFILES = ("P", "B")
OBJECTIVE_NOT_COMMITTED = "objective not committed"
OBJECTIVE_OTHER_MODEL = "objective decided for another model"


@dataclass(frozen=True)
class Co2Inputs:
    candidates: Mapping[str, Candidate]
    catalog: ModelCatalog
    bus_kg_per_vkm: float  # P13 default
    car_kg_per_pkm: float  # P12 default
    factor_statuses: Mapping[str, str]


log = logging.getLogger("citypilot.decision")


@dataclass(frozen=True)
class Finding:
    """A per-profile finding (e.g. from the precompute), valid only for the model and catalog it was computed for."""
    text: str
    model_identity: Mapping  # cache_identity(config_hash, input_hashes) of that model
    catalog_hash: str | None  # decision_real.catalog_hash of that catalog


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
    N_a_max: int  # slider / enumeration maximum; config/limits.yaml N_a_max
    reference_package_ids: tuple[str, ...] | None = None  # the AYNA real response, from the catalog
    stress_grid: StressGrid | None = None
    co2: Co2Inputs | None = None
    od_car_distance_km: Mapping[str, OdCarDistance] | None = None  # OD table car_distance_km
    patches_for: Callable[[Scenario], Callable[[tuple[str, ...]], tuple[RoutingPatch, ...]]] = lambda scenario: no_patches
    requires_bike: frozenset[str] = frozenset()
    findings: Mapping[str, Finding] | None = None  # per profile; shown (not an error) only for this model and catalog
    catalog_hash: str | None = None  # identity of the candidate catalog (decision_real.catalog_hash)

    def __post_init__(self):
        if set(self.model_hashes) != set(PROFILES):
            raise ValueError(f"model_hashes needs one normal/disrupted pair per profile {PROFILES}, got {sorted(self.model_hashes)}")
        for profile, pair in self.model_hashes.items():
            if set(pair) != {"normal", "disrupted"}:
                raise ValueError(f"model_hashes[{profile}] needs normal and disrupted, got {sorted(pair)}")
        if not self.objective_dirs:
            raise ValueError("objective_dirs is empty")
        if isinstance(self.N_a_max, bool) or not isinstance(self.N_a_max, int) or self.N_a_max < 1:
            raise ValueError(f"N_a_max must be an int >= 1, got {self.N_a_max!r}")
        if self.limits.N_a_actions > self.N_a_max:
            raise ValueError(f"default N_a_actions {self.limits.N_a_actions} exceeds N_a_max {self.N_a_max}")


# --- request bodies (out of range -> 422) ---

class OptimizeBody(BaseModel):
    B_h: float = Field(ge=0, le=70, description="bus-hour budget")
    K: float = Field(ge=0, le=3, description="new infrastructure km budget")
    N_a: int = Field(ge=1, description="maximum number of actions; at most the backend's N_a_max")
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



COMPARE_INCOMPLETE = "unavailable: incomplete cache"
INDEX_VERSION = 2  # 2: header and file name carry the catalog identity (catalog_hash, m_variants)
INDEX_IDENTITY_FIELDS = ("contract_version", "model_version", "od_set_id", "state", "profile", "config_hash",
                         "primary_t_min", "cap_min")


@dataclass(frozen=True)
class IndexedResult:
    """Summary of one evaluation from the cache index: everything ranking needs, without the OD rows.
    od_results is read lazily from the full cache file (map, journey inspector, removal detail, CO2)."""
    contract_version: str
    model_version: str
    od_set_id: str
    state: str
    profile: str
    config_hash: str
    within_counts: Mapping[int, int]
    capped_time_sum: float
    primary_t_min: int
    cap_min: float
    duration_ms: float
    warnings: tuple[str, ...]
    load_full: Callable[[], EvaluationResult] = field(compare=False, repr=False)

    @property
    def od_results(self):
        return self.load_full().od_results

    def validate_request(self, request: RoutingRequest, config_hash: str | None = None) -> None:
        """Same identity checks as EvaluationResult.validate_request; raises ValueError on a mismatch.
        config_hash: the request's hash if already computed (it is expensive to recompute)."""
        for name in INDEX_IDENTITY_FIELDS:
            got = config_hash if name == "config_hash" and config_hash is not None else getattr(request, name)
            if getattr(self, name) != got:
                raise ValueError(f"Request/index mismatch: {name}")
        if set(self.within_counts) != set(request.thresholds_min):
            raise ValueError("Request/index thresholds mismatch")


def index_row(result: EvaluationResult, candidate_ids: tuple[str, ...], resources: ResourceResult,
              feasible: bool) -> dict:
    deltas = [s.delta_vehicles for s in resources.per_service]
    return {"config_hash": result.config_hash, "candidate_ids": list(candidate_ids),
            "within_counts": {str(t): n for t, n in result.within_counts.items()},
            "capped_time_sum": result.capped_time_sum, "bus_hours": resources.added_bus_hours,
            "vehicles": None if any(d is None for d in deltas) else sum(deltas),
            "actions": resources.action_count, "feasible": feasible,
            **{name: getattr(result, name) for name in INDEX_IDENTITY_FIELDS if name != "config_hash"},
            "duration_ms": result.duration_ms, "warnings": list(result.warnings)}


def model_hash(model_identity: Mapping, scenario: Scenario, catalog_hash: str | None) -> str:
    """Short hash of model identity, evaluator scenario and catalog identity; names the index (and stress) files,
    so an index built for one catalog variant never has the name another variant looks for."""
    return hashlib.sha256(_canonical({"model": dict(model_identity), "scenario": _evaluator_scenario_key(scenario),
                                      "catalog_hash": catalog_hash}).encode()).hexdigest()[:16]


def index_name(profile: str, model_identity: Mapping, scenario: Scenario, catalog_hash: str | None) -> str:
    """index_<profile>_<model_hash>.json."""
    return f"index_{profile}_{model_hash(model_identity, scenario, catalog_hash)}.json"


_HEX = set("0123456789abcdef")
_NUMBER = (int, float)


def _is_number(v, optional=False) -> bool:
    if v is None:
        return optional
    return isinstance(v, _NUMBER) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v, optional=False) -> bool:
    if v is None:
        return optional
    return isinstance(v, int) and not isinstance(v, bool)


def index_row_problem(row) -> str | None:
    """Why an index row is malformed (missing field or wrong type), or None. Rows are checked before use."""
    if not isinstance(row, dict):
        return "row is not an object"
    required = {"config_hash", "candidate_ids", "within_counts", "capped_time_sum", "bus_hours", "vehicles", "actions",
                "feasible", "duration_ms", "warnings", *INDEX_IDENTITY_FIELDS}
    missing = sorted(required - set(row))
    if missing:
        return f"missing fields {missing}"
    h = row["config_hash"]
    checks = {
        "config_hash": isinstance(h, str) and len(h) == 64 and set(h) <= _HEX,
        "candidate_ids": isinstance(row["candidate_ids"], list) and all(isinstance(i, str) for i in row["candidate_ids"]),
        "within_counts": isinstance(row["within_counts"], dict) and bool(row["within_counts"])
        and all(isinstance(t, str) and t.isdigit() and _is_int(n) and n >= 0 for t, n in row["within_counts"].items()),
        "capped_time_sum": _is_number(row["capped_time_sum"]),
        "bus_hours": _is_number(row["bus_hours"], optional=True),
        "vehicles": _is_int(row["vehicles"], optional=True),
        "actions": _is_int(row["actions"]) and row["actions"] >= 0,
        "feasible": isinstance(row["feasible"], bool),
        "duration_ms": _is_number(row["duration_ms"]),
        "warnings": isinstance(row["warnings"], list) and all(isinstance(w, str) for w in row["warnings"]),
        "primary_t_min": _is_int(row["primary_t_min"]),
        "cap_min": _is_number(row["cap_min"]),
        **{f: isinstance(row[f], str) for f in ("contract_version", "model_version", "od_set_id", "state", "profile")},
    }
    wrong = sorted(f for f, ok in checks.items() if not ok)
    return f"wrong type or value: {wrong}" if wrong else None


def cache_identity(config_hash: str, input_hashes: Mapping[str, str]) -> dict:
    """Model identity in the cache key; the router and the precompute must build it the same way."""
    return {"config_hash": config_hash, "input_hashes": dict(sorted(input_hashes.items()))}


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
        self.index: dict[str, dict] = {}  # request config_hash -> index row (validated by the router)
        self._hashes = weakref.WeakKeyDictionary()  # request -> config_hash; computing it re-validates the request

    def config_hash(self, request: RoutingRequest) -> str:
        try:
            return self._hashes[request]
        except KeyError:
            value = self._hashes[request] = request.config_hash
            return value
        except TypeError:  # unhashable request (e.g. per-group headway factors): no memo
            return request.config_hash

    def key_for(self, request: RoutingRequest) -> str:
        return _canonical({"request": request.to_dict(), "model": self.model_identity, "scenario": self.scenario_key})

    def path_for(self, key: str) -> Path:
        return self.directory / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def lookup(self, request: RoutingRequest) -> EvaluationResult | IndexedResult | None:
        """The valid stored result for this exact request: index summary, then RAM, then disk; never evaluates."""
        config_hash = self.config_hash(request)
        row = self.index.get(config_hash)
        if row is not None:
            summary = self._summary(row, request)
            try:
                summary.validate_request(request, config_hash)
                return summary
            except ValueError as e:
                del self.index[config_hash]
                log.warning("index row %s dropped: %s", config_hash, e)
        return self.lookup_full(request)

    def _summary(self, row: dict, request: RoutingRequest) -> IndexedResult:
        return IndexedResult(
            **{name: row[name] for name in INDEX_IDENTITY_FIELDS},
            within_counts={int(t): n for t, n in row["within_counts"].items()}, capped_time_sum=row["capped_time_sum"],
            duration_ms=row["duration_ms"], warnings=tuple(row["warnings"]), load_full=lambda: self.full(request))

    def full(self, request: RoutingRequest) -> EvaluationResult:
        """The full result with OD rows: cached file, else a fresh evaluation."""
        return self.lookup_full(request) or self._evaluate_fresh(request)

    def lookup_full(self, request: RoutingRequest) -> EvaluationResult | None:
        """The valid stored full result (RAM, then disk), or None; never evaluates."""
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

    def evaluate(self, request: RoutingRequest) -> EvaluationResult | IndexedResult:
        result = self.lookup(request)
        if result is not None:
            return result
        return self._evaluate_fresh(request)

    def _evaluate_fresh(self, request: RoutingRequest) -> EvaluationResult:
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

    model_identity = cache_identity(backend.config_hash, backend.input_hashes)

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

    primed: set[str] = set()
    index_status: dict[str, dict] = {}
    indexed: dict[str, set[tuple[str, ...]]] = {p: set() for p in PROFILES}  # packages with a validated index row

    def widest_problem(profile: str, scenario: Scenario) -> DecisionProblem:
        return problem(scenario, Limits(backend.limits.B_h_bus_hours, backend.limits.K_new_infra_km, backend.N_a_max,
                                        backend.limits.max_exact_packages), profile)  # enumeration uses N_a only

    def load_index(profile: str) -> None:
        """Attach the default-scenario index: header must match; each row must be the request it claims."""
        scenario = default_scenario()
        cache = cache_for(profile, scenario)
        path = Path(backend.cache_dir) / index_name(profile, model_identity, scenario, backend.catalog_hash)
        status = {"file": path.name, "rows": 0, "dropped": 0, "loaded": False}
        index_status[profile] = status
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            header = (data["index_version"], data["profile"], data["model"], data["scenario"], data["catalog_hash"])
            expected = (INDEX_VERSION, profile, json.loads(_canonical(model_identity)), _evaluator_scenario_key(scenario),
                        backend.catalog_hash)
            if json.loads(_canonical(list(header))) != json.loads(_canonical(list(expected))):
                log.warning("index %s ignored: header (model, scenario, catalog) does not match this backend", path.name)
                return
            rows = data["rows"]
            if not isinstance(rows, list):
                raise TypeError("rows is not a list")
        except Exception as e:  # unreadable or malformed file: never crash, never serve it; per-file cache serves
            log.warning("index %s ignored: %s", path.name, e)
            return
        hashes = [r.get("config_hash") for r in rows if isinstance(r, dict) and isinstance(r.get("config_hash"), str)]
        duplicated = {h for h in hashes if hashes.count(h) > 1}
        try:
            widest = widest_problem(profile, scenario)
        except (ValueError, OSError) as e:  # no committed objective / decided for another model
            log.warning("index %s not loaded: %s", path.name, e)
            return
        for row in rows:
            try:
                problem_text = index_row_problem(row)
                if problem_text:
                    raise ValueError(problem_text)
                if row["config_hash"] in duplicated:
                    raise ValueError("duplicate row for this config_hash")
                request = build_request(widest, tuple(row["candidate_ids"]))
                config_hash = cache.config_hash(request)
                if row["config_hash"] != config_hash:
                    raise ValueError("config_hash is not the hash of the request it represents")
                cache._summary(row, request).validate_request(request, config_hash)
            except Exception as e:  # a malformed row is dropped and logged; its package falls back to its full file
                status["dropped"] += 1
                log.warning("index %s row %s dropped: %s", path.name,
                            row.get("candidate_ids") if isinstance(row, dict) else type(row).__name__, e)
                continue
            cache.index[config_hash] = row
            indexed[profile].add(tuple(request.candidate_ids))
        status.update(rows=len(cache.index), loaded=True)
        # the validated index replaces the first-use pass; packages without a row are evaluated on demand
        primed.add(_canonical({"profile": profile, "scenario": _evaluator_scenario_key(scenario)}))

    def evaluator(profile: str, scenario: Scenario):
        """Cached evaluator; on first use it evaluates every valid package with <= N_a_max actions once
        (index summaries when present), so later limit changes only re-filter and re-rank."""
        cache = cache_for(profile, scenario)
        name = _canonical({"profile": profile, "scenario": _evaluator_scenario_key(scenario)})
        if name not in primed:
            widest = widest_problem(profile, scenario)
            packages = list(enumerate_packages(widest))
            if len(packages) <= backend.limits.max_exact_packages:
                for package in packages:
                    cache.evaluate(build_request(widest, package))
            primed.add(name)
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
        if body.N_a > backend.N_a_max:
            raise HTTPException(422, f"N_a {body.N_a} exceeds N_a_max {backend.N_a_max}")
        return Limits(body.B_h, body.K, body.N_a, backend.limits.max_exact_packages)

    def run_optimize(limits: Limits, profile: str) -> OptimizationResult:
        scenario = default_scenario()
        return optimize(problem(scenario, limits, profile), evaluator(profile, scenario))

    def finding(profile: str) -> str | None:
        """The profile's finding if it was computed for this model and catalog; any other finding is ignored."""
        f = (backend.findings or {}).get(profile)
        if f is None:
            return None
        if _canonical(dict(f.model_identity)) != _canonical(model_identity) or f.catalog_hash != backend.catalog_hash:
            log.warning("finding for %s ignored: computed for another model or catalog", profile)
            return None
        return f.text

    def unprocessable(e: Exception) -> HTTPException:
        return HTTPException(422, str(e))

    for p in PROFILES:  # startup: only the index summaries are read; full OD files stay lazy
        load_index(p)

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
            "N_a_max": backend.N_a_max,
            "findings": {p: text for p in PROFILES if (text := finding(p)) is not None},
            "index": {p: dict(v) for p, v in index_status.items()},
            "compare_ayna": dict(compare_status),
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
        return stamp(optimization_json(result) | {"limits": jsonable(limits_from(body)),
                                                  "finding": finding(body.profile)}, body, "optimize")

    compare_store: dict[str, tuple[str, dict]] = {}  # profile -> (fingerprint, result before stamping)
    compare_status: dict[str, str] = {}

    def gate_identity(profile: str) -> dict:
        """The profile's gate exactly as /optimize validates it: missing, invalid or decided for another model
        raises the same 409. Includes the gate file's SHA-256, so an altered gate never matches a stored result."""
        objective = committed_objective(profile)
        path = objective_path_for(objective_dir_for(profile), profile)
        return {"objective": objective, "file": path.name, "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "hashes": dict(backend.model_hashes[profile])}

    def compare_fingerprint(profile: str, gate: dict) -> str:
        """Everything compare_ayna depends on: gate, model, catalog, the index file on disk and the limits."""
        path = Path(backend.cache_dir) / index_name(profile, model_identity, default_scenario(), backend.catalog_hash)
        try:
            st = path.stat()
            index = [path.name, st.st_size, st.st_mtime_ns]
        except OSError:
            index = None
        limits = {f: getattr(backend.limits, f) for f in ("B_h_bus_hours", "K_new_infra_km", "N_a_actions")}
        return _canonical({"gate": gate, "model": dict(model_identity), "catalog_hash": backend.catalog_hash,
                           "index": index, "limits": limits, "N_a_max": backend.N_a_max})

    def compare_packages_indexed(profile: str) -> bool:
        """Every package compare_ayna needs (all up to N_a_max, and the reference) has a validated index row."""
        packages = set(enumerate_packages(widest_problem(profile, default_scenario())))
        packages.add(tuple(sorted(backend.reference_package_ids or ())))
        return packages <= indexed[profile]

    def compute_compare(profile: str) -> dict:
        """AYNA reference vs the optimiser at the reference's own bus-hours, N_a_max actions. Inputs are fixed."""
        objective = committed_objective(profile)
        reference_ids = backend.reference_package_ids
        if not reference_ids:
            raise HTTPException(409, "no AYNA reference package in the catalog")
        scenario = default_scenario()
        try:
            reference_problem = problem(scenario, backend.limits, profile)
            reference_resources = reference_problem.resources(tuple(sorted(reference_ids)))
            if reference_resources.added_bus_hours is None:
                raise ValueError(f"reference package {reference_ids}: bus-hours unknown")
            limits = Limits(reference_resources.added_bus_hours, backend.limits.K_new_infra_km, backend.N_a_max,
                            backend.limits.max_exact_packages)
            result = optimize(problem(scenario, limits, profile), evaluator(profile, scenario))
            ref_eval = evaluator(profile, scenario)(build_request(reference_problem, reference_ids))
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
        return {"reference": reference, "optimizer": optimization_json(result), "limits": jsonable(limits),
                "difference": difference, "verdict": verdict}

    def stored_compare(profile: str) -> dict:
        """The stored result while gate, model, catalog, index and limits are unchanged (checked on every call,
        the gate exactly as /optimize does); otherwise reload the index and recompute. With an index loaded,
        it is computed only from complete index rows, never by routing."""
        gate = gate_identity(profile)  # 409 like /optimize when the gate is missing, invalid or for another model
        fingerprint = compare_fingerprint(profile, gate)
        held = compare_store.get(profile)
        if held is not None and held[0] == fingerprint:
            return held[1]
        if held is not None:
            caches.clear()  # something changed: drop summaries and the first-use pass, then reload the indexes
            primed.clear()
            for p in PROFILES:
                indexed[p].clear()
                load_index(p)
            compare_store.clear()
        if index_status.get(profile, {}).get("loaded") and not compare_packages_indexed(profile):
            compare_status[profile] = COMPARE_INCOMPLETE
            raise HTTPException(409, f"compare_ayna {COMPARE_INCOMPLETE}")
        result = compute_compare(profile)
        compare_store[profile] = (fingerprint, result)
        compare_status[profile] = "ready"
        return result

    @router.post("/compare_ayna")
    def post_compare(body: ProfileBody) -> dict:
        return stamp(dict(stored_compare(body.profile)), body, "compare_ayna")

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
            scenario = default_scenario()
            evaluate = evaluator(body.profile, scenario)
            p = problem(scenario, backend.limits, body.profile)
            package_eval, no_action_eval = evaluate(build_request(p, body.package_ids)), evaluate(build_request(p, ()))
            coverage = car_distance_coverage(package_eval, no_action_eval, backend.od_car_distance_km)
            if car_trip_km is None:
                car_trip_km, source = mean_car_distance_km(package_eval, no_action_eval, backend.od_car_distance_km)
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
                                    "car_distance_coverage": coverage, "factor_statuses": dict(co2.factor_statuses)},
                     body, "co2")

    for p in PROFILES:  # startup: compare_ayna has fixed inputs; once per profile, from a complete index only
        if not index_status.get(p, {}).get("loaded"):
            compare_status[p] = "on request (no index)"
            continue  # without an index it would evaluate every package; it is computed on the first request
        try:
            stored_compare(p)  # never routes: an incomplete index marks it unavailable instead
        except HTTPException as e:  # incomplete cache / objective not committed: reported per request and in /state
            compare_status.setdefault(p, f"unavailable: {e.detail}")
            log.warning("compare_ayna for %s not precomputed: %s", p, e.detail)

    return router
