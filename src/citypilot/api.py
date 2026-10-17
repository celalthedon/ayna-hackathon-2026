"""One composable FastAPI app factory; no notebook execution or server at import."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from citypilot.api_routing import RoutingRuntime, RoutingSettings, build_routing_router


def _has_route_prefix(app, prefix):
    # FastAPI 0.143 keeps included routers lazily; direct route.path inspection
    # alone misses them. Also inspect mounts and endpoints hidden from OpenAPI.
    def paths(routes, parent=""):
        for route in routes:
            included = getattr(route, "original_router", None)
            if included is not None:
                context = getattr(route, "include_context", None)
                yield from paths(included.routes, parent + getattr(context, "prefix", ""))
            else:
                path = parent + getattr(route, "path", "")
                yield path
                yield from paths(getattr(route, "routes", ()), path)
    return any(path == prefix or path.startswith(prefix + "/") for path in paths(app.routes))


def create_app(settings: RoutingSettings | None = None, *, app: FastAPI | None = None,
               decision_backend=None) -> FastAPI:
    """Add routing to an existing factory's app, or create the roadmap base app.

    Existing decision endpoints/lifespan are preserved. Supplying Ali's backend
    is the only way this factory adds /decision; no fixture/optimizer is wired
    implicitly. Ali owns constructing his real backend (A6/precompute).
    """
    settings = settings if settings is not None else RoutingSettings.from_env()
    app = app if app is not None else FastAPI(title="CityPilot")
    if hasattr(app.state, "citypilot_routing") or _has_route_prefix(app, "/routing"):
        raise ValueError("Routing is already mounted")
    if decision_backend is not None:
        if _has_route_prefix(app, "/decision"):
            raise ValueError("Decision router is already mounted; do not supply a second backend")
        from citypilot.api_decision import build_decision_router
        app.include_router(build_decision_router(decision_backend))

    runtime = RoutingRuntime(settings)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application) as state:
            try:
                await runtime.start()
                yield state
            finally:
                await runtime.close()

    app.router.lifespan_context = lifespan
    app.state.citypilot_routing = runtime
    app.include_router(build_routing_router(runtime))
    app.openapi_schema = None  # existing factories may already have built it
    return app
