"""Small JSON-file store for things Claude pushes: the bulletin and agenda items."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any

from .config import settings

_lock = threading.Lock()
_path = settings.data_dir / "state.json"


def _empty() -> dict[str, Any]:
    return {"bulletin": None, "items": [], "hidden": []}


def load() -> dict[str, Any]:
    with _lock:
        try:
            data = json.loads(_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = _empty()
    for k, v in _empty().items():
        data.setdefault(k, v)
    return data


def save(data: dict[str, Any]) -> None:
    with _lock:
        _path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(_path)


def now() -> datetime:
    return datetime.now(settings.tz)


# ---- bulletin -------------------------------------------------------------

def set_bulletin(message: str, label: str = "NOTE", expires_at: datetime | None = None) -> dict:
    data = load()
    data["bulletin"] = {
        "message": message.strip(),
        "label": (label or "NOTE").strip().upper()[:12],
        "set_at": now().isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    save(data)
    return data["bulletin"]


def clear_bulletin() -> None:
    data = load()
    data["bulletin"] = None
    save(data)


def active_bulletin() -> dict | None:
    b = load()["bulletin"]
    if not b:
        return None
    if b.get("expires_at") and datetime.fromisoformat(b["expires_at"]) < now():
        return None
    return b


# ---- pushed agenda items --------------------------------------------------

def _normalize(item: dict, source: str) -> dict:
    kind = item.get("kind", "event")
    if kind not in ("event", "due"):
        raise ValueError("kind must be 'event' or 'due'")
    date = str(item["date"])[:10]
    datetime.strptime(date, "%Y-%m-%d")
    t = item.get("time") or None
    if t:
        datetime.strptime(t, "%H:%M")
    return {
        "id": item.get("id") or uuid.uuid4().hex[:8],
        "source": source,
        "kind": kind,
        "date": date,
        "time": t,
        "title": str(item["title"]).strip(),
        "course": (item.get("course") or None),
    }


def add_items(items: list[dict], source: str = "claude") -> list[dict]:
    data = load()
    new = [_normalize(i, source) for i in items]
    data["items"].extend(new)
    save(data)
    return new


def replace_source(source: str, items: list[dict]) -> list[dict]:
    """Replace every pushed item from `source` (e.g. a full Canvas sync)."""
    data = load()
    new = [_normalize(i, source) for i in items]
    data["items"] = [i for i in data["items"] if i["source"] != source] + new
    save(data)
    return new


def remove_item(item_id: str) -> bool:
    """Remove a pushed item, or hide a calendar event by its id."""
    data = load()
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if i["id"] != item_id]
    removed = len(data["items"]) < before
    if not removed and item_id not in data["hidden"]:
        data["hidden"].append(item_id)
    save(data)
    return True


def unhide_all() -> None:
    data = load()
    data["hidden"] = []
    save(data)
