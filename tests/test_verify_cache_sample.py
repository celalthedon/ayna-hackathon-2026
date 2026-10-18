"""Cross-platform acceptance rule: exact identity/within_counts/OD ids/statuses; 1e-6 min on minutes and sums;
the exact OD hash is reported, not required."""
import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import verify_cache_sample as v  # noqa: E402

from decision_testkit import make_evaluation  # noqa: E402

LISTED = make_evaluation([44, 40, 39, 50])


def item_for(result):
    return {"profile": "P", "candidate_ids": ["A"], "config_hash": result.config_hash,
            "within_counts": {str(t): n for t, n in result.within_counts.items()},
            "capped_time_sum": result.capped_time_sum, "ods_sha256": v.ods_digest(result),
            "od_count": len(result.od_results), "ods": v.ods_rows(result)}


def test_identical_result_passes_with_exact_hash():
    row = v.compare_item(item_for(LISTED), LISTED.config_hash, make_evaluation([44, 40, 39, 50]))
    assert row["ok"] and row["exact_hash_equal"]


def test_float_noise_within_tolerance_passes_but_exact_hash_differs():
    noisy = make_evaluation([44 + 1.56e-11, 40, 39, 50 - 6.7e-10])  # the Windows magnitudes
    row = v.compare_item(item_for(LISTED), LISTED.config_hash, noisy)
    assert row["ok"] and not row["exact_hash_equal"]


def test_swapped_od_minutes_fail_although_counts_and_sum_agree():
    swapped = make_evaluation([40, 44, 39, 50])
    assert swapped.within_counts == LISTED.within_counts and swapped.capped_time_sum == LISTED.capped_time_sum
    row = v.compare_item(item_for(LISTED), LISTED.config_hash, swapped)
    assert row["within_counts_equal"] and row["max_abs_minutes_delta"] == 4 and not row["ok"]


def test_a_status_difference_fails():
    row = v.compare_item(item_for(LISTED), LISTED.config_hash, make_evaluation([44, 40, None, 50]))
    assert row["status_differences"] == 1 and not row["ok"]


def test_other_od_ids_or_config_hash_fail():
    other = make_evaluation([44, 40, 39, 50, 60])
    assert not v.compare_item(item_for(LISTED), LISTED.config_hash, other)["ok"]
    assert not v.compare_item(item_for(LISTED), "0" * 64, LISTED)["ok"]


def test_a_version_1_list_fails_loudly():
    item = item_for(LISTED)
    del item["ods"]
    with pytest.raises(ValueError, match="version-2"):
        v.compare_item(item, LISTED.config_hash, LISTED)
