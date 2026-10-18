"""Focused API composition and metadata tests, independent of decision/A6 work."""
import json
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from citypilot.api import create_app
from citypilot.api_routing import RoutingSettings
from citypilot.ui_metadata import od_metadata
from test_api_routing import model, settings, loader  # existing verified small-model fixtures


def add_display_properties(model):
    for key, field in (("origins", "origin_id"), ("destinations", "destination_id")):
        for stable_id, feature in model[key].items():
            feature["properties"] = {field: stable_id, "private_note": "not public",
                                     "walk_node_id": 123, "origin_kind": "grid"}


def test_fixed_od_metadata_is_allowlisted_identity_bound_and_read_only(settings, loader, model):
    add_display_properties(model)
    with TestClient(create_app(settings)) as client:
        ready = client.get("/routing/ready").json()
        response = client.get("/routing/od_metadata")
        assert response.status_code == 200
        value = response.json()
        assert value["identity"] == {k: v for k, v in ready.items() if k != "status"}
        assert {r["id"] for r in value["origins"]} == set(model["origins"])
        assert {r["id"] for r in value["destinations"]} == set(model["destinations"])
        assert value["selection_policy"] == "fixed_saved_ids_only"
        assert value["unavailable_interventions"] == ["activate_link", "enable_parking"]
        for row in value["origins"] + value["destinations"]:
            assert set(row) == {"id", "coordinates", "properties"}
            assert "walk_node_id" not in row["properties"]
            assert "private_note" not in row["properties"]
        assert str(model["root"]) not in response.text
        assert str(model["config"]) not in response.text
        assert "graphs" not in value and "nodes" not in value
        assert client.post("/routing/od_metadata", json={}).status_code == 405
        assert client.get("/routing/od_metadata").json() == value
        assert next(iter(model["origins"].values()))["properties"]["private_note"] == "not public"


def test_headway_choices_come_from_loaded_config_and_retain_status(model):
    import pandas as pd
    add_display_properties(model)
    original = model["services"]
    try:
        model["services"] = pd.DataFrame([
            dict(service_group_id="SG_R2", headway_low_min=6, headway_default_min=7.5,
                 headway_high_min=10, headway_status="published"),
            dict(service_group_id="SG_R14", headway_low_min=4.5, headway_default_min=5,
                 headway_high_min=8, headway_status="assumption"),
        ])
        headways = od_metadata(model, {})["headways"]
        assert headways == {
            "SG_R2": {"baseline_min": 7.5, "choices_min": [6, 7.5], "status": "published"},
            "SG_R14": {"baseline_min": 5, "choices_min": [4.5, 5], "status": "assumption"},
        }
    finally:
        model["services"] = original


def test_ui_is_same_app_local_assets_and_preserves_existing_routes(settings, loader):
    existing = FastAPI()

    @existing.get("/")
    def root():
        return {"existing": True}

    @existing.get("/decision/state")
    def decision():
        return {"existing_decision": True}

    @existing.get("/static/other")
    def other_static():
        return {"existing_static": True}

    app = create_app(settings, app=existing)
    assert app is existing
    with TestClient(app) as client:
        assert client.get("/").json() == {"existing": True}
        assert client.get("/decision/state").json() == {"existing_decision": True}
        assert client.get("/static/other").json() == {"existing_static": True}
        assert client.get("/routing/ready").status_code == 200
        html = client.get("/citypilot")
        assert html.status_code == 200
        assert "text/html" in html.headers["content-type"]
        assert "charset=utf-8" in html.headers["content-type"]
        assert "file:///" not in html.text and "demoLegs" not in html.text
        assert client.get("/citypilot-capabilities").json()["decision_available"] is True
        for name in ("style.css", "app.js", "routing-adapter.js", "routing-ui.js",
                     "playback.js", "journey-presentation.js", "vendor/three.module.js", "vendor/three.core.js",
                     "vendor/OrbitControls.js", "vendor/BufferGeometryUtils.js", "THREE-LICENSE.txt"):
            asset = client.get("/citypilot-assets/citypilot/" + name)
            assert asset.status_code == 200
            assert "charset=utf-8" in asset.headers["content-type"]
            asset.content.decode("utf-8", errors="strict")
        assert client.get("/citypilot-assets/decision/decision_panel.js").status_code == 200
        assert client.get("/citypilot-assets/../../src/citypilot/api.py").status_code == 404


def test_default_root_and_decision_pending_even_when_routing_unready(tmp_path):
    with TestClient(create_app(RoutingSettings(tmp_path / "missing", tmp_path))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/citypilot").status_code == 200
        assert client.get("/citypilot-capabilities").json() == {
            "decision_available": False, "decision_status": "pending_real_backend"}
        response = client.get("/routing/od_metadata")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_not_ready"
        assert str(tmp_path) not in response.text
        assert client.get("/decision/state").status_code == 404


def test_metadata_error_is_sanitized(settings, loader, model, monkeypatch):
    import citypilot.ui_metadata as metadata
    def broken(*args):
        raise RuntimeError("secret filesystem details")
    monkeypatch.setattr(metadata, "od_metadata", broken)
    with TestClient(create_app(settings)) as client:
        response = client.get("/routing/od_metadata")
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "internal_error", "message": "Routing request failed"}}
        assert "secret" not in response.text


def test_metadata_respects_the_same_routing_admission_gate(settings, loader):
    app = create_app(settings)
    with TestClient(app) as client:
        gate = app.state.citypilot_routing._gate
        assert gate.acquire(blocking=False)
        try:
            response = client.get("/routing/od_metadata")
            assert response.status_code == 429
            assert response.json()["error"]["code"] == "routing_busy"
        finally:
            gate.release()


def test_root_in_an_included_router_is_preserved(settings, loader):
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/")
    def included_root():
        return {"included": True}

    existing = FastAPI()
    existing.include_router(router)
    with TestClient(create_app(settings, app=existing)) as client:
        assert client.get("/").json() == {"included": True}
        assert client.get("/citypilot").status_code == 200


def test_map_and_panel_provenance_not_replaced_with_optimizer_output():
    data = json.loads((ROOT / "web/static/citypilot/pilot-map.json").read_text(encoding="utf-8"))
    assert data["meta"]["counts"]["stations"] == 15
    assert data["meta"]["counts"]["origins"] == 302
    assert data["meta"]["counts"]["destinations"] == 9
    assert all("source" in shape for shape in data["buses"])
    assert not any(key in data for key in ("recommendation", "optimizer", "resources"))
