"""Cross-platform check compares the canonical OD-level result, not only within_counts and the capped sum."""
import sys
from pathlib import Path

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
            "od_count": len(result.od_results)}


def test_identical_result_passes():
    row = v.compare_item(item_for(LISTED), LISTED.config_hash, make_evaluation([44, 40, 39, 50]), LISTED)
    assert row["ok"] and row["ods_sha256_equal"]


def test_swapped_od_minutes_fail_although_counts_and_sum_agree():
    swapped = make_evaluation([40, 44, 39, 50])  # OD1 and OD2 exchange times
    assert swapped.within_counts == LISTED.within_counts and swapped.capped_time_sum == LISTED.capped_time_sum
    row = v.compare_item(item_for(LISTED), LISTED.config_hash, swapped)  # no stored file to fall back on
    assert row["within_counts_equal"] and abs(row["capped_time_sum_delta"]) == 0
    assert not row["ods_sha256_equal"] and not row["ok"]


def test_digest_covers_status_minutes_and_capped_minutes():
    over = make_evaluation([44, 40, 39, 130])  # OD4 over the cap: status and capped_minutes change
    assert v.ods_digest(over) != v.ods_digest(LISTED)
    assert v.ods_digest(make_evaluation([44, 40, 39, 50])) == v.ods_digest(LISTED)


def test_another_config_hash_fails():
    assert not v.compare_item(item_for(LISTED), "0" * 64, LISTED, LISTED)["ok"]
