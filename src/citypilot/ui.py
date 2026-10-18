"""Serve the approved CITYPILOT UI inside the existing app and origin."""
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


WEB = Path(__file__).resolve().parents[2] / "web"


class UTF8StaticFiles(StaticFiles):
    """Make text decoding explicit across Windows/Linux MIME registries."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        media = response.headers.get("content-type", "").split(";", 1)[0]
        if media.startswith("text/") or media in ("application/javascript", "application/json"):
            response.headers["content-type"] = media + "; charset=utf-8"
        return response


def mount_ui(app, *, decision_available=False, serve_root=True):
    # An independent namespace avoids replacing a composing app's static mount.
    app.mount("/citypilot-assets", UTF8StaticFiles(directory=WEB / "static"), name="citypilot-assets")

    @app.get("/citypilot", include_in_schema=False)
    async def citypilot_page():
        return FileResponse(WEB / "citypilot.html", media_type="text/html; charset=utf-8")

    if serve_root:
        app.add_api_route("/", citypilot_page, include_in_schema=False)

    @app.get("/citypilot-capabilities", include_in_schema=False)
    async def ui_capabilities():
        return {"decision_available": decision_available,
                "decision_status": "backend_supplied" if decision_available else "pending_real_backend"}
