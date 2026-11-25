"""FastAPI app: preview pages, REST API, MCP endpoint, and the push loop."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import mcp_server, render, sources, state
from .config import settings
from .render import Renderer
from .scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs full request URLs at INFO, which would leak the private iCal address.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("eink")

renderer = Renderer()
scheduler = Scheduler(renderer)
mcp_server.bind(scheduler)


_auth = mcp_server.attach_auth()
if not _auth:
    if settings.mcp_no_auth:
        log.warning("MCP endpoint is UNAUTHENTICATED (MCP_NO_AUTH=true); local dev only")
    else:
        log.warning("PUBLIC_BASE_URL not set: MCP endpoint disabled")
# Streamable HTTP at /mcp; OAuth routes (/.well-known/*, /authorize, /token,
# /register, /login) live at the root of this sub-app.
mcp_app = mcp_server.mcp.http_app(path="/mcp") if (_auth or settings.mcp_no_auth) else None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await renderer.start()
    task = asyncio.create_task(scheduler.run())
    if mcp_app:
        async with mcp_app.lifespan(app):
            yield
    else:
        yield
    task.cancel()
    await renderer.stop()


app = FastAPI(title="Bedside e-ink dashboard", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def require_token(authorization: str = Header(default="")) -> None:
    if not settings.api_token or authorization != f"Bearer {settings.api_token}":
        raise HTTPException(401, "bad or missing token")


@app.get("/healthz")
def healthz():
    return {"ok": True, **scheduler.status}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><meta charset=utf-8><title>Bedside dashboard</title>
<meta http-equiv=refresh content=60>
<body style="font-family:sans-serif;background:#ddd;margin:24px">
<p><a href=/dash.html>live HTML</a> · <a href=/latest.png>panel PNG</a> · <a href=/healthz>status</a></p>
<img src=/latest-landscape.png style="max-width:100%;border:1px solid #888"></body>"""


@app.get("/dash.html", response_class=HTMLResponse)
def dash_html():
    return render.render_html()


@app.get("/latest.png")
def latest_png():
    return FileResponse(settings.data_dir / "latest.png", media_type="image/png")


@app.get("/latest-landscape.png")
def latest_landscape():
    return FileResponse(settings.data_dir / "latest-landscape.png", media_type="image/png")


class BulletinIn(BaseModel):
    message: str
    label: str = "NOTE"
    expires_in_hours: float | None = None


@app.post("/api/bulletin", dependencies=[Depends(require_token)])
def post_bulletin(b: BulletinIn):
    exp = state.now() + timedelta(hours=b.expires_in_hours) if b.expires_in_hours else None
    out = state.set_bulletin(b.message, b.label, exp)
    scheduler.refresh()
    return out


@app.delete("/api/bulletin", dependencies=[Depends(require_token)])
def delete_bulletin():
    state.clear_bulletin()
    scheduler.refresh()
    return {"ok": True}


@app.get("/api/agenda", dependencies=[Depends(require_token)])
def get_agenda():
    return sources.agenda()


@app.put("/api/agenda/{source}", dependencies=[Depends(require_token)])
def put_agenda(source: str, items: list[mcp_server.AgendaItem]):
    new = state.replace_source(source, [i.model_dump() for i in items])
    scheduler.refresh()
    return {"count": len(new)}


@app.post("/api/refresh", dependencies=[Depends(require_token)])
def post_refresh(full: bool = False):
    scheduler.refresh(full)
    return {"ok": True}


@app.post("/api/brightness", dependencies=[Depends(require_token)])
def post_brightness(level: int | None = None):
    """Override the frontlight (0-24); omit level to go back to the day/night schedule."""
    if level is not None and not 0 <= level <= 24:
        raise HTTPException(400, "level must be 0-24")
    scheduler.brightness_override = level
    scheduler.refresh()
    return {"brightness": scheduler.brightness()}


# Last, so the dashboard routes above take precedence.
if mcp_app:
    app.mount("/", mcp_app)
