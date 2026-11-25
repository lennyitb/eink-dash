"""HTML -> screenshot (Playwright/Chromium) -> rotated 16-level grayscale PNG."""
from __future__ import annotations

import asyncio
import io
import os
import logging
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from playwright.async_api import Browser, async_playwright

from . import sources, state
from .config import settings

log = logging.getLogger(__name__)

W, H = 1448, 1072  # landscape design size; panel is 1072x1448 portrait
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html"]))

# 16 evenly spaced gray levels, matching the panel
_PALETTE = Image.new("P", (1, 1))
_PALETTE.putpalette([v for i in range(16) for v in (i * 17,) * 3] + [0] * (256 - 16) * 3)


def _fmt_time(hhmm: str | None) -> str:
    if not hhmm:
        return "—"
    h, m = map(int, hhmm.split(":"))
    if settings.clock_24h:
        return f"{h:02d}:{m:02d}"
    return f"{(h % 12) or 12}:{m:02d}"


def _day_label(d: date, today: date) -> str:
    if d == today:
        return "TODAY"
    return f"{d.strftime('%a').upper()} {d.day}"


def build_context() -> dict:
    now = state.now()
    today = now.date()
    groups: dict[str, list[dict]] = {}
    for i in sources.agenda():
        groups.setdefault(i["date"], []).append({**i, "time_label": "DUE" if i["kind"] == "due" and not i["time"] else _fmt_time(i["time"])})
    days = [{"label": _day_label(date.fromisoformat(k), today), "rows": v} for k, v in groups.items()]
    clock = now.strftime("%H:%M") if settings.clock_24h else f"{(now.hour % 12) or 12}:{now.minute:02d}"
    return {"now": now, "clock": clock, "weather": sources.weather(),
            "bulletin": state.active_bulletin(), "days": days}


def render_html() -> str:
    return _env.get_template("dash.html").render(**build_context())


def to_panel(png: bytes) -> Image.Image:
    """Screenshot -> grayscale, rotate to portrait, Floyd-Steinberg to 16 grays."""
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    im = im.rotate(settings.rotate, expand=True)
    im = im.quantize(palette=_PALETTE, dither=Image.Dither.FLOYDSTEINBERG)
    return im.convert("L")


class Renderer:
    def __init__(self) -> None:
        self._pw = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        exe = os.environ.get("CHROMIUM_PATH") or None
        self._browser = await self._pw.chromium.launch(executable_path=exe, args=["--no-sandbox", "--disable-dev-shm-usage"])

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def screenshot(self, html: str) -> bytes:
        async with self._lock:
            if not self._browser or not self._browser.is_connected():
                await self.start()
            page = await self._browser.new_page(viewport={"width": W, "height": H})
            try:
                await page.set_content(html, wait_until="load")
                await page.evaluate("document.fonts.ready")
                await page.wait_for_selector("body[data-ready='1']", timeout=5000)
                return await page.screenshot(type="png")
            finally:
                await page.close()

    async def render(self) -> tuple[Image.Image, bytes]:
        html = await asyncio.to_thread(render_html)  # fetches may block
        shot = await self.screenshot(html)
        return to_panel(shot), shot
