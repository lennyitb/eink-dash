"""Push a PNG to the Kindle over SSH and re-assert frontlight / no-screensaver."""
from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)


def _ssh_opts() -> list[str]:
    return ["-i", settings.kindle_key,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={settings.data_dir / 'known_hosts'}",
            "-o", "ConnectTimeout=15", "-o", "BatchMode=yes"]


async def _run(*cmd: str, timeout: float = 45) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{cmd[0]} timed out")
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exit {proc.returncode}: {out.decode(errors='replace').strip()[-300:]}")


async def push(png_path: Path, brightness: int, full_refresh: bool,
               retries: int = 3) -> None:
    target = f"{settings.kindle_user}@{settings.kindle_host}"
    # -f flashes the whole panel (clears ghosting); otherwise a quieter update.
    flags = "-f -W GC16" if full_refresh else "-W AUTO"
    remote = (f"mv /mnt/us/dash.tmp.png /mnt/us/dash.png && "
              f"/mnt/us/fbink -q {flags} -g file=/mnt/us/dash.png; "
              f"lipc-set-prop com.lab126.powerd preventScreenSaver 1; "
              f"lipc-set-prop com.lab126.powerd flIntensity {int(brightness)}")
    delay = 5
    for attempt in range(1, retries + 1):
        try:
            await _run("scp", "-q", *_ssh_opts(), str(png_path), f"{target}:/mnt/us/dash.tmp.png")
            await _run("ssh", *_ssh_opts(), target, remote)
            return
        except Exception as e:
            log.warning("push attempt %d/%d failed: %s", attempt, retries, e)
            if attempt == retries:
                raise
            await asyncio.sleep(delay)  # Wi-Fi may be waking up
            delay *= 3


async def set_brightness(level: int) -> None:
    target = f"{settings.kindle_user}@{settings.kindle_host}"
    await _run("ssh", *_ssh_opts(), target,
               f"lipc-set-prop com.lab126.powerd flIntensity {shlex.quote(str(int(level)))}")
