"""Ranking policy quantised-1e-6-v1: the capped sum enters rank_key as round(sum / 1e-6), so ranking is a plain,
transitive tuple comparison and float noise below the quantum never decides; the next key does."""
import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot.decision_engine import (  # noqa: E402
    RANKING_POLICY,
    Limits,
    PackageOutcome,
    ResourceResult,
    greedy_baseline,
    quantised_sum,
    rank_key,
    worse_reason,
)

from decision_testkit import make_evaluation  # noqa: E402


def outcome(ids, last_minutes, bus_hours):
    evaluation = make_evaluation([44, 40, 39, last_minutes])  # within 45: 3 ODs either way
    return PackageOutcome(tuple(ids), evaluation, ResourceResult(bus_hours, bus_hours, 0.0, len(ids), "known", (), ()),
                          True)


def ranked(items, objective):
    return [o.candidate_ids for o in sorted(items, key=lambda o: rank_key(o.evaluation, o.resources, objective,
                                                                         o.candidate_ids))]


def test_policy_is_named_and_documented():
    assert RANKING_POLICY == "quantised-1e-6-v1"
    assert "round(capped_time_sum / RANKING_QUANTUM_MIN)" in rank_key.__doc__ and RANKING_POLICY in rank_key.__doc__


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_three_near_sums_give_one_order_in_all_six_permutations(objective):
    # capped sums 100, 100 + 0.75e-6, 100 + 1.5e-6 (ODs of 44 and 56 + d minutes) with decreasing bus costs
    def two_ods(ids, d, bus_hours):
        return PackageOutcome((ids,), make_evaluation([44, 56 + d]),
                              ResourceResult(bus_hours, bus_hours, 0.0, 1, "known", (), ()), True)
    items = [two_ods("A", 0.0, 30.0), two_ods("B", 0.75e-6, 20.0), two_ods("C", 1.5e-6, 10.0)]
    assert [round(o.capped_time_sum - 100, 9) for o in items] == [0.0, 0.00000075, 0.0000015]
    orders = {tuple(ranked(list(p), objective)) for p in itertools.permutations(items)}
    assert len(orders) == 1
    keys = [quantised_sum(o.capped_time_sum) for o in items]
    assert keys == sorted(keys)  # quantisation keeps the order of genuinely different sums


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_sums_1e9_apart_rank_by_bus_hours_in_both_input_orders(objective):
    lower_sum = outcome(["A"], 50.0, 21.0)
    cheaper = outcome(["B"], 50.0 + 1e-9, 15.0)
    assert quantised_sum(lower_sum.capped_time_sum) == quantised_sum(cheaper.capped_time_sum)
    assert ranked([lower_sum, cheaper], objective) == ranked([cheaper, lower_sum], objective) == [("B",), ("A",)]


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_a_real_difference_still_decides(objective):
    assert ranked([outcome(["B"], 50.001, 15.0), outcome(["A"], 50.0, 21.0)], objective) == [("A",), ("B",)]


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_worse_reason_skips_a_tied_capped_sum(objective):
    rec, alt = outcome(["B"], 50.0 + 1e-9, 15.0), outcome(["A"], 50.0, 21.0)
    assert worse_reason(alt, rec, objective) == "+6 bus-hours"


def test_greedy_treats_a_capped_sum_gain_below_the_quantum_as_no_gain():
    table = {(): outcome([], 50.0, 0.0), ("A",): outcome(["A"], 50.0 - 1e-9, 3.0)}
    problem = SimpleNamespace(candidate_ids=("A",), prerequisites={}, exclusions=(), limits=Limits(30.0, 2.0, 3, 100))
    result = greedy_baseline(problem, "sum", lambda ids: table[tuple(sorted(ids))])
    assert [s.outcome for s in result.steps] == ["no_gain"] and result.package.candidate_ids == ()
