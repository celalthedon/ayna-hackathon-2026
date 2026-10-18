"""demo_smoke.verify: exact expectations; empty alternatives and wrong coverage fail; the self-test catches tampering."""
import copy
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import demo_smoke as smoke  # noqa: E402

RESULTS = ROOT / "outputs" / "m_results_dc34c5b.json"


@pytest.fixture(scope="module")
def ref():
    if not RESULTS.exists():
        pytest.skip("outputs/m_results_dc34c5b.json is local (git-ignored)")
    return json.loads(RESULTS.read_text())


def perfect(ref):
    """API answers that satisfy every expectation."""
    a = {"state": {"index": {p: {"loaded": True, "dropped": 0} for p in "PB"}, "N_a_max": 5, "B_h_max": 120.0,
                   "objective": {"P": {"value": "count"}, "B": {"value": "sum"}}}}
    for p in "PB":
        d, c = ref["default"][p], ref["compare_ayna"][p]
        a[f"optimize {p} defaults"] = {"recommendation": d["recommendation"],
                                       "alternatives": d["alternatives"][:smoke.ALTERNATIVES_SHOWN],
                                       "baselines": {n: {"package": b["package"]} for n, b in d["baselines"].items()}}
        a[f"optimize {p} N_a 5, B_h 105"] = {"recommendation": c["citypilot"]}
        a[f"compare_ayna {p}"] = {"verdict": c["verdict"], "reference": c["reference"],
                                  "optimizer": {"recommendation": c["citypilot"]}, "limits": c["limits"]}
        st = ref["stress_P"] if p == "P" else {"points": [{}] * 9, "worst": {}, "reoptimization": {"recommendation": []}}
        a[f"stress {p}"] = {"status": "ok", "points": st["points"], "worst": st["worst"],
                            "reoptimization": {"recommendation": {"candidate_ids": st["reoptimization"]["recommendation"]}}}
        rec = d["recommendation"]
        a[f"remove {p}"] = {"remaining": {"candidate_ids": rec["candidate_ids"][1:]},
                            "loss_within_t": rec["within_t"] - d["disrupted"]["within_t"],
                            "capped_time_increase": rec["capped_time_sum_reduction"]}
    for label, _, _ in smoke.co2_packages(ref):
        key = {"P recommendation": "P_recommendation", "AYNA reference": "AYNA_reference"}.get(label)
        bus_kg = ref["co2"][key]["bus_kg"] if key else 100.0
        k, n = smoke.EXPECTED_COVERAGE[label]
        a[f"co2 {label}"] = {"bus_kg": bus_kg, "status": "needs_car_trip_km",
                             "car_distance_coverage": {"missing": k, "restored": n}}
        a[f"co2 {label}, 10 km entered"] = {"bus_kg": bus_kg, "car_kg_per_pkm": 0.125211, "status": "complete",
                                            "break_even_trips": math.ceil(bus_kg / (10.0 * 0.125211))}
    return {name: (0.0, answer) for name, answer in a.items()}


def test_perfect_answers_pass_and_the_self_test_detects_tampering(ref):
    answers = perfect(ref)
    checks = smoke.verify(answers, ref)
    assert checks.failures == 0, [r for r in checks.rows if not r[2]]
    assert smoke.self_test(answers, ref) == []


def test_empty_api_alternatives_fail_unless_expected_empty(ref):
    answers = perfect(ref)
    answers["optimize B defaults"] = (0.0, {**answers["optimize B defaults"][1], "alternatives": []})
    assert smoke.verify(answers, ref).failures > 0
    empty = copy.deepcopy(ref)
    empty["default"]["B"]["alternatives"] = []
    assert smoke.verify(answers, empty).failures == 0  # the expected file says empty


def test_alternative_values_are_checked(ref):
    answers = perfect(ref)
    alt = copy.deepcopy(answers["optimize P defaults"][1])
    alt["alternatives"][0]["within_t"] += 1
    answers["optimize P defaults"] = (0.0, alt)
    assert any("alternative 1 within_t" in r[1] for r in smoke.verify(answers, ref).rows if not r[2])


@pytest.mark.parametrize("label, wrong", [("P recommendation", (35, 750)), ("AYNA reference", (41, 881)),
                                          ("B recommendation", (1, 0))])
def test_coverage_must_be_exact(ref, label, wrong):
    answers = perfect(ref)
    body = copy.deepcopy(answers[f"co2 {label}"][1])
    body["car_distance_coverage"] = {"missing": wrong[0], "restored": wrong[1]}
    answers[f"co2 {label}"] = (0.0, body)
    assert smoke.verify(answers, ref).failures == 1
