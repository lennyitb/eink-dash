"""Settings, all from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    v = _env(name)
    return int(v) if v else default


def _float(name: str, default: float | None) -> float | None:
    v = _env(name)
    return float(v) if v else default


def _bool(name: str, default: bool) -> bool:
    v = _env(name).lower()
    return default if not v else v in ("1", "true", "yes", "on")


@dataclass
class Settings:
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo(_env("TZ", "America/New_York")))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/data")))

    # Display / Kindle
    kindle_host: str = field(default_factory=lambda: _env("KINDLE_HOST", "10.0.0.168"))
    kindle_user: str = field(default_factory=lambda: _env("KINDLE_USER", "root"))
    kindle_key: str = field(default_factory=lambda: _env("KINDLE_KEY", "/keys/kindle_dash_ed25519"))
    push_enabled: bool = field(default_factory=lambda: _bool("PUSH_ENABLED", True))
    # Landscape design is rotated onto the portrait panel. 90 = counter-clockwise,
    # 270 = clockwise. Flip this if the dashboard shows upside down.
    rotate: int = field(default_factory=lambda: _int("ROTATE", 90))
    push_interval_s: int = field(default_factory=lambda: _int("PUSH_INTERVAL_S", 60))
    night_push_interval_s: int = field(default_factory=lambda: _int("NIGHT_PUSH_INTERVAL_S", 60))
    full_refresh_min: int = field(default_factory=lambda: _int("FULL_REFRESH_MIN", 15))

    # Frontlight 0-24, day vs. night
    day_brightness: int = field(default_factory=lambda: _int("DAY_BRIGHTNESS", 9))
    night_brightness: int = field(default_factory=lambda: _int("NIGHT_BRIGHTNESS", 0))
    night_start: str = field(default_factory=lambda: _env("NIGHT_START", "22:30"))
    night_end: str = field(default_factory=lambda: _env("NIGHT_END", "06:30"))

    # Content
    calendar_ics_urls: list[str] = field(
        default_factory=lambda: [u for u in _env("CALENDAR_ICS_URLS").split() if u]
    )
    agenda_days: int = field(default_factory=lambda: _int("AGENDA_DAYS", 10))
    weather_lat: float | None = field(default_factory=lambda: _float("WEATHER_LAT", None))
    weather_lon: float | None = field(default_factory=lambda: _float("WEATHER_LON", None))
    weather_units: str = field(default_factory=lambda: _env("WEATHER_UNITS", "fahrenheit"))
    # Birthdays from iCloud Contacts (CardDAV). App-specific password from account.apple.com.
    icloud_username: str = field(default_factory=lambda: _env("ICLOUD_USERNAME"))
    icloud_app_password: str = field(default_factory=lambda: _env("ICLOUD_APP_PASSWORD"))
    birthday_first_names: bool = field(default_factory=lambda: _bool("BIRTHDAY_FIRST_NAMES", False))
    birthday_show_age: bool = field(default_factory=lambda: _bool("BIRTHDAY_SHOW_AGE", True))
    clock_24h: bool = field(default_factory=lambda: _bool("CLOCK_24H", False))

    # API_TOKEN guards the REST API. The MCP endpoint (/mcp) uses single-user OAuth when
    # PUBLIC_BASE_URL is set; MCP_NO_AUTH=true exposes it without auth (local dev only).
    api_token: str = field(default_factory=lambda: _env("API_TOKEN"))
    mcp_no_auth: bool = field(default_factory=lambda: _bool("MCP_NO_AUTH", False))


settings = Settings()
