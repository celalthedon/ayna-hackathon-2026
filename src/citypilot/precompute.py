"""Precompute every package up to N_a_max into the evaluation cache, so the API only re-filters and re-ranks.

    python -m citypilot.precompute --profile P|B --workers N
        [--dry-run] [--limit N] [--m-variants all|design_only] [--cache-dir PATH]
        [--bundle PATH] [--config PATH]

Bundle and routing config default to CITYPILOT_ARTIFACT_DIR / CITYPILOT_CONFIG_DIR (as the routing API).
Every package up to N_a_max is enumerated regardless of B_h / K (those only filter). Results go to the P0
evaluation cache (<cache-dir>/evaluations/, default data/cache/, git-ignored): cached entries are skipped,
so a re-run resumes. A package error is logged with its id and the run continues.

Writes <cache-dir>/precompute_<profile>_<m-variants>.log.jsonl (one line per package: id, duration_ms,
cache hit/miss/error) and merges this run into <cache-dir>/precompute_manifest.json under
runs["<profile>:<m-variants>"].

Profile B first evaluates the strongest package (the strongest variant of every group). If its B result
equals the disrupted result, no smaller package can change a bike time, so the run is skipped and the
manifest records the finding instead.
"""
import argparse
import json
import multiprocessing
import functools
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping

from citypilot.api_decision import (INDEX_VERSION, EvaluationCache, _canonical, _evaluator_scenario_key, cache_identity,
                                    index_name, index_row)
from citypilot.decision_engine import DecisionProblem, Limits, Scenario, build_request, enumerate_packages, is_feasible

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = ROOT / "data" / "cache"
MANIFEST_NAME = "precompute_manifest.json"
M_VARIANT_CHOICES = ("all", "design_only")
B_NO_EFFECT = "B: no catalog action changes bike travel times"
LIBRARIES = ("numpy", "pandas", "scipy", "shapely", "pyproj", "fastapi", "pyyaml")
SAME_MINUTES_TOL = 1e-9


@dataclass(frozen=True)
class Context:
    """Everything one precompute run needs; built once per process."""
    m_variants: str
    problem: DecisionProblem  # limits.N_a_actions = N_a_max
    max_package: tuple[str, ...]
    identity: Mapping[str, Any]
    scenario: Scenario
    make_evaluator: Callable[[], Callable]
    info: Mapping[str, Any]  # model identity for the manifest
    catalog_hash: str | None = None  # decision_real.catalog_hash of the (variant-filtered) candidate catalog
    default_limits: Limits | None = None  # config/limits.yaml defaults; the index's feasible flag

    @property
    def profile(self) -> str:
        return self.problem.context.profile


def build_context(bundle: Path, config: Path, profile: str, m_variants: str) -> Context:
    """Real catalog on the loaded model (R2/R14 cuts + M services), limits from config/limits.yaml."""
    from citypilot.decision_engine import load_scenario
    from citypilot.decision_real import (LIMITS_PATH, catalog_hash, design_only, load_n_a_max, real_catalog,
                                         real_evaluator, real_input_hashes, real_limits, real_problem,
                                         strongest_package)
    from citypilot.routing_engine import get_catalog, load_model

    if m_variants not in M_VARIANT_CHOICES:
        raise ValueError(f"m_variants must be one of {M_VARIANT_CHOICES}, got {m_variants!r}")
    model = load_model(bundle, config)
    catalog = get_catalog(model)
    candidates, exclusions = real_catalog(catalog)
    if m_variants == "design_only":
        candidates, exclusions = design_only(candidates, exclusions)
    base = real_limits()
    limits = Limits(base.B_h_bus_hours, base.K_new_infra_km, load_n_a_max(), base.max_exact_packages)
    H_hours = load_scenario(LIMITS_PATH, 1.0, 1.0).H_hours
    hashes = real_input_hashes(model)
    return Context(
        m_variants=m_variants,
        problem=real_problem(model, profile, limits, candidates, exclusions, H_hours),
        max_package=strongest_package(candidates, exclusions, catalog),
        identity=cache_identity(catalog.model_version, hashes),
        scenario=Scenario(1.0, 1.0, H_hours),
        make_evaluator=lambda: real_evaluator(model),
        info={"model_version": catalog.model_version, **hashes},
        catalog_hash=catalog_hash(candidates, exclusions),
        default_limits=base,
    )


def plan(problem: DecisionProblem) -> list[tuple[str, ...]]:
    """Every package up to N_a_max in deterministic order: fewer actions first, then ids."""
    return sorted(enumerate_packages(problem), key=lambda ids: (len(ids), ids))


def counts_by_n_a(packages: list[tuple[str, ...]], n_a_max: int) -> dict[int, int]:
    return {k: sum(1 for ids in packages if len(ids) <= k) for k in range(1, n_a_max + 1)}


def package_id(ids: tuple[str, ...]) -> str:
    return "+".join(ids) or "NO_ACTION"


START_METHOD = "spawn"  # the only start method on Windows; workers rebuild their context from a picklable factory


def _rss_kb() -> int:
    """Current RSS in KiB (psutil; works on Windows and Linux). Windows also reports its peak working set."""
    import psutil

    info = psutil.Process().memory_info()
    return max(info.rss, getattr(info, "peak_wset", 0)) // 1024


def evaluate_chunk(ctx: Context, packages: list[tuple[str, ...]], cache_dir: Path, log_path: Path | None,
                   worker: int = 0) -> tuple[list[dict], int]:
    """Look up or evaluate each package; one log line per package; errors are recorded, never raised."""
    cache = EvaluationCache(cache_dir, dict(ctx.identity), ctx.scenario, ctx.make_evaluator)
    records = []
    peak = _rss_kb()
    log = open(log_path, "a", encoding="utf-8") if log_path else None
    try:
        for ids in packages:
            started = time.perf_counter()
            record = {"id": package_id(ids), "worker": worker}
            try:
                request = build_request(ctx.problem, ids)
                result = cache.lookup(request)
                record["cache"] = "hit" if result is not None else "miss"
                if result is None:
                    result = cache.evaluate(request)
                record["routing_duration_ms"] = result.duration_ms
            except Exception as e:  # noqa: BLE001 - one bad package must not stop the run
                record["cache"] = "error"
                record["error"] = f"{type(e).__name__}: {e}"
            record["duration_ms"] = (time.perf_counter() - started) * 1000
            peak = max(peak, _rss_kb())  # sampled after every package
            records.append(record)
            if log:
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
    finally:
        if log:
            log.close()
    return records, peak


def same_travel_times(a, b) -> bool:
    left = {o.od_id: o for o in a.od_results}
    right = {o.od_id: o for o in b.od_results}
    if left.keys() != right.keys():
        return False
    for od_id, x in left.items():
        y = right[od_id]
        if x.status != y.status or (x.minutes is None) != (y.minutes is None):
            return False
        if x.minutes is not None and abs(x.minutes - y.minutes) > SAME_MINUTES_TOL:
            return False
    return True


def max_package_check(ctx: Context, cache_dir: Path) -> dict:
    """Strongest package vs disrupted (no action); both through the cache."""
    cache = EvaluationCache(cache_dir, dict(ctx.identity), ctx.scenario, ctx.make_evaluator)
    disrupted = cache.evaluate(build_request(ctx.problem, ()))
    strongest = cache.evaluate(build_request(ctx.problem, ctx.max_package))
    return {"package": list(ctx.max_package), "equals_disrupted": same_travel_times(strongest, disrupted),
            "capped_time_sum": {"max_package": strongest.capped_time_sum, "disrupted": disrupted.capped_time_sum}}


_WORKER: Context | None = None  # one per spawned worker process, built once by _init_worker


def _init_worker(context_factory) -> None:
    global _WORKER
    _WORKER = context_factory()


def _worker_chunk(packages, cache_dir, log_path, worker):
    return evaluate_chunk(_WORKER, packages, cache_dir, log_path, worker)


def _run_workers(ctx: Context, packages, cache_dir: Path, log_path: Path, workers: int, context_factory=None):
    if workers == 1 or len(packages) <= 1:
        records, rss = evaluate_chunk(ctx, packages, cache_dir, log_path)
        return records, [rss]
    if context_factory is None:
        raise ValueError("workers > 1 needs a picklable context_factory (spawned workers rebuild the context)")
    chunks = [packages[i::workers] for i in range(workers)]
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context(START_METHOD),
                             initializer=_init_worker, initargs=(context_factory,)) as pool:
        done = [pool.submit(_worker_chunk, chunk, cache_dir, log_path, i) for i, chunk in enumerate(chunks)]
        results = [f.result() for f in done]
    return [r for records, _ in results for r in records], [rss for _, rss in results]


def git_commit() -> str | None:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return head + ("-dirty" if dirty else "")


def library_versions() -> dict[str, str | None]:
    versions = {"python": sys.version.split()[0]}
    for name in LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def write_index(ctx: Context, cache_dir: Path) -> dict:
    """index_<profile>_<model_hash>.json: one summary row per cached package, from validated full files only
    (never evaluates). The API loads only this at startup."""
    cache_dir = Path(cache_dir)
    cache = EvaluationCache(cache_dir, dict(ctx.identity), ctx.scenario, ctx.make_evaluator)
    limits = ctx.default_limits or ctx.problem.limits
    rows, missing, invalid = [], 0, 0
    for ids in plan(ctx.problem):
        request = build_request(ctx.problem, ids)
        result = cache.lookup_full(request)
        if result is None:
            if cache.path_for(cache.key_for(request)).exists():
                invalid += 1
            else:
                missing += 1
            continue
        resources = ctx.problem.resources(ids)
        rows.append(index_row(result, ids, resources, is_feasible(resources, limits)))
    path = cache_dir / index_name(ctx.profile, ctx.identity, ctx.scenario)
    index = {"index_version": INDEX_VERSION, "profile": ctx.profile, "model": json.loads(_canonical(dict(ctx.identity))),
             "scenario": _evaluator_scenario_key(ctx.scenario),
             "feasible_limits": {f: getattr(limits, f) for f in ("B_h_bus_hours", "K_new_infra_km", "N_a_actions")},
             "created": datetime.now(timezone.utc).isoformat(), "rows": rows}
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, allow_nan=False))
    tmp.replace(path)
    return {"file": path.name, "rows": len(rows), "missing": missing, "invalid": invalid}


def run(ctx: Context, cache_dir: Path, workers: int = 1, limit: int | None = None, context_factory=None) -> dict:
    """Precompute and merge this run into the manifest; returns the run entry. workers > 1 spawns processes
    that each build their context with context_factory() (picklable, e.g. functools.partial(build_context, ...))."""
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    packages = plan(ctx.problem)
    selected = packages[:limit] if limit else packages
    check, finding = None, None
    if ctx.profile == "B":
        check = max_package_check(ctx, cache_dir)
        if check["equals_disrupted"]:
            selected, finding = [], B_NO_EFFECT
    log_path = cache_dir / f"precompute_{ctx.profile}_{ctx.m_variants}.log.jsonl"
    records, rss = (_run_workers(ctx, selected, cache_dir, log_path, workers, context_factory) if selected
                    else ([], [_rss_kb()]))
    routing_ms = [r["routing_duration_ms"] for r in records if r["cache"] == "miss"]
    failed = [{"id": r["id"], "error": r["error"]} for r in records if r["cache"] == "error"]
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        **dict(ctx.info),
        "identity": json.loads(json.dumps(dict(ctx.identity))),
        "catalog_hash": ctx.catalog_hash,
        "libraries": library_versions(),
        "profile": ctx.profile,
        "m_variants": ctx.m_variants,
        "N_a_max": ctx.problem.limits.N_a_actions,
        "counts_by_N_a": counts_by_n_a(packages, ctx.problem.limits.N_a_actions),
        "limit": limit,
        "counts": {"enumerated": len(packages), "expected": len(selected),
                   "evaluated": len(routing_ms), "cached": sum(r["cache"] == "hit" for r in records),
                   "failed": len(failed)},
        "failed_ids": failed,
        "workers": workers,
        "peak_rss_kb_per_worker": rss,
        "wall_s": time.perf_counter() - started,
        "duration_ms": {"mean": statistics.fmean(routing_ms) if routing_ms else None,
                        "max": max(routing_ms) if routing_ms else None},
        "max_package_check": check,
        "finding": finding,
        "log": log_path.name,
        "index": write_index(ctx, cache_dir),
    }
    manifest_path = cache_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"runs": {}}
    manifest["runs"][f"{ctx.profile}:{ctx.m_variants}"] = entry
    tmp = manifest_path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))
    tmp.replace(manifest_path)
    return entry


def findings_from_manifest(path: Path, model_identity: Mapping, catalog_hash: str | None) -> dict:
    """Per-profile Findings for DecisionBackend.findings, only from runs computed for this model and catalog."""
    from citypilot.api_decision import Finding

    if not Path(path).exists():
        return {}
    wanted = _canonical(dict(model_identity))
    out = {}
    for r in json.loads(Path(path).read_text())["runs"].values():
        if not r.get("finding"):
            continue
        if _canonical(r.get("identity") or {}) != wanted or r.get("catalog_hash") != catalog_hash:
            continue  # stale: another model or catalog variant
        out[r["profile"]] = Finding(r["finding"], r["identity"], r["catalog_hash"])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True, choices=("P", "B"))
    parser.add_argument("--workers", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true", help="enumerate only and print counts per N_a")
    parser.add_argument("--limit", type=int, help="evaluate only the first N packages (pilot)")
    parser.add_argument("--index-only", action="store_true", help="only (re)build the index from the cache")
    parser.add_argument("--m-variants", choices=M_VARIANT_CHOICES, default="all")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--bundle", type=Path, default=os.environ.get("CITYPILOT_ARTIFACT_DIR"))
    parser.add_argument("--config", type=Path, default=os.environ.get("CITYPILOT_CONFIG_DIR"))
    args = parser.parse_args(argv)
    if args.bundle is None or args.config is None:
        parser.error("--bundle and --config (or CITYPILOT_ARTIFACT_DIR / CITYPILOT_CONFIG_DIR) are required")
    ctx = build_context(args.bundle, args.config, args.profile, args.m_variants)
    if args.dry_run:
        packages = plan(ctx.problem)
        print(json.dumps({"profile": ctx.profile, "m_variants": ctx.m_variants,
                          "N_a_max": ctx.problem.limits.N_a_actions,
                          "counts_by_N_a": counts_by_n_a(packages, ctx.problem.limits.N_a_actions),
                          "max_package": list(ctx.max_package)}, indent=2))
        return 0
    if args.index_only:
        print(json.dumps(write_index(ctx, args.cache_dir), indent=2))
        return 0
    entry = run(ctx, args.cache_dir, args.workers, args.limit,
                context_factory=functools.partial(build_context, args.bundle, args.config, args.profile, args.m_variants))
    print(json.dumps({k: entry[k] for k in ("profile", "m_variants", "counts", "wall_s", "duration_ms",
                                             "peak_rss_kb_per_worker", "finding", "index")}, indent=2))
    return 1 if entry["failed_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
