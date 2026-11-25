"""MCP tools so Claude (claude.ai custom connector) can post to the dashboard."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from . import sources, state

INSTRUCTIONS = """\
Controls Lenny's bedside e-ink dashboard (landscape, black-and-white, read from bed).
The right side shows a boxed bulletin note and an agenda grouped by day.
- set_bulletin: a short note (aim for under ~140 characters; it is cut at 4 lines).
- Agenda rows are ■ events (calendar) and □ due items (schoolwork). Calendar events come
  from Google Calendar automatically; push curated extras or Canvas due dates with
  sync_agenda_items (replaces everything from one source) or add_agenda_items.
- Keep titles short: about 40 characters fit on one line.
"""

mcp = FastMCP("Bedside dashboard", instructions=INSTRUCTIONS)


def attach_auth() -> bool:
    """Single-user OAuth (password login page), shared with Lenny's other MCP servers
    via canvas-viewer-mcp. Configured by PUBLIC_BASE_URL + AUTH_PASSWORD[_HASH] + DB_PATH.
    Returns False when not configured (local dev only)."""
    import os

    if not os.environ.get("PUBLIC_BASE_URL"):
        return False
    from canvas_viewer_mcp.auth.login import register_login_routes
    from canvas_viewer_mcp.auth.provider import SingleUserOAuthProvider
    from canvas_viewer_mcp.config import AuthConfig

    provider = SingleUserOAuthProvider(AuthConfig.from_env())
    mcp.auth = provider
    register_login_routes(mcp, provider)
    return True


_scheduler = None  # set by main


def bind(scheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def _refresh(full: bool = False) -> None:
    if _scheduler:
        _scheduler.refresh(full)


class AgendaItem(BaseModel):
    title: str = Field(description="Short title, ~40 chars fit")
    date: str = Field(description="YYYY-MM-DD, in the dashboard's local time zone")
    time: str | None = Field(None, description="HH:MM 24-hour local time, or omit for all-day / plain due")
    kind: Literal["event", "due"] = Field("event", description="'event' (■) or 'due' (□, e.g. an assignment)")
    course: str | None = Field(None, description="Course code shown in bold after a due item, e.g. 'CHEM 210'")


@mcp.tool()
def set_bulletin(message: str, label: str = "NOTE", expires_in_hours: float | None = None) -> dict:
    """Show a short message in the dashboard's bulletin box (replaces the current one).
    label is kept for compatibility but not displayed. expires_in_hours
    hides it automatically after that long; omit to keep it until replaced or cleared."""
    exp = state.now() + timedelta(hours=expires_in_hours) if expires_in_hours else None
    b = state.set_bulletin(message, label, exp)
    _refresh()
    return {"ok": True, "bulletin": b}


@mcp.tool()
def clear_bulletin() -> dict:
    """Remove the bulletin box from the dashboard."""
    state.clear_bulletin()
    _refresh()
    return {"ok": True}


@mcp.tool()
def get_dashboard() -> dict:
    """What the dashboard currently shows: bulletin, merged agenda (with ids), and push status."""
    return {
        "now": state.now().isoformat(),
        "bulletin": state.active_bulletin(),
        "agenda": sources.agenda(),
        "status": _scheduler.status if _scheduler else None,
    }


@mcp.tool()
def add_agenda_items(items: list[AgendaItem], source: str = "claude") -> dict:
    """Add items to the agenda alongside calendar events."""
    new = state.add_items([i.model_dump() for i in items], source)
    _refresh()
    return {"ok": True, "added": new}


@mcp.tool()
def sync_agenda_items(source: str, items: list[AgendaItem]) -> dict:
    """Replace every item previously pushed under `source` with this list. Use for a full
    sync, e.g. source='canvas' with all upcoming Canvas due dates worth showing."""
    new = state.replace_source(source, [i.model_dump() for i in items])
    _refresh()
    return {"ok": True, "source": source, "count": len(new)}


@mcp.tool()
def remove_agenda_item(item_id: str) -> dict:
    """Remove a pushed item, or hide a calendar event, by the id from get_dashboard."""
    state.remove_item(item_id)
    _refresh()
    return {"ok": True}


@mcp.tool()
def refresh_display(full: bool = False) -> dict:
    """Re-render and push now. full=True does a flashing refresh that clears ghosting."""
    _refresh(full)
    return {"ok": True}
