"""Cache index: summaries for fast startup; full OD rows stay lazy; every row must be the request it claims."""
import dataclasses
import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot import precompute as pc  # noqa: E402
from citypilot.api_decision import (EvaluationCache, IndexedResult, cache_identity,  # noqa: E402
                                    index_name)
from citypilot.decision_engine import Scenario, build_request  # noqa: E402

from test_api_decision import (CountingEvaluators, FIXTURE, client_for, four_action_backend,  # noqa: E402
                               optimize, strict_json)
from test_optimize import problem_from  # noqa: E402
from test_precompute import Counting  # noqa: E402

SCENARIO = Scenario(1.0, 1.0, 3.0)
IDENTITY = cache_identity("fixture_4action", {"fixture": "fixture_4action"})  # = four_action_backend's


def fill(tmp_path, profile="P"):
    """Precompute every package into tmp_path/cache for the four-action backend's identity; returns the index path."""
    problem = problem_from(FIXTURE, tmp_path / "objectives", n_a=4)
    problem = dataclasses.replace(problem, context=dataclasses.replace(problem.context, profile=profile))
    ctx = pc.Context(m_variants="all", problem=problem, max_package=("A", "C", "D"), identity=IDENTITY,
                     scenario=SCENARIO, make_evaluator=lambda: Counting(), info={})
    entry = pc.run(ctx, tmp_path / "cache")
    assert entry["index"]["rows"] == 12 and entry["index"]["missing"] == 0
    return tmp_path / "cache" / index_name(profile, IDENTITY, SCENARIO), problem


def test_index_rows_equal_the_full_files(tmp_path):
    path, problem = fill(tmp_path)
    cache = EvaluationCache(tmp_path / "cache", IDENTITY, SCENARIO, lambda: None)
    rows = json.loads(path.read_text())["rows"]
    for row in rows:
        request = build_request(problem, tuple(row["candidate_ids"]))
        full = cache.lookup_full(request)
        assert row["config_hash"] == request.config_hash == full.config_hash
        assert {int(t): n for t, n in row["within_counts"].items()} == full.within_counts
        assert row["capped_time_sum"] == full.capped_time_sum
        assert (row["state"], row["profile"], row["cap_min"], row["primary_t_min"]) == (
            full.state, full.profile, full.cap_min, full.primary_t_min)


def test_startup_loads_only_the_index_and_ods_stay_lazy(tmp_path, counter):
    path, problem = fill(tmp_path)
    backend = four_action_backend(tmp_path, counter)
    c = client_for(backend)
    assert strict_json(c.get("/decision/state"))["index"]["P"] == {"file": path.name, "rows": 12, "dropped": 0,
                                                                  "loaded": True}
    for f in (tmp_path / "cache" / "evaluations").glob("*.json"):
        f.rename(f.with_suffix(".hidden"))  # no full file can be read now
    r = strict_json(optimize(c, 24))
    assert r["recommendation"]["candidate_ids"] == ["A", "C", "D"] and counter.calls == 0
    cache = EvaluationCache(tmp_path / "cache", IDENTITY, SCENARIO, lambda: None)
    cache.index = {row["config_hash"]: row for row in json.loads(path.read_text())["rows"]}
    summary = cache.lookup(build_request(problem, ("A",)))
    assert isinstance(summary, IndexedResult)
    for f in (tmp_path / "cache" / "evaluations").glob("*.hidden"):
        f.rename(f.with_suffix(".json"))
    assert len(summary.od_results) == len(FIXTURE["ods"])  # read lazily from the full file


@pytest.mark.parametrize("tamper", [
    lambda row: row.update(config_hash="0" * 64),            # not the hash of its request
    lambda row: row.update(candidate_ids=["B"]),             # claims another package
    lambda row: row.update(cap_min=90.0),                    # identity field differs from the request
    lambda row: row.update(within_counts={"45": 1}),         # thresholds differ
])
def test_a_tampered_row_is_rejected(tmp_path, counter, caplog, tamper):
    path, problem = fill(tmp_path)
    index = json.loads(path.read_text())
    row = next(r for r in index["rows"] if r["candidate_ids"] == ["A", "C"])
    tamper(row)
    path.write_text(json.dumps(index))
    with caplog.at_level(logging.WARNING, logger="citypilot.decision"):
        c = client_for(four_action_backend(tmp_path, counter))
    status = strict_json(c.get("/decision/state"))["index"]["P"]
    assert status["dropped"] == 1 and status["rows"] == 11
    assert any("dropped" in m for m in caplog.messages)
    r = strict_json(optimize(c, 24))  # the dropped package is read from its full file instead
    assert r["recommendation"]["candidate_ids"] == ["A", "C", "D"] and counter.calls == 0


def test_an_index_for_another_model_is_ignored(tmp_path, counter, caplog):
    path, _ = fill(tmp_path)
    index = json.loads(path.read_text())
    index["model"]["input_hashes"] = {"fixture": "other"}
    path.write_text(json.dumps(index))
    with caplog.at_level(logging.WARNING, logger="citypilot.decision"):
        c = client_for(four_action_backend(tmp_path, counter))
    assert strict_json(c.get("/decision/state"))["index"]["P"]["loaded"] is False
    assert any("header does not match" in m for m in caplog.messages)


@pytest.fixture
def counter():
    return CountingEvaluators(FIXTURE)


# --- real cache (local data/cache, M model) ---

REAL_CACHE = ROOT / "data" / "cache"


@pytest.fixture(scope="module")
def real():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit or not list(REAL_CACHE.glob("index_*.json")):
        pytest.skip("Set CITYPILOT_TEST_BUNDLE and build data/cache/index_*.json first")
    from citypilot.routing_engine import load_model
    started = time.perf_counter()
    model = load_model(Path(explicit), ROOT / "supplements" / "m_services_v1" / "config")
    return model, time.perf_counter() - started


def test_real_index_equals_the_full_files_for_all_rows(real):
    """Every row == its stored full result (raw JSON), and row config_hash == hash of the stored request."""
    from citypilot.api_decision import _canonical
    from citypilot.contracts import RoutingRequest
    stored = {}
    for f in (REAL_CACHE / "evaluations").glob("*.json"):
        d = json.loads(f.read_text())
        group = _canonical({"model": d["key"]["model"], "scenario": d["key"]["scenario"]})
        stored[(group, RoutingRequest.from_dict(d["key"]["request"]).config_hash)] = d["result"]
    checked = 0
    for path in sorted(REAL_CACHE.glob("index_*.json")):
        index = json.loads(path.read_text())
        group = _canonical({"model": index["model"], "scenario": index["scenario"]})
        for row in index["rows"]:
            full = stored[(group, row["config_hash"])]
            assert full["config_hash"] == row["config_hash"]
            assert full["within_counts"] == row["within_counts"] and full["capped_time_sum"] == row["capped_time_sum"]
            for name in ("contract_version", "model_version", "od_set_id", "state", "profile", "cap_min",
                         "primary_t_min", "duration_ms"):
                assert full[name] == row[name], (path.name, row["candidate_ids"], name)
            checked += 1
    assert checked == sum(len(json.loads(p.read_text())["rows"]) for p in REAL_CACHE.glob("index_*.json"))


def test_real_startup_then_state_and_optimize_under_2_s(real, tmp_path):
    import hashlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from citypilot.api_decision import build_decision_router
    from citypilot.decision_real import real_backend
    model, load_s = real
    car = tmp_path / "od_car_distances.csv"
    car.write_text("od_id,origin_id,destination_id,profile,car_distance_km,status,snap_m,origin_snap_m,"
                   "destination_snap_m\n", encoding="utf-8")
    started = time.perf_counter()
    backend = real_backend(model, REAL_CACHE, car, hashlib.sha256(car.read_bytes()).hexdigest())
    app = FastAPI()
    app.include_router(build_decision_router(backend))
    client = TestClient(app)
    startup_s = time.perf_counter() - started
    started = time.perf_counter()
    state = client.get("/decision/state").json()
    r = client.post("/decision/optimize", json={"B_h": 30, "K": 2.0, "N_a": 3, "profile": "P"})
    first_s = time.perf_counter() - started
    print(f"model load {load_s:.2f} s, backend+index startup {startup_s:.2f} s, /state+/optimize {first_s:.2f} s")
    assert r.status_code == 200 and r.json()["recommendation"]["candidate_ids"] == ["SVC_M5_A"]
    assert all(state["index"][p]["loaded"] and state["index"][p]["dropped"] == 0 for p in ("P", "B"))
    assert first_s < 2.0
