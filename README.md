# Toggle War

A shared red/blue toggle synchronized over WebSockets. One **Switch** button flips state for every connected client. Timing stats (totals, longest streaks, current stint) are tracked on the server in milliseconds and persisted to SQLite.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in one or more browser tabs.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `STATS_TICK_SEC` | `0.1` | How often (seconds) the server pushes live stats to all clients |
| `PERSIST_INTERVAL_SEC` | `5` | How often (seconds) committed state is saved to SQLite |

Toggles still sync and persist **immediately** on each Switch click; these control the background timer updates and crash checkpoints.

**PowerShell example (50 ms UI tick, 2 s DB checkpoint):**

```powershell
$env:STATS_TICK_SEC = "0.05"
$env:PERSIST_INTERVAL_SEC = "2"
uvicorn app.main:app --reload
```

**bash example:**

```bash
export STATS_TICK_SEC=0.05
export PERSIST_INTERVAL_SEC=2
uvicorn app.main:app --reload
```

## Smoke test

1. Open two tabs — the color square and stats should match.
2. Click **Switch** in one tab — both tabs update together.
3. Refresh a tab — state and totals reload from `data/toggle.db`.
4. Stop the server, restart — totals should remain close (wall-clock recovery on boot; periodic saves per `PERSIST_INTERVAL_SEC`).

## Layout

- Black page background
- Red/blue square (server state) with red stats on the left, blue stats on the right
- **Switch** button below

## API

- `GET /` — static UI
- `WS /ws` — send `{"type":"toggle"}`; receive `{"type":"state", ...}` snapshots
