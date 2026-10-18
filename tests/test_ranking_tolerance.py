"""Capped sums within 1e-6 min are a tie in every ranking comparison; the next key decides."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from citypilot.decision_engine import (  # noqa: E402
    CAPPED_SUM_TIE_MIN,
    Limits,
    PackageOutcome,
    ResourceResult,
    compare_rank_keys,
    greedy_baseline,
    rank_key,
    sorted_by_compare,
    worse_reason,
)

from decision_testkit import make_evaluation  # noqa: E402


def outcome(ids, last_minutes, bus_hours):
    evaluation = make_evaluation([44, 40, 39, last_minutes])  # within 45: 3 ODs either way
    return PackageOutcome(tuple(ids), evaluation, ResourceResult(bus_hours, bus_hours, 0.0, len(ids), "known", (), ()),
                          True)


def ranked(items, objective):
    key = lambda o: rank_key(o.evaluation, o.resources, objective, o.candidate_ids)  # noqa: E731
    return [o.candidate_ids for o in sorted_by_compare(items, lambda a, b: compare_rank_keys(key(a), key(b), objective))]


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_sums_1e9_apart_rank_by_bus_hours_in_both_input_orders(objective):
    lower_sum = outcome(["A"], 50.0, 21.0)            # lower capped sum, more bus-hours
    cheaper = outcome(["B"], 50.0 + 1e-9, 15.0)       # 1e-9 min higher, fewer bus-hours
    assert abs(lower_sum.capped_time_sum - cheaper.capped_time_sum) < CAPPED_SUM_TIE_MIN
    assert ranked([lower_sum, cheaper], objective) == [("B",), ("A",)]
    assert ranked([cheaper, lower_sum], objective) == [("B",), ("A",)]


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_a_real_difference_still_decides(objective):
    lower_sum = outcome(["A"], 50.0, 21.0)
    higher = outcome(["B"], 50.001, 15.0)  # 1e-3 min: above the tie
    assert ranked([higher, lower_sum], objective) == [("A",), ("B",)]


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_ids_break_a_full_tie(objective):
    a, b = outcome(["B"], 50.0, 15.0), outcome(["A"], 50.0 + 1e-9, 15.0)
    assert ranked([a, b], objective) == ranked([b, a], objective) == [("A",), ("B",)]


@pytest.mark.parametrize("objective", ["count", "sum"])
def test_worse_reason_skips_a_tied_capped_sum(objective):
    rec, alt = outcome(["B"], 50.0 + 1e-9, 15.0), outcome(["A"], 50.0, 21.0)
    assert worse_reason(alt, rec, objective) == "+6 bus-hours"


def test_greedy_treats_a_capped_sum_gain_below_the_tie_as_no_gain():
    table = {(): outcome([], 50.0, 0.0), ("A",): outcome(["A"], 50.0 - 1e-9, 3.0)}
    problem = SimpleNamespace(candidate_ids=("A",), prerequisites={}, exclusions=(), limits=Limits(30.0, 2.0, 3, 100))
    result = greedy_baseline(problem, "sum", lambda ids: table[tuple(sorted(ids))])
    assert [s.outcome for s in result.steps] == ["no_gain"] and result.package.candidate_ids == ()


def test_sorted_by_compare_is_stable():
    items = [("b", 1), ("a", 0), ("c", 1), ("d", 0)]
    assert sorted_by_compare(items, lambda x, y: (x[1] > y[1]) - (x[1] < y[1])) == [("a", 0), ("d", 0), ("b", 1), ("c", 1)]
