"""Shared-contract routing HTTP adapter; one admitted job, no application cache."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from threading import BoundedSemaphore
from typing import Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from citypilot import routing_engine
from citypilot.contracts import (
    CONTRACT_VERSION, ContractError, EvaluationResult, JourneyResult, ModelCatalog,
    RoutingRequest, StressFactorsNotSupported,
)

LOG = logging.getLogger(__name__)
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RoutingSettings:
    artifact_dir: Path
    config_dir: Path

    def __post_init__(self):
        for name in ("artifact_dir", "config_dir"):
            value = Path(getattr(self, name))
            if not value.is_absolute():
                raise ValueError(name + " must be an explicit absolute directory")
            object.__setattr__(self, name, value)

    @classmethod
    def from_env(cls):
        names = ("CITYPILOT_ARTIFACT_DIR", "CITYPILOT_CONFIG_DIR")
        missing = [name for name in names if not os.environ.get(name, "").strip()]
        if missing:
            raise ValueError("Explicit startup settings required: " + ", ".join(missing))
        return cls(Path(os.environ[names[0]]), Path(os.environ[names[1]]))


class RoutingAPIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _error(exc: RoutingAPIError):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}},
                        status_code=exc.status,
                        headers={"Retry-After": "1"} if exc.status == 429 else None)


class RoutingRuntime:
    """Per-app lifetime, one worker and zero waiting jobs (immediate 429).

    Serialization is part of the admitted job. A disconnected/cancelled caller
    cannot free admission while its CPU work is still running.
    """
    def __init__(self, settings: RoutingSettings):
        self.settings = settings
        self.model = None
        self.identity = None
        self.ready = False
        self._started = False
        self._gate = BoundedSemaphore(1)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="citypilot-routing")

    async def start(self):
        if self._started:
            raise RuntimeError("Routing lifetime cannot start twice")
        self._started = True

        def load():
            model = routing_engine.load_model(self.settings.artifact_dir, self.settings.config_dir)
            catalog = routing_engine.get_catalog(model)
            if type(catalog) is not ModelCatalog:
                raise TypeError("Expected shared ModelCatalog")
            catalog.to_json()  # startup validation; no catalog response cache
            identity = {
                "contract_version": CONTRACT_VERSION,
                "model_version": catalog.model_version,
                "od_set_id": catalog.od_set_id,
                "bundle_hash": model["manifest"]["bundle_hash"],
                "od_hash": model["od"]["od_hash"],
                "supplement_hash": model.get("supplement_hash"),
                "closure_id": model["closure_id"],
                "origin_count": len(model["origins"]),
                "destination_count": len(model["destinations"]),
            }
            return model, identity

        try:
            self.model, self.identity = await asyncio.get_running_loop().run_in_executor(self._executor, load)
            self.ready = True
        except Exception:
            # Keep readiness and existing decision routes usable; never disclose
            # artifact paths, corrupt file contents or tracebacks over HTTP.
            LOG.exception("Routing model startup failed")

    async def close(self):
        self.ready = False
        await asyncio.to_thread(self._executor.shutdown, wait=True)
        self.model = None
        self.identity = None

    async def run(self, operation: Callable):
        if not self.ready:
            raise RoutingAPIError(503, "model_not_ready", "Routing model is not ready")
        if not self._gate.acquire(blocking=False):
            raise RoutingAPIError(429, "routing_busy", "One routing job is already running; retry later")
        try:
            future = self._executor.submit(operation)
        except BaseException:
            self._gate.release()
            raise
        future.add_done_callback(lambda _: self._gate.release())
        return await asyncio.shield(asyncio.wrap_future(future))


async def _body(request: Request) -> bytes:
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise RoutingAPIError(415, "unsupported_media_type", "Use application/json")
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise RoutingAPIError(413, "request_too_large", "Routing JSON body exceeds 1 MiB")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(payload: bytes):
    try:
        return RoutingRequest.from_json(payload)
    except (ValueError, RecursionError) as exc:
        raise RoutingAPIError(422, "invalid_request", str(exc)) from exc


def _calculate(runtime, payload, origin_id=None, destination_id=None):
    request = _parse(payload)
    try:
        if origin_id is None:
            result = routing_engine.evaluate_package(runtime.model, request)
            expected = EvaluationResult
        else:
            result = routing_engine.inspect_journey(runtime.model, request, origin_id, destination_id)
            expected = JourneyResult
    except StressFactorsNotSupported as exc:
        raise RoutingAPIError(501, "not_available", "Requested routing capability is not available") from exc
    except ContractError as exc:
        raise RoutingAPIError(422, "invalid_request", str(exc)) from exc
    # A broken result is a server failure, not a bad client request.
    if type(result) is not expected:
        raise TypeError("Routing returned a non-shared result")
    result.validate_request(request)
    return result.to_json()


def build_routing_router(runtime: RoutingRuntime) -> APIRouter:
    router = APIRouter(prefix="/routing", tags=["routing"])

    @router.get("/ready")
    async def readiness():
        if not runtime.ready:
            return _error(RoutingAPIError(503, "model_not_ready", "Routing model is not ready"))
        return {"status": "ready", **runtime.identity}

    @router.get("/catalog")
    async def catalog():
        def serialize():
            result = routing_engine.get_catalog(runtime.model)
            if type(result) is not ModelCatalog:
                raise TypeError("Routing returned a non-shared catalog")
            return result.to_json()
        try:
            return Response(await runtime.run(serialize), media_type="application/json")
        except RoutingAPIError as exc:
            return _error(exc)
        except Exception:
            LOG.exception("Routing catalog failed")
            return _error(RoutingAPIError(500, "internal_error", "Routing request failed"))

    async def calculate(request, origin_id=None, destination_id=None):
        try:
            payload = await _body(request)
            result = await runtime.run(lambda: _calculate(runtime, payload, origin_id, destination_id))
            return Response(result, media_type="application/json")
        except RoutingAPIError as exc:
            return _error(exc)
        except Exception:
            LOG.exception("Routing calculation failed")
            return _error(RoutingAPIError(500, "internal_error", "Routing request failed"))

    @router.post("/evaluate_package")
    async def evaluate(request: Request):
        return await calculate(request)

    @router.post("/inspect_journey")
    async def journey(request: Request,
                      origin_id: str = Query(min_length=1, max_length=256),
                      destination_id: str = Query(min_length=1, max_length=256)):
        return await calculate(request, origin_id, destination_id)

    return router
