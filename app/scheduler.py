"""The render/push loop."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, time

from . import push, sources, state
from .config import settings
from .render import Renderer

log = logging.getLogger(__name__)


def _hm(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def is_night(now: datetime | None = None) -> bool:
    t = (now or state.now()).time()
    start, end = _hm(settings.night_start), _hm(settings.night_end)
    return (t >= start or t < end) if start > end else (start <= t < end)


class Scheduler:
    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.wake = asyncio.Event()
        self.force_full = False
        self.brightness_override: int | None = None
        self.last_full: datetime | None = None
        self.last_hash: str | None = None
        self.status: dict = {"last_render": None, "last_push": None, "last_error": None}

    @property
    def latest_png(self):
        return settings.data_dir / "latest.png"

    def brightness(self) -> int:
        if self.brightness_override is not None:
            return self.brightness_override
        return settings.night_brightness if is_night() else settings.day_brightness

    def refresh(self, full: bool = False) -> None:
        self.force_full = self.force_full or full
        self.wake.set()

    async def tick(self) -> None:
        sources.prune_past_items()
        img, shot = await self.renderer.render()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        img.save(self.latest_png, optimize=True)
        (settings.data_dir / "latest-landscape.png").write_bytes(shot)
        now = state.now()
        self.status["last_render"] = now.isoformat()
        digest = hashlib.sha1(img.tobytes()).hexdigest()
        full = (self.force_full or self.last_full is None or
                (now - self.last_full).total_seconds() >= settings.full_refresh_min * 60)
        if not settings.push_enabled:
            return
        if digest == self.last_hash and not full:
            return
        await push.push(self.latest_png, self.brightness(), full)
        self.last_hash = digest
        self.force_full = False
        if full:
            self.last_full = now
        self.status["last_push"] = now.isoformat()
        self.status["last_error"] = None

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:
                log.exception("tick failed")
                self.status["last_error"] = f"{state.now():%H:%M} {e}"
            interval = settings.night_push_interval_s if is_night() else settings.push_interval_s
            # sleep until just after the next interval boundary so the clock flips on time
            now = state.now()
            secs = interval - (now.timestamp() % interval) + 1
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), secs)
            except asyncio.TimeoutError:
                pass
