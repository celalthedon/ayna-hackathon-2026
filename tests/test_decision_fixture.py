"""Fixture evaluator and rank_key tests. Expected values were computed by hand."""
from pathlib import Path

import pytest

from citypilot.decision_engine import (
    CONTRACT_VERSION,
    EvaluationResult,
    ResourceResult,
    load_fixture,
    make_fixture_evaluator,
    rank_key,
)

from decision_testkit import make_request  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "decision" / "fixture_4action.json"
FIXTURE = load_fixture(FIXTURE_PATH)
EVALUATE = make_fixture_evaluator(FIXTURE)


def request(ids):
    return make_request(ids)


def fixture_resources(ids):
    actions = FIXTURE["actions"]
    bus_hours = sum(actions[i]["bus_hours"] for i in ids)
    km = sum(actions[i]["new_infra_km"] for i in ids)
    return ResourceResult(bus_hours, bus_hours, km, len(ids), "known", (), ())


@pytest.mark.parametrize("package, n40, n45, n50, capped", [
    ("", 0, 0, 2, 507),
    ("A", 1, 2, 4, 467),
    ("B", 2, 4, 6, 437),
    ("C", 1, 3, 5, 398),
    ("D", 0, 0, 2, 507),
    ("AC", 2, 5, 7, 358),
    ("AD", 1, 2, 4, 467),
    ("BD", 2, 4, 6, 437),
    ("CD", 1, 5, 5, 390),
    ("ACD", 2, 7, 7, 350),
])
def test_evaluator_counts(package, n40, n45, n50, capped):
    r = EVALUATE(request(package))
    assert r.within_counts == {40: n40, 45: n45, 50: n50}
    assert r.capped_time_sum == capped


def test_evaluator_per_od_minutes_acd():
    r = EVALUATE(request("ACD"))
    assert [od.minutes for od in r.od_results] == [40, 42, 55, 41, 39, 44, 44, 45]
    assert all(od.status == "reachable" for od in r.od_results)


def test_evaluator_no_path_is_cap():
    od5 = EVALUATE(request("B")).od_results[4]
    assert (od5.od_id, od5.minutes, od5.capped_minutes, od5.status) == ("OD5", None, 120, "no_path")


def test_evaluator_unknown_action():
    with pytest.raises(ValueError):
        EVALUATE(request("AX"))


def test_evaluator_is_deterministic():
    assert EVALUATE(request("CA")) == EVALUATE(request("AC"))


def test_unconstrained_best_recorded():
    best = FIXTURE["expected_search"]["unconstrained_best"]
    assert EVALUATE(request(best["package"])).within_counts[45] == 8
    assert fixture_resources(best["package"]).added_bus_hours == 30


FEASIBLE = ["", "A", "B", "C", "D", "AC", "AD", "BD", "CD", "ACD"]


def test_ranking_of_feasible_packages():
    ranked = sorted(FEASIBLE, key=lambda p: rank_key(EVALUATE(request(p)), fixture_resources(p), objective="count", candidate_ids=p))
    assert ranked == ["ACD", "AC", "CD", "B", "BD", "C", "A", "AD", "", "D"]
    assert list(ranked[0]) == FIXTURE["expected_search"]["exact"]["package"]


def test_capped_sum_beats_bus_hours():
    ac = rank_key(EVALUATE(request("AC")), fixture_resources("AC"), objective="count", candidate_ids="AC")
    cd = rank_key(EVALUATE(request("CD")), fixture_resources("CD"), objective="count", candidate_ids="CD")
    assert fixture_resources("CD").added_bus_hours < fixture_resources("AC").added_bus_hours
    assert ac < cd


def test_km_breaks_tie():
    assert rank_key(EVALUATE(request("B")), fixture_resources("B"), objective="count", candidate_ids="B") < rank_key(EVALUATE(request("BD")), fixture_resources("BD"), objective="count", candidate_ids="BD")


def synthetic_result(ids):
    return EvaluationResult(CONTRACT_VERSION, "fixture", "fixture-ods", "mitigated", "P", "synthetic", 120, 0.0,
                            (), {45: 5}, 300, 45)


def test_rank_fewer_bus_hours_wins():
    cheap = rank_key(synthetic_result("X"), ResourceResult(6, 6, 0, 1, "known", (), ()), objective="count", candidate_ids="X")
    costly = rank_key(synthetic_result("Y"), ResourceResult(9, 9, 0, 1, "known", (), ()), objective="count", candidate_ids="Y")
    assert cheap < costly


def test_rank_fewer_actions_wins():
    one = rank_key(synthetic_result("Z"), ResourceResult(6, 6, 0.5, 1, "known", (), ()), objective="count", candidate_ids="Z")
    two = rank_key(synthetic_result("XY"), ResourceResult(6, 6, 0.5, 2, "known", (), ()), objective="count", candidate_ids="XY")
    assert one < two


def test_rank_unknown_bus_hours_fails():
    with pytest.raises(ValueError):
        rank_key(synthetic_result("X"), ResourceResult(None, 3, 0, 1, "unknown", (), ()), objective="count", candidate_ids="X")
