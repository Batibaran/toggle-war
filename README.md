# Toggle War

A minimalist, high-stakes multiplayer tug-of-war played via a single, shared button.

The game is currently hosted and live at: [www.togglewar.com](https://www.togglewar.com/)

There are no complex mechanics or deep configuration settings for players. There is only the button, your chosen team, and the clock.

---

## The Game

The premise is straightforward: Choose your team, claim the switch, and defend your time.

Every connected player in the world looks at the exact same screen. When you click **Switch**, the color flips for everyone instantly. Your team's timer only ticks up while the screen matches your team's color.

* **Mass Interaction:** Hundreds of players potentially fighting over a single millisecond.
* **Imaginary Rivalry:** Red vs. Blue. An unscripted competitive feud born out of pure coordination and interaction.
* **The Goal:** Accumulate the highest total time, hold the longest streak, and deny the opposing team any ground.
* **Future Updates:** The game is intended to remain minimalistic, but future updates will introduce new minor features to track and display team dominance.

---

## Running Locally

### Quick Start

```bash
# 1. Setup environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Run the server
uvicorn app.main:app --reload

```

Open `http://127.0.0.1:8000` in multiple browser tabs to simulate the multiplayer interaction locally.

---

## Technical Overview

### Tech Stack

* **Backend Framework:** FastAPI (Python) for handling lightweight routing and asynchronous concurrency.
* **Real-time Sync:** WebSockets to ensure sub-millisecond state propagation across all connected clients simultaneously.
* **Database:** SQLite (`aiosqlite`) to keep a lightweight, server-side transactional record of historical data without requiring a heavy external database setup.

### Design Decisions

* **Immediate Updates vs. Background Ticks:** Switch clicks are processed instantly, triggering an immediate broadcast and a data write. Global timer syncing is decoupled into a configured background heartbeat (`STATS_TICK_SEC`) to optimize network bandwidth.
* **Wall-Clock Time Recovery:** To prevent data loss during server restarts or crashes, the backend calculates intervals using wall-clock time milestones saved to the database. When the server boots back up, it automatically recovers elapsed time based on the last recorded state.
* **Rate-Limiting & Security:** Features a custom token-bucket rate limiter and reactive bot-detection algorithms on the backend to block automated scripts and preserve fair clicking mechanics.
