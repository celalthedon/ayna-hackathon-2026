"""Evaluation cache: any change to the canonical request is a miss; limits (B_h, K, N_a) are not part of the key."""
import dataclasses
import json

import pytest

from citypilot.api_decision import EvaluationCache
from citypilot.contracts import RoutingPatch, RoutingRequest
from citypilot.decision_engine import Scenario, make_fixture_evaluator

from test_api_decision import FIXTURE, CountingEvaluators, client_for, four_action_backend, optimize

MODEL = {"config_hash": "fixture_4action", "input_hashes": {"fixture": "fixture_4action"}}
DEFAULT = Scenario(1.0, 1.0, 3.0)


@pytest.fixture
def counter():
    return CountingEvaluators(FIXTURE)


def calls_after(counter, tmp_path, first, second, *, B_h=(24, 24), profile=("P", "P")):
    """Evaluator calls made by the second optimisation after the first filled the disk cache."""
    optimize(client_for(first), B_h[0], profile=profile[0])
    before = counter.calls
    r = optimize(client_for(second), B_h[1], profile=profile[1])
    assert r.status_code == 200, r.text
    return counter.calls - before


# --- API: every changed request field misses, limits hit ---

def test_cap_change_misses(tmp_path, counter):
    base = four_action_backend(tmp_path, counter)
    assert calls_after(counter, tmp_path, base, dataclasses.replace(base, cap_min=90.0)) == 12


def test_cap_change_returns_the_new_cap(tmp_path, counter):
    base = four_action_backend(tmp_path, counter)
    optimize(client_for(base), 24)
    cache = EvaluationCache(tmp_path / "cache", MODEL, DEFAULT, lambda: counter.evaluator_for("P", DEFAULT))
    request = RoutingRequest(model_version="fixture", od_set_id="fixture-ods", state="disrupted",
                             closure_id="closure-28may-nizami", profile="P", cap_min=90.0)
    assert cache.evaluate(request).cap_min == 90.0


def test_primary_t_change_misses(tmp_path, counter):
    base = four_action_backend(tmp_path, counter)
    assert calls_after(counter, tmp_path, base, dataclasses.replace(base, primary_t_min=40)) == 12


def test_profile_change_misses(tmp_path, counter):
    base = four_action_backend(tmp_path, counter)
    assert calls_after(counter, tmp_path, base, base, profile=("P", "B")) == 12


def test_patch_change_misses(tmp_path, counter):
    def patches(cut):
        return lambda scenario: lambda ids: tuple(
            RoutingPatch(kind="set_service_headway", target_id=f"R_{i}", headway_min=cut) for i in ids)
    first = dataclasses.replace(four_action_backend(tmp_path, counter), patches_for=patches(8.0))
    second = dataclasses.replace(first, patches_for=patches(7.0))
    assert calls_after(counter, tmp_path, first, second) == 11  # every package except no action


def test_model_identity_change_misses(tmp_path, counter):
    base = four_action_backend(tmp_path, counter)
    assert calls_after(counter, tmp_path, base, dataclasses.replace(base, input_hashes={"fixture": "other"})) == 12


def test_budget_change_hits(tmp_path, counter):
    base = four_action_backend(tmp_path, counter)
    assert calls_after(counter, tmp_path, base, base, B_h=(24, 15)) == 0
    r = optimize(client_for(base), 24, N_a=2, K=0.5)
    assert r.status_code == 200 and counter.calls == 12


# --- cache unit: scenario values, stored key check ---

def request(**overrides):
    return RoutingRequest(**({"model_version": "fixture", "od_set_id": "fixture-ods", "state": "mitigated",
                              "closure_id": "closure-28may-nizami", "profile": "P", "candidate_ids": ("A",)} | overrides))


class Counting:
    def __init__(self):
        self.calls = 0
        self._evaluate = make_fixture_evaluator(FIXTURE)

    def __call__(self, req):
        self.calls += 1
        return self._evaluate(req)


def cache_with(tmp_path, evaluator, scenario=DEFAULT, model=MODEL):
    return EvaluationCache(tmp_path, model, scenario, lambda: evaluator)


@pytest.mark.parametrize("change", [
    {"speed_factor": 0.8},
    {"headway_factor_by_group": {"R2": 1.5}},
    {"thresholds_min": (40, 45)},
    {"candidate_ids": ("A", "C")},
])
def test_request_field_change_misses(tmp_path, change):
    evaluate = Counting()
    cache_with(tmp_path, evaluate).evaluate(request())
    cache_with(tmp_path, evaluate).evaluate(request(**change))
    assert evaluate.calls == 2


def test_scenario_change_misses(tmp_path):
    evaluate = Counting()
    cache_with(tmp_path, evaluate).evaluate(request())
    cache_with(tmp_path, evaluate, Scenario(1.0, 1.25, 3.0)).evaluate(request())
    assert evaluate.calls == 2


def test_same_request_hits_from_disk(tmp_path):
    evaluate = Counting()
    first = cache_with(tmp_path, evaluate).evaluate(request())
    again = cache_with(tmp_path, evaluate).evaluate(request())
    assert evaluate.calls == 1 and again == first
    assert cache_with(tmp_path, evaluate, Scenario(1.0, 1.0, 6.0)).evaluate(request()) == first  # H_hours: resources only
    assert evaluate.calls == 1


def test_file_stores_its_canonical_request(tmp_path):
    cache = cache_with(tmp_path, Counting())
    cache.evaluate(request())
    (path,) = (tmp_path / "evaluations").glob("*.json")
    stored = json.loads(path.read_text())
    assert stored["key"]["request"] == request().to_dict()
    assert stored["key"]["model"] == MODEL
    assert path == cache.path_for(cache.key_for(request()))


@pytest.mark.parametrize("damage", ["foreign key", "corrupt", "wrong cap"])
def test_mismatched_file_is_re_evaluated_and_overwritten(tmp_path, damage):
    evaluate = Counting()
    cache = cache_with(tmp_path, evaluate)
    good = cache.evaluate(request())
    (path,) = (tmp_path / "evaluations").glob("*.json")
    stored = json.loads(path.read_text())
    if damage == "foreign key":  # a different request's result filed under this digest
        stored["key"]["request"]["cap_min"] = 90.0
        path.write_text(json.dumps(stored))
    elif damage == "corrupt":
        path.write_text("{not json")
    else:
        stored["result"]["cap_min"] = 90.0
        path.write_text(json.dumps(stored))
    assert cache_with(tmp_path, evaluate).evaluate(request()) == good
    assert evaluate.calls == 2
    assert json.loads(path.read_text())["key"]["request"]["cap_min"] == 120.0
    assert json.loads(path.read_text())["result"]["cap_min"] == 120.0


# --- every returned result passes result.validate_request(request) ---

OTHER_HASH = "0" * 64
TAMPER = {"model_version": "other-model", "config_hash": OTHER_HASH}


@pytest.mark.parametrize("field", sorted(TAMPER))
def test_tampered_disk_result_is_recomputed(tmp_path, field):
    evaluate = Counting()
    good = cache_with(tmp_path, evaluate).evaluate(request())
    (path,) = (tmp_path / "evaluations").glob("*.json")
    stored = json.loads(path.read_text())
    stored["result"][field] = TAMPER[field]  # correct key, wrong identity inside
    path.write_text(json.dumps(stored))
    again = cache_with(tmp_path, evaluate).evaluate(request())
    assert again == good and getattr(again, field) == getattr(good, field)
    assert evaluate.calls == 2
    assert json.loads(path.read_text())["result"][field] == getattr(good, field)  # overwritten


@pytest.mark.parametrize("field", sorted(TAMPER))
def test_tampered_ram_result_is_recomputed(tmp_path, field):
    evaluate = Counting()
    cache = cache_with(tmp_path, evaluate)
    good = cache.evaluate(request())
    (stem,) = cache.results
    key, held = cache.results[stem]
    cache.results[stem] = (key, dataclasses.replace(held, **{field: TAMPER[field]}))
    (path,) = (tmp_path / "evaluations").glob("*.json")
    path.unlink()  # force a recomputation, not a disk hit
    assert cache.evaluate(request()) == good and evaluate.calls == 2
    assert cache.lookup(request()) == good


def test_ram_hit_is_validated_before_disk(tmp_path):
    evaluate = Counting()
    cache = cache_with(tmp_path, evaluate)
    good = cache.evaluate(request())
    (stem,) = cache.results
    key, held = cache.results[stem]
    cache.results[stem] = (key, dataclasses.replace(held, config_hash=OTHER_HASH))
    assert cache.evaluate(request()) == good and evaluate.calls == 1  # valid disk entry replaces the RAM one


@pytest.mark.parametrize("field", sorted(TAMPER))
def test_fresh_mismatch_raises_and_is_never_cached(tmp_path, field):
    from citypilot.contracts import ContractError

    def wrong(req):
        return dataclasses.replace(make_fixture_evaluator(FIXTURE)(req), **{field: TAMPER[field]})

    cache = cache_with(tmp_path, wrong)
    with pytest.raises(ContractError, match=f"Request/result mismatch: {field}"):
        cache.evaluate(request())
    assert not (tmp_path / "evaluations").exists() or not list((tmp_path / "evaluations").glob("*"))
    assert cache.results == {} and cache.lookup(request()) is None
