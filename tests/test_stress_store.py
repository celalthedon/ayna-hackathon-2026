"""Stored /stress of the default recommendation: computed once, served from memory, keyed by what it depends on."""
import dataclasses
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import citypilot.api_decision as api  # noqa: E402
from citypilot.decision_dev import fixture_stress_backend  # noqa: E402
from citypilot.decision_engine import StressGrid  # noqa: E402

from test_api_decision import client_for, strict_json, write_objective  # noqa: E402


@pytest.fixture
def runs(monkeypatch):
    calls = []
    real = api.stress_test
    monkeypatch.setattr(api, "stress_test", lambda setup, ids: calls.append(tuple(ids)) or real(setup, ids))
    return calls


def backend(tmp_path, **changes):
    return dataclasses.replace(fixture_stress_backend(write_objective(tmp_path / "objectives"), tmp_path / "cache"),
                               **changes)


def default_package(c):
    r = strict_json(c.post("/decision/optimize", json={"B_h": 24, "K": 2, "N_a": 3, "profile": "P"}))
    return r["recommendation"]["candidate_ids"]


def stress(c, package):
    return strict_json(c.post("/decision/stress", json={"package_ids": package, "profile": "P"}))


def test_default_recommendation_is_computed_once_stored_and_reloaded(tmp_path, runs):
    b = backend(tmp_path)
    c = client_for(b)
    package = default_package(c)
    first = stress(c, package)
    files = list((tmp_path / "cache").glob("stress_P_*.json"))
    assert len(runs) == 1 and len(files) == 1
    stored = json.loads(files[0].read_text())
    assert stored["key"]["package_id"] == "+".join(sorted(package)) and stored["key"]["grid_hash"]
    started = time.perf_counter()
    second = stress(c, package)
    assert time.perf_counter() - started < 0.1 and len(runs) == 1 and second == first
    reloaded = stress(client_for(b), package)  # new router: served from the file, no recomputation
    assert len(runs) == 1 and {k: v for k, v in reloaded.items() if k != "request_hash"} == {
        k: v for k, v in first.items() if k != "request_hash"}


@pytest.mark.parametrize("change", ["grid", "limits"])
def test_a_changed_grid_or_limits_ignores_the_file(tmp_path, runs, change):
    b = backend(tmp_path)
    c = client_for(b)
    stress(c, default_package(c))
    if change == "grid":
        grid = b.stress_grid
        b2 = dataclasses.replace(b, stress_grid=StressGrid({**grid.speed_levels_kmh, "low": grid.speed_levels_kmh["low"] - 1},
                                                           grid.headway_levels_min))
    else:
        b2 = dataclasses.replace(b, limits=dataclasses.replace(b.limits, B_h_bus_hours=b.limits.B_h_bus_hours + 1))
    c2 = client_for(b2)
    stress(c2, default_package(c2))
    assert len(runs) == 2


def test_another_package_is_computed_live_and_not_written(tmp_path, runs):
    c = client_for(backend(tmp_path))
    package = default_package(c)
    stress(c, package)
    before = [f.read_text() for f in (tmp_path / "cache").glob("stress_P_*.json")]
    other = ["A"] if package != ["A"] else ["C"]
    stress(c, other)
    assert len(runs) == 2
    assert [f.read_text() for f in (tmp_path / "cache").glob("stress_P_*.json")] == before
