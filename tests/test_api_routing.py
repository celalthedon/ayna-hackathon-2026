"""Routing HTTP/lifecycle tests. Synthetic cases are not M-service evidence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
import threading
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from citypilot.api import create_app
from citypilot.api_routing import RoutingSettings, RoutingRuntime, RoutingAPIError, MAX_BODY_BYTES
from citypilot import routing_engine as e
from citypilot.contracts import EvaluationResult, JourneyResult, ModelCatalog, StressFactorsNotSupported
from test_activate_service import small, registry


@pytest.fixture
def model(tmp_path):
    model, data = small(tmp_path / "bundle")
    registry(model["config"], data, model["manifest"]["bundle_hash"])
    e._load_prebuilt(model)
    return model


@pytest.fixture
def settings(model):
    return RoutingSettings(model["root"], model["config"])


@pytest.fixture
def loader(monkeypatch, model):
    load = Mock(return_value=model)
    monkeypatch.setattr(e, "load_model", load)
    return load


def post(client, request, path="/routing/evaluate_package", **kwargs):
    return client.post(path, content=request.to_json(), headers={"content-type": "application/json"}, **kwargs)


def test_settings_require_explicit_absolute_paths(monkeypatch, tmp_path):
    for name in ("CITYPILOT_ARTIFACT_DIR", "CITYPILOT_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="Explicit startup settings"):
        create_app()
    with pytest.raises(ValueError, match="absolute"):
        RoutingSettings(Path("relative"), tmp_path)
    monkeypatch.setenv("CITYPILOT_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("CITYPILOT_CONFIG_DIR", str(tmp_path / "config"))
    assert RoutingSettings.from_env() == RoutingSettings(tmp_path, tmp_path / "config")


def test_load_once_readiness_catalog_shared_serializers_and_close(settings, loader, model):
    app = create_app(settings)
    assert not app.state.citypilot_routing.ready
    with TestClient(app) as client:
        ready = client.get("/routing/ready")
        assert ready.status_code == 200
        identity = ready.json()
        catalog = ModelCatalog.from_json(client.get("/routing/catalog").content)
        assert identity["model_version"] == catalog.model_version
        assert identity["od_set_id"] == catalog.od_set_id
        assert identity["supplement_hash"] == model["supplement_hash"]
        assert set(catalog.prebuilt_services) == {"SYN6", "SYN9"}
        assert identity["bundle_hash"] == model["manifest"]["bundle_hash"]
        assert identity["od_hash"] == model["od"]["od_hash"]
        request = e.baseline_request(model, "disrupted")
        result = EvaluationResult.from_json(post(client, request).content)
        result.validate_request(request)
        journey = JourneyResult.from_json(post(client, request, "/routing/inspect_journey",
            params={"origin_id": "o", "destination_id": "d2"}).content)
        journey.validate_request(request)
        assert abs(journey.total_min - sum(leg.total_min for leg in journey.legs)) < 1e-9
        for _ in range(3):
            assert client.get("/routing/ready").status_code == 200
        loader.assert_called_once_with(settings.artifact_dir, settings.config_dir)
    assert not app.state.citypilot_routing.ready
    assert app.state.citypilot_routing.model is None


def test_model_load_failure_is_unready_sanitized_and_not_retried(tmp_path, monkeypatch):
    load = Mock(side_effect=RuntimeError("private artifact path and secret input"))
    monkeypatch.setattr(e, "load_model", load)
    app = create_app(RoutingSettings(tmp_path, tmp_path))
    with TestClient(app) as client:
        for path in ("/routing/ready", "/routing/catalog"):
            response = client.get(path)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "model_not_ready"
            assert "private" not in response.text
        response = client.post("/routing/evaluate_package", content="{}", headers={"content-type": "application/json"})
        assert response.status_code == 503
        load.assert_called_once()


def test_actual_missing_bundle_load_is_unready(tmp_path):
    with TestClient(create_app(RoutingSettings(tmp_path / "missing", tmp_path))) as client:
        assert client.get("/routing/ready").status_code == 503


@pytest.mark.parametrize("raw", [
    b"{}", b"[]", b"not JSON", b'{"contract_version":"v1"}',
    b'{"state":"normal","state":"normal"}', b'{"speed_factor":NaN}',
    b'{"speed_factor":Infinity}', b'\xff', b"[" * 1100,
    b'{"cap_min":' + b"9" * 5000 + b"}",
])
def test_strict_wire_rejection(settings, loader, raw):
    with TestClient(create_app(settings)) as client:
        response = client.post("/routing/evaluate_package", content=raw, headers={"content-type": "application/json"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_media_body_limit_unknown_fields_identity_and_journey_ids(settings, loader, model):
    request = e.baseline_request(model)
    with TestClient(create_app(settings)) as client:
        assert client.post("/routing/evaluate_package", content="{}").status_code == 415
        assert client.post("/routing/evaluate_package", content=b"x" * (MAX_BODY_BYTES + 1),
            headers={"content-type": "application/json"}).status_code == 413
        for payload in (dict(request.to_dict(), extra=True), dict(request.to_dict(), model_version="other"),
                        dict(request.to_dict(), speed_factor=False)):
            assert client.post("/routing/evaluate_package", json=payload).status_code == 422
        assert post(client, request, "/routing/inspect_journey").status_code == 422
        assert post(client, request, "/routing/inspect_journey",
            params={"origin_id": "unknown", "destination_id": "d2"}).status_code == 422


def test_unsupported_capability_and_malformed_input_are_distinct(settings, loader, model):
    from citypilot.contracts import RoutingPatch
    request = replace(e.baseline_request(model, "mitigated"),
        patches=(RoutingPatch(kind="activate_link", target_id="future"),))
    with TestClient(create_app(settings)) as client:
        response = post(client, request)
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "not_available"
        invalid = dict(request.to_dict(), speed_factor=0)
        assert client.post("/routing/evaluate_package", json=invalid).status_code == 422


def test_unexpected_errors_and_invalid_results_are_sanitized(settings, loader, model, monkeypatch):
    with TestClient(create_app(settings)) as client:
        request = e.baseline_request(model)
        def broken(*args):
            raise RuntimeError("secret C:/private/data")
        monkeypatch.setattr(e, "evaluate_package", broken)
        response = post(client, request)
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "internal_error", "message": "Routing request failed"}}
        assert "secret" not in response.text
        monkeypatch.setattr(e, "evaluate_package", lambda *args: {"unvalidated": True})
        assert post(client, request).status_code == 500
        monkeypatch.setattr(e, "get_catalog", broken)
        assert client.get("/routing/catalog").status_code == 500


def test_one_job_no_waiting_queue_and_event_loop_responsive(settings, loader, model, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = e.evaluate_package
    threads = []
    def blocked(*args):
        threads.append(threading.get_ident())
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test release missing")
        return original(*args)
    monkeypatch.setattr(e, "evaluate_package", blocked)
    app = FastAPI()
    @app.get("/event-loop-thread")
    async def event_loop_thread():
        return threading.get_ident()
    create_app(settings, app=app)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(post, client, e.baseline_request(model))
        try:
            assert entered.wait(3)
            assert client.get("/routing/ready").status_code == 200
            assert client.get("/event-loop-thread").json() != threads[0]
            busy = client.get("/routing/catalog")
            assert busy.status_code == 429
            assert busy.headers["Retry-After"] == "1"
            assert post(client, e.baseline_request(model)).status_code == 429
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
        assert client.get("/routing/catalog").status_code == 200


def test_cancelled_caller_does_not_release_running_worker(settings, loader):
    async def case():
        runtime = RoutingRuntime(settings)
        await runtime.start()
        entered, release = threading.Event(), threading.Event()
        def blocked():
            entered.set()
            release.wait(5)
            return 1
        try:
            task = asyncio.create_task(runtime.run(blocked))
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.01)
            assert entered.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(RoutingAPIError) as busy:
                await runtime.run(lambda: 2)
            assert busy.value.status == 429
            release.set()
            for _ in range(100):
                try:
                    assert await runtime.run(lambda: 2) == 2
                    break
                except RoutingAPIError:
                    await asyncio.sleep(.01)
            else:
                pytest.fail("Worker did not release admission")
        finally:
            release.set()
            await runtime.close()
    asyncio.run(case())


def test_existing_factory_lifespan_and_decision_endpoints_preserved(settings, loader, tmp_path):
    from citypilot.decision_dev import fixture_stress_backend
    from citypilot.api_decision import build_decision_router
    events = []
    @asynccontextmanager
    async def lifetime(app):
        events.append("start")
        yield
        events.append("stop")
    existing = FastAPI(lifespan=lifetime)
    backend = fixture_stress_backend(tmp_path, tmp_path / "cache")
    existing.include_router(build_decision_router(backend))
    with TestClient(existing) as before:
        expected = before.get("/decision/state").json()
    app = create_app(settings, app=existing)
    assert app is existing
    with TestClient(app) as client:
        assert client.get("/decision/state").json() == expected
        assert client.get("/routing/ready").status_code == 200
    assert events == ["start", "stop", "start", "stop"]
    with pytest.raises(ValueError, match="already mounted"):
        create_app(settings, app=app)
    other = FastAPI()
    other.include_router(build_decision_router(backend))
    with pytest.raises(ValueError, match="already mounted"):
        create_app(settings, app=other, decision_backend=backend)
    with TestClient(create_app(settings, decision_backend=backend)) as client:
        assert client.get("/decision/state").status_code == 200


@pytest.mark.skipif(not os.environ.get("CITYPILOT_TEST_BUNDLE"), reason="Explicit C4 bundle required")
def test_real_baseline_and_terminal_journey_over_http():
    bundle = Path(os.environ["CITYPILOT_TEST_BUNDLE"])
    app = create_app(RoutingSettings(bundle, bundle / "config"))
    with TestClient(app) as client:
        ready = client.get("/routing/ready").json()
        request = e.baseline_request(app.state.citypilot_routing.model, "disrupted", "P")
        assert request.model_version == ready["model_version"]
        assert request.od_set_id == ready["od_set_id"]
        response = post(client, request)
        assert response.status_code == 200
        result = EvaluationResult.from_json(response.content)
        result.validate_request(request)
        assert len(result.od_results) == 2718
        assert tuple(result.within_counts[t] for t in (40, 45, 50)) == (636, 1191, 1697)
        model = app.state.citypilot_routing.model
        origin = "origin:terminal:baku_international"
        destination = next(iter(model["destinations"]))
        response = post(client, request, "/routing/inspect_journey",
            params={"origin_id": origin, "destination_id": destination})
        assert response.status_code == 200
        journey = JourneyResult.from_json(response.content)
        journey.validate_request(request)
        assert abs(sum(leg.total_min for leg in journey.legs) - journey.total_min) < 1e-6
        od = next(r for r in result.od_results if r.od_id == journey.od_id)
        assert abs(od.minutes - journey.total_min) < 1e-6
        print("real API baseline:", dict(result.within_counts), "duration_ms:", result.duration_ms,
              "journey_min:", journey.total_min, "legs:", len(journey.legs))


@pytest.mark.parametrize("prefix", ["/decision", "/routing"])
def test_lazy_nested_hidden_and_mounted_router_detection(settings, loader, prefix):
    from fastapi import APIRouter
    from citypilot.api import _has_route_prefix
    nested = APIRouter()
    nested.get("/private", include_in_schema=False)(lambda: None)
    outer = APIRouter()
    outer.include_router(nested, prefix=prefix)
    app = FastAPI()
    app.include_router(outer)
    assert _has_route_prefix(app, prefix)
    mount = FastAPI()
    mount.mount(prefix, FastAPI())
    assert _has_route_prefix(mount, prefix)
    unrelated = FastAPI()
    unrelated.get(prefix + "_other")(lambda: None)
    assert not _has_route_prefix(unrelated, prefix)


def test_startup_rejects_actual_manifest_corruption(tmp_path):
    import hashlib, json
    root = tmp_path / "bundle"
    root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (root / "payload").write_bytes(b"corrupt")
    files = {"payload": hashlib.sha256(b"expected").hexdigest()}
    manifest = {"artifact_version": "c4-alpha-1", "files": files,
        "bundle_hash": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    (root / "manifest.json").write_text(json.dumps(manifest))
    with TestClient(create_app(RoutingSettings(root, config))) as client:
        response = client.get("/routing/ready")
        assert response.status_code == 503
        assert "payload" not in response.text
        assert client.get("/routing/catalog").status_code == 503


@pytest.mark.skipif(not os.environ.get("CITYPILOT_TEST_BUNDLE"), reason="Explicit C4 bundle required")
def test_actual_external_synthetic_supplement_load(tmp_path):
    import shutil,json
    bundle = Path(os.environ["CITYPILOT_TEST_BUNDLE"])
    config = tmp_path / "config"
    shutil.copytree(bundle / "config", config)
    shutil.copytree(ROOT / "tests/fixtures/prebuilt_services", config / "prebuilt_services")
    expected = json.loads((config / "prebuilt_services/manifest.json").read_text())
    with TestClient(create_app(RoutingSettings(bundle, config))) as client:
        ready = client.get("/routing/ready")
        assert ready.status_code == 200
        assert ready.json()["supplement_hash"] == expected["supplement_hash"]
        assert "+prebuilt@" + expected["supplement_hash"] in ready.json()["model_version"]
        catalog = ModelCatalog.from_json(client.get("/routing/catalog").content)
        assert len(catalog.prebuilt_services) == 2
        assert set(catalog.service_groups) == {"SG_R2", "SG_R14"}


def test_actual_existing_dev_factory_can_be_extended(settings, loader, tmp_path, monkeypatch):
    from citypilot import decision_dev
    # Existing demo remains explicitly synthetic; its files stay in test temp.
    monkeypatch.setattr(decision_dev, "DEV_DIR", tmp_path / "decision-demo")
    existing = decision_dev.create_dev_app()
    app = create_app(settings, app=existing)
    assert app is existing
    with TestClient(app) as client:
        assert client.get("/decision/state").status_code == 200
        assert client.get("/routing/ready").status_code == 200
        assert client.get("/").status_code == 200
        paths = client.get("/openapi.json").json()["paths"]
        assert "/decision/state" in paths and "/routing/catalog" in paths


def test_clean_process_import_has_no_notebook_or_model_side_effects():
    import subprocess
    script = ("import sys; sys.path.insert(0, " + repr(str(ROOT / "src")) + "); "
        "import citypilot.api; "
        "assert not any(n.startswith(('IPython','jupyter','numpy','pandas')) for n in sys.modules); "
        "print('clean API import OK')")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "clean API import OK" in result.stdout


@pytest.mark.skipif(not os.environ.get("CITYPILOT_TEST_BUNDLE"), reason="Explicit C4 bundle required")
def test_repository_m_config_identity_preserves_decision_endpoints(tmp_path):
    import json
    from citypilot.decision_dev import fixture_stress_backend
    from citypilot.api_decision import build_decision_router
    bundle = Path(os.environ["CITYPILOT_TEST_BUNDLE"])
    config = ROOT / "supplements/m_services_v1/config"
    manifest = json.loads((config / "prebuilt_services/manifest.json").read_text())
    baseline = json.loads((bundle / "manifest.json").read_text())
    od = json.loads((bundle / "od/manifest.json").read_text())
    baseline_identity = baseline["artifact_version"] + "@" + baseline["bundle_hash"]
    backend = fixture_stress_backend(tmp_path, tmp_path / "cache")
    existing = FastAPI()
    existing.include_router(build_decision_router(backend))
    with TestClient(existing) as before:
        expected_decision = before.get("/decision/state").json()
    app = create_app(RoutingSettings(bundle, config), app=existing)
    with TestClient(app) as client:
        response = client.get("/routing/ready")
        assert response.status_code == 200
        ready = response.json()
        assert ready["bundle_hash"] == baseline["bundle_hash"]
        assert ready["model_version"] == baseline_identity + "+prebuilt@" + manifest["supplement_hash"]
        assert ready["od_set_id"] == od["od_version"] + "@" + od["od_hash"]
        assert ready["supplement_hash"] == manifest["supplement_hash"]
        catalog = ModelCatalog.from_json(client.get("/routing/catalog").content)
        assert set(catalog.service_groups) == {"SG_R2", "SG_R14"}
        assert set(catalog.prebuilt_services) == {f"SVC_M{line}_{variant}"
            for line in (1, 2, 3, 5, 6) for variant in ("A", "B")}
        assert client.get("/decision/state").json() == expected_decision
        # A baseline-model payload must not silently adopt the M identity.
        wrong_model_request = e.baseline_request(app.state.citypilot_routing.model, "disrupted")
        wrong_model_request = replace(wrong_model_request, model_version=baseline_identity)
        assert post(client, wrong_model_request).status_code == 422
    print("Repository M config startup/catalog + preserved decision endpoints: PASS; no gate/activation evaluation")
