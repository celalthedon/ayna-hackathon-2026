"""Precompute: deterministic plan, resume from the P0 cache, errors do not stop the run, manifest, B check."""
import dataclasses
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot import precompute as pc  # noqa: E402
from citypilot.decision_engine import Candidate, Scenario, load_limits, make_fixture_evaluator  # noqa: E402
from citypilot.decision_real import LIMITS_PATH, design_only, load_n_a_max, strongest_package  # noqa: E402

from test_optimize import FIXTURE, problem_from  # noqa: E402

MANIFEST_FIELDS = {"identity", "catalog_hash", "timestamp", "git_commit", "model_version", "bundle_hash", "od_hash", "libraries", "profile",
                   "m_variants", "N_a_max", "counts_by_N_a", "limit", "counts", "failed_ids", "workers",
                   "peak_rss_kb_per_worker", "wall_s", "duration_ms", "max_package_check", "finding", "log"}


class Counting:
    """Fixture evaluator that counts calls and can fail for chosen packages or ignore every action."""
    def __init__(self, fail=(), no_effect=False):
        self.calls, self.fail, self.no_effect = 0, set(fail), no_effect
        self._evaluate = make_fixture_evaluator(FIXTURE)

    def __call__(self, request):
        self.calls += 1
        if "+".join(request.candidate_ids) in self.fail:
            raise RuntimeError("routing failed")
        result = self._evaluate(dataclasses.replace(request, candidate_ids=()) if self.no_effect else request)
        return dataclasses.replace(result, state=request.state, config_hash=request.config_hash)


def context(tmp_path, evaluator, profile="P"):
    problem = problem_from(FIXTURE, tmp_path / "objectives", n_a=4)
    problem = dataclasses.replace(problem, context=dataclasses.replace(problem.context, profile=profile))
    return pc.Context(m_variants="all", problem=problem, max_package=("A", "C", "D"),
                      identity={"config_hash": "fixture", "input_hashes": {"fixture": "4action"}},
                      scenario=Scenario(1.0, 1.0, 3.0), make_evaluator=lambda: evaluator,
                      info={"model_version": "fixture", "bundle_hash": "b", "od_hash": "o"})


def manifest(cache_dir):
    return json.loads((cache_dir / pc.MANIFEST_NAME).read_text())


# --- plan ---

def test_plan_is_deterministic_and_complete(tmp_path):
    packages = pc.plan(context(tmp_path, Counting()).problem)
    assert len(packages) == 12 and packages[0] == () and packages == sorted(packages, key=lambda p: (len(p), p))
    assert pc.counts_by_n_a(packages, 4) == {1: 5, 2: 10, 3: 12, 4: 12}


# --- resume, limit, errors ---

def test_limit_then_resume_skips_cached_entries(tmp_path):
    evaluate, cache = Counting(), tmp_path / "cache"
    first = pc.run(context(tmp_path, evaluate), cache, limit=5)
    assert first["counts"] == {"enumerated": 12, "expected": 5, "evaluated": 5, "cached": 0, "failed": 0}
    second = pc.run(context(tmp_path, evaluate), cache)
    assert second["counts"] == {"enumerated": 12, "expected": 12, "evaluated": 7, "cached": 5, "failed": 0}
    assert evaluate.calls == 12
    third = pc.run(context(tmp_path, evaluate), cache)
    assert third["counts"]["cached"] == 12 and evaluate.calls == 12
    log = [json.loads(line) for line in (cache / third["log"]).read_text().splitlines()]
    assert len(log) == 5 + 12 + 12 and {"id", "duration_ms", "cache"} <= set(log[0])


def test_an_error_does_not_stop_the_run(tmp_path):
    evaluate, cache = Counting(fail={"A+C"}), tmp_path / "cache"
    entry = pc.run(context(tmp_path, evaluate), cache)
    assert entry["counts"] == {"enumerated": 12, "expected": 12, "evaluated": 11, "cached": 0, "failed": 1}
    assert entry["failed_ids"] == [{"id": "A+C", "error": "RuntimeError: routing failed"}]
    retry = pc.run(context(tmp_path, Counting()), cache)  # the failed package is not cached; a re-run retries it
    assert retry["counts"]["evaluated"] == 1 and retry["counts"]["failed"] == 0


def test_manifest_fields(tmp_path):
    cache = tmp_path / "cache"
    pc.run(context(tmp_path, Counting()), cache)
    pc.run(context(tmp_path, Counting(), profile="B"), cache)
    runs = manifest(cache)["runs"]
    assert set(runs) == {"P:all", "B:all"}
    for entry in runs.values():
        assert MANIFEST_FIELDS <= set(entry)
        assert set(entry["libraries"]) >= {"python", "numpy", "pandas", "scipy", "shapely", "pyproj"}
        assert entry["duration_ms"]["mean"] is not None and len(entry["peak_rss_kb_per_worker"]) == 1


def spawned_context(root, profile="P"):
    """Module-level, so functools.partial(spawned_context, ...) pickles into a spawned worker."""
    return context(Path(root), Counting(), profile)


def test_workers_are_spawned_and_share_the_cache(tmp_path, monkeypatch):
    import functools
    import multiprocessing
    methods = []
    real = multiprocessing.get_context
    monkeypatch.setattr(multiprocessing, "get_context", lambda method=None: methods.append(method) or real(method))
    cache = tmp_path / "cache"
    factory = functools.partial(spawned_context, str(tmp_path))
    entry = pc.run(context(tmp_path, Counting()), cache, workers=2, context_factory=factory)
    assert methods == ["spawn"]
    assert entry["counts"]["evaluated"] == 12 and len(entry["peak_rss_kb_per_worker"]) == 2
    assert all(kb > 0 for kb in entry["peak_rss_kb_per_worker"])
    assert pc.run(context(tmp_path, Counting()), cache)["counts"]["cached"] == 12


def test_workers_need_a_picklable_factory(tmp_path):
    with pytest.raises(ValueError, match="context_factory"):
        pc.run(context(tmp_path, Counting()), tmp_path / "cache", workers=2)


def test_precompute_has_no_unix_only_code():
    import ast
    source = (ROOT / "src" / "citypilot" / "precompute.py").read_text()
    imported = {a.name.split(".")[0] for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
    assert "resource" not in imported and "fork" not in source and pc.START_METHOD == "spawn"


# --- profile B: strongest package check ---

def test_b_skips_when_the_strongest_package_changes_nothing(tmp_path):
    evaluate, cache = Counting(no_effect=True), tmp_path / "cache"
    entry = pc.run(context(tmp_path, evaluate, profile="B"), cache)
    assert entry["max_package_check"]["equals_disrupted"] is True and entry["finding"] == pc.B_NO_EFFECT
    assert entry["counts"]["expected"] == 0 and evaluate.calls == 2  # disrupted + strongest only
    ctx = context(tmp_path, evaluate, profile="B")
    (f,) = pc.findings_from_manifest(cache / pc.MANIFEST_NAME, ctx.identity, ctx.catalog_hash).values()
    assert f.text == pc.B_NO_EFFECT and dict(f.model_identity) == ctx.identity
    assert pc.findings_from_manifest(cache / pc.MANIFEST_NAME, {"config_hash": "other", "input_hashes": {}}, None) == {}
    assert pc.findings_from_manifest(cache / pc.MANIFEST_NAME, ctx.identity, "design_only-catalog") == {}


def test_b_falls_back_to_a_full_run_when_the_strongest_package_differs(tmp_path):
    evaluate, cache = Counting(), tmp_path / "cache"
    entry = pc.run(context(tmp_path, evaluate, profile="B"), cache)
    assert entry["max_package_check"]["equals_disrupted"] is False and entry["finding"] is None
    assert entry["counts"]["expected"] == 12 and entry["counts"]["evaluated"] + entry["counts"]["cached"] == 12
    assert evaluate.calls == 12  # the two check evaluations are reused from the cache


def test_p_has_no_strongest_package_check(tmp_path):
    assert pc.run(context(tmp_path, Counting(no_effect=True)), tmp_path / "cache")["max_package_check"] is None


# --- catalog helpers ---

def test_strongest_package_and_design_only():
    candidates = {"R2_CUT25": Candidate("R2_CUT25", "headway_cut", "SG_R2", 0.25),
                  "R2_CUT50": Candidate("R2_CUT50", "headway_cut", "SG_R2", 0.5),
                  "SVC_M1_A": Candidate("SVC_M1_A", "activate_service", "SVC_M1_A"),
                  "SVC_M1_B": Candidate("SVC_M1_B", "activate_service", "SVC_M1_B")}
    exclusions = (("R2_CUT25", "R2_CUT50"), ("SVC_M1_A", "SVC_M1_B"))
    catalog = SimpleNamespace(service_groups={}, prebuilt_services={"SVC_M1_A": SimpleNamespace(base_headway_min=6.0),
                                                                     "SVC_M1_B": SimpleNamespace(base_headway_min=9.0)})
    assert strongest_package(candidates, exclusions, catalog) == ("R2_CUT50", "SVC_M1_A")
    kept, groups = design_only(candidates, exclusions)
    assert sorted(kept) == ["R2_CUT25", "R2_CUT50", "SVC_M1_A"] and groups == (("R2_CUT25", "R2_CUT50"),)


def test_limits_config():
    assert load_n_a_max() == 5
    assert load_limits(LIMITS_PATH).max_exact_packages == 3000


# --- real catalog counts ---

@pytest.fixture(scope="module")
def bundle():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit:
        pytest.skip("Set CITYPILOT_TEST_BUNDLE to the explicit immutable C4 bundle")
    return Path(explicit)


@pytest.mark.parametrize("variants, counts", [("all", {3: 379, 4: 939, 5: 1611}),
                                              ("design_only", {3: 114, 4: 199, 5: 260})])
def test_real_counts_dry_run(bundle, capsys, variants, counts):
    config = ROOT / "supplements" / "m_services_v1" / "config"
    assert pc.main(["--profile", "P", "--workers", "1", "--dry-run", "--m-variants", variants,
                    "--bundle", str(bundle), "--config", str(config)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {int(k): v for k, v in out["counts_by_N_a"].items() if int(k) >= 3} == counts
    assert out["max_package"] == ["R14_CUT50", "R2_CUT50", "SVC_M1_A", "SVC_M2_A", "SVC_M3_A", "SVC_M5_A", "SVC_M6_A"]
