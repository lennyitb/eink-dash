"""Data sources: Google Calendar (private iCal URLs), Open-Meteo weather, pushed items."""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import icalendar
import recurring_ical_events

from . import state
from .config import settings

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # keep showing stale data if a fetch fails
        log.warning("fetch %s failed: %s", key, e)
        return hit[1] if hit else None
    _cache[key] = (time.monotonic(), val)
    return val


# ---- calendar -------------------------------------------------------------

def _fetch_calendar(url: str) -> list[dict]:
    r = httpx.get(url, timeout=20, follow_redirects=True)
    r.raise_for_status()
    cal = icalendar.Calendar.from_ical(r.content)
    today = state.now().date()
    start, end = today, today + timedelta(days=settings.agenda_days)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = ev.get("DTSTART").dt
        dtend = ev.get("DTEND").dt if ev.get("DTEND") else None
        uid = str(ev.get("UID", ""))
        if isinstance(dtstart, datetime):
            local = dtstart.astimezone(settings.tz)
            d, t = local.date(), local.strftime("%H:%M")
        else:
            d, t = dtstart, None
            # multi-day all-day events: show on each day still in range
        days = [d]
        if t is None and isinstance(dtend, date) and not isinstance(dtend, datetime):
            days = [d + timedelta(n) for n in range((dtend - d).days)] or [d]
        for day in days:
            if not (start <= day < end):
                continue
            rid = hashlib.sha1(f"{uid}|{day}|{t}".encode()).hexdigest()[:8]
            out.append({
                "id": f"cal-{rid}", "source": "calendar", "kind": "event",
                "date": day.isoformat(), "time": t,
                "title": str(ev.get("SUMMARY", "(no title)")).strip(), "course": None,
            })
    return out


def calendar_events() -> list[dict]:
    events: list[dict] = []
    for url in settings.calendar_ics_urls:
        key = "cal:" + hashlib.sha1(url.encode()).hexdigest()
        events += _cached(key, 600, lambda u=url: _fetch_calendar(u)) or []
    return events


# ---- weather --------------------------------------------------------------

# WMO weather codes -> (label, icon)
_WMO = {
    0: ("Clear", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloud"), 45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"), 80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"),
    82: ("Heavy showers", "rain"), 85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorms", "storm"), 96: ("Thunderstorms", "storm"), 99: ("Thunderstorms", "storm"),
}


def _fetch_weather() -> dict:
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
        "latitude": settings.weather_lat, "longitude": settings.weather_lon,
        "current": "temperature_2m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "temperature_unit": settings.weather_units, "timezone": str(settings.tz),
        "forecast_days": 4,
    })
    r.raise_for_status()
    j = r.json()
    cur, daily = j["current"], j["daily"]
    label, icon = _WMO.get(cur["weather_code"], ("—", "cloud"))
    days = []
    for i in range(1, 4):
        d = date.fromisoformat(daily["time"][i])
        days.append({"dow": d.strftime("%a").upper(),
                     "hi": round(daily["temperature_2m_max"][i]),
                     "lo": round(daily["temperature_2m_min"][i])})
    return {"temp": round(cur["temperature_2m"]), "label": label, "icon": icon,
            "hi": round(daily["temperature_2m_max"][0]),
            "lo": round(daily["temperature_2m_min"][0]), "days": days}


def weather() -> dict | None:
    if settings.weather_lat is None or settings.weather_lon is None:
        return None
    return _cached("weather", 900, _fetch_weather)


# ---- birthdays (iCloud Contacts) -------------------------------------------

def birthday_items() -> list[dict]:
    if not (settings.icloud_username and settings.icloud_app_password):
        return []
    from . import birthdays

    contacts = _cached("birthdays", 6 * 3600, birthdays.fetch_contacts) or []
    return birthdays.upcoming(contacts, state.now().date(), settings.agenda_days)


# ---- merged agenda --------------------------------------------------------

def agenda() -> list[dict]:
    """All upcoming items (calendar + pushed), minus hidden ones, sorted."""
    st = state.load()
    hidden = set(st["hidden"])
    today = state.now().date().isoformat()
    last = (state.now().date() + timedelta(days=settings.agenda_days)).isoformat()
    items = [i for i in calendar_events() + birthday_items() + st["items"]
             if i["id"] not in hidden and today <= i["date"] < last]
    # all-day first, then timed, events before dues at the same time
    items.sort(key=lambda i: (i["date"], i["time"] is not None, i["time"] or "", i["kind"] != "event"))
    return items


def prune_past_items() -> None:
    st = state.load()
    today = state.now().date().isoformat()
    keep = [i for i in st["items"] if i["date"] >= today]
    if len(keep) != len(st["items"]):
        st["items"] = keep
        state.save(st)
