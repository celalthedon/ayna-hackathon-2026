"""Gate folder selection per profile (P and B have their own normal/disrupted hash pairs)."""
import dataclasses
import os
from pathlib import Path

import pytest

from citypilot.decision_engine import ObjectiveModelMismatch, load_limits, select_objective_dir
from citypilot.decision_real import GATE_DIRS, LIMITS_PATH, gate_dirs_for, gate_hashes, real_limits

from decision_testkit import h, write_objective
from test_api_decision import CountingEvaluators, FIXTURE, client_for, four_action_backend, optimize, strict_json

ROOT = Path(__file__).resolve().parents[1]
PAIR = {name: {"normal": h(f"{name}-normal"), "disrupted": h(f"{name}-disrupted")}
        for name in ("base-P", "base-B", "m-P", "m-B", "other")}


@pytest.fixture
def folders(tmp_path):
    base, m = tmp_path / "objective", tmp_path / "objective" / "m_services_v1"
    write_objective(base, "count", "P", PAIR["base-P"])
    write_objective(base, "sum", "B", PAIR["base-B"])
    write_objective(m, "count", "P", PAIR["m-P"])
    write_objective(m, "sum", "B", PAIR["m-B"])
    return base, m


# --- select_objective_dir ---

def test_selects_the_folder_decided_on_the_model(folders):
    base, m = folders
    assert select_objective_dir((base, m), "P", PAIR["base-P"]) == base
    assert select_objective_dir((base, m), "P", PAIR["m-P"]) == m
    assert select_objective_dir((base, m), "B", PAIR["m-B"]) == m


def test_pairs_are_per_profile(folders):
    with pytest.raises(ObjectiveModelMismatch, match="objective decided for another model"):
        select_objective_dir(folders, "B", PAIR["base-P"])  # P's pair is not B's


def test_unknown_model_is_another_model(folders):
    with pytest.raises(ObjectiveModelMismatch, match="objective decided for another model"):
        select_objective_dir(folders, "P", PAIR["other"])


def test_no_record_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="objective decision missing"):
        select_objective_dir((tmp_path / "a", tmp_path / "b"), "P", PAIR["base-P"])


def test_two_matching_folders_fail_loudly(tmp_path):
    for name in ("a", "b"):
        write_objective(tmp_path / name, "count", "P", PAIR["base-P"])
    with pytest.raises(ValueError, match="several gate folders"):
        select_objective_dir((tmp_path / "a", tmp_path / "b"), "P", PAIR["base-P"])


# --- API ---

def backend_with(tmp_path, folders, hashes):
    return dataclasses.replace(four_action_backend(tmp_path, CountingEvaluators(FIXTURE), objective=False),
                               objective_dirs=folders, model_hashes=hashes)


def test_api_picks_a_folder_per_profile(tmp_path, folders):
    base, m = folders
    c = client_for(backend_with(tmp_path, folders, {"P": PAIR["m-P"], "B": PAIR["m-B"]}))
    s = strict_json(c.get("/decision/state"))
    assert {p: (o["value"], o["objective_dir"]) for p, o in s["objective"].items()} == {
        "P": ("count", str(m)), "B": ("sum", str(m))}
    assert s["model_hashes"] == {"P": PAIR["m-P"], "B": PAIR["m-B"]}
    assert strict_json(optimize(c, 24, profile="P"))["objective"] == "count"
    assert strict_json(optimize(c, 24, profile="B"))["objective"] == "sum"


def test_api_rejects_a_model_with_no_matching_gate(tmp_path, folders):
    c = client_for(backend_with(tmp_path, folders, {"P": PAIR["base-P"], "B": PAIR["other"]}))
    assert optimize(c, 24, profile="P").status_code == 200
    r = optimize(c, 24, profile="B")
    assert r.status_code == 409 and r.json()["detail"] == "objective decided for another model"
    assert strict_json(c.get("/decision/state"))["objective"]["B"]["status"] == "objective decided for another model"


def test_backend_needs_a_pair_per_profile(tmp_path, folders):
    with pytest.raises(ValueError, match="one normal/disrupted pair per profile"):
        backend_with(tmp_path, folders, PAIR["base-P"])
    with pytest.raises(ValueError, match="objective_dirs is empty"):
        backend_with(tmp_path, (), {"P": PAIR["base-P"], "B": PAIR["base-B"]})


# --- real config ---

def test_limits_come_from_config_limits_yaml():
    assert LIMITS_PATH == ROOT / "config" / "limits.yaml"
    assert real_limits() == load_limits(ROOT / "config" / "limits.yaml")


def test_committed_gate_folders():
    assert GATE_DIRS == (ROOT / "config" / "objective", ROOT / "config" / "objective" / "m_services_v1")


@pytest.fixture(scope="module")
def models():
    explicit = os.environ.get("CITYPILOT_TEST_BUNDLE")
    if not explicit:
        pytest.skip("Set CITYPILOT_TEST_BUNDLE to the explicit immutable C4 bundle")
    from citypilot.routing_engine import load_model
    bundle = Path(explicit)
    return {"original": load_model(bundle, bundle / "config"),
            "m": load_model(bundle, ROOT / "supplements" / "m_services_v1" / "config")}


def test_original_model_uses_config_objective(models):
    hashes = gate_hashes(models["original"])
    assert hashes["P"] != hashes["B"]
    assert gate_dirs_for(hashes) == {"P": GATE_DIRS[0], "B": GATE_DIRS[0]}


def test_m_model_uses_the_m_gate_folder(models):
    assert gate_dirs_for(gate_hashes(models["m"])) == {"P": GATE_DIRS[1], "B": GATE_DIRS[1]}


def test_profile_pairs_swapped_is_another_model(models):
    hashes = gate_hashes(models["original"])
    with pytest.raises(ObjectiveModelMismatch, match="objective decided for another model"):
        gate_dirs_for({"P": hashes["B"], "B": hashes["P"]})
