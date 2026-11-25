# Bedside e-ink dashboard server

Renders the "F · Sidebar + agenda (landscape)" layout, rotates it onto the Kindle
Paperwhite 4's 1072×1448 portrait panel, dithers to 16 grays, and pushes it over SSH
(`scp` + `fbink`). Each push also re-asserts the frontlight level and
`preventScreenSaver 1`, which the Kindle forgets on reboot.

**Content**
- Sidebar: weekday, date, clock, weather from Open-Meteo (no key needed; set `WEATHER_LAT`/`WEATHER_LON`).
- Agenda: Google Calendar via private iCal URL(s), merged with items Claude pushes
  (e.g. Canvas due dates under source `canvas`). Rows that don't fit are dropped with a "+N more".
- Bulletin box: a short note Claude sets through the MCP connector. Hidden when empty.

**Schedule**: re-render every `PUSH_INTERVAL_S` (default 60 s, on the minute, so the clock
is right). Pushes only when the image changed. A flashing GC16 full refresh runs every
`FULL_REFRESH_MIN` (default 15) to clear ghosting. The frontlight stays at
`DAY_BRIGHTNESS` (default 20 of 24) by day, fades to `NIGHT_BRIGHTNESS` (default 1) over
`DIM_RAMP_MIN` (60) starting at `NIGHT_START` (22:00), and fades back up over `WAKE_RAMP_MIN`
(30) starting at `NIGHT_END` (07:00). SSH failures retry 3× with backoff
(5 s, 15 s) in case the Kindle's Wi-Fi is waking.

## Run

```sh
cp .env.example .env          # fill in calendar URL, weather lat/lon, API_TOKEN, AUTH_PASSWORD
mkdir -p key && cp /path/to/kindle_dash_ed25519 key/   # never commit this
docker compose up -d --build
```

Open `http://<host>:8080/` for a live preview of what the panel shows.

## Claude connector (MCP)

Endpoint: `https://eink.lenny.zone/mcp` (streamable HTTP). Add it in claude.ai under
Settings › Connectors › Add custom connector; claude.ai registers itself (OAuth dynamic client
registration) and sends you to a password login page (`AUTH_PASSWORD`, the same single-user
OAuth from canvas-viewer-mcp that Lenny's other MCP servers use). Refresh tokens last 90 days.
The public reverse proxy exposes only the OAuth/MCP paths; the preview, PNGs and `/api/*`
stay LAN-only.

Without `PUBLIC_BASE_URL` the MCP endpoint is off. `MCP_NO_AUTH=true` serves it with no auth,
for local dev only.

Tools: `set_bulletin`, `clear_bulletin`, `get_dashboard`, `add_agenda_items`,
`sync_agenda_items` (replace everything from one source, e.g. `canvas`),
`remove_agenda_item` (also hides a calendar event), `refresh_display`.

## REST API (`Authorization: Bearer $API_TOKEN`)

| Method | Path | |
|---|---|---|
| POST | `/api/bulletin` | `{"message": "...", "label": "NOTE", "expires_in_hours": 12}` |
| DELETE | `/api/bulletin` | clear |
| GET | `/api/agenda` | merged agenda with ids |
| PUT | `/api/agenda/{source}` | replace a source's items: `[{"title","date","time","kind","course"}]` |
| POST | `/api/refresh?full=true` | push now |
| POST | `/api/brightness?level=4` | override frontlight; omit `level` to resume schedule |

## Dev

```sh
pip install -r requirements.txt && playwright install chromium
DATA_DIR=./data PUSH_ENABLED=false uvicorn app.main:app --reload --port 8080
```

## Deploy

A push to `main` deploys automatically. A GitHub webhook (push events) hits
`https://lenny.zone/eink-dash-webhook`, which nginx proxies to a small listener on the
homelab (`eink-dash-webhook.service`, 127.0.0.1:9119). It fast-forwards the clone in
`/opt/eink-dash` and runs `docker compose up -d --build`, then waits for `/healthz`.
`.env` and `key/` there are untracked and survive deploys. Logs:
`journalctl -u eink-dash-webhook -f`.
