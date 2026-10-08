"""
Durable state. Atomic writes, one file, explicit schema:
  positions : id -> position dict (PENDING/OPEN/PARTIAL_*)       [engine.OPEN_STATES]
  closed    : list of closed positions (newest last, capped)     [drives dashboard ledger + leaderboard]
  seen      : signal id -> iso time (dedupe, pruned)
  outbox    : alerts not yet DELIVERED (retried next run -- v1 lost them on a failed send)
  alert_log : last N delivered alerts (dashboard)
  decisions : last N reasons a signal was suppressed (dashboard: "why no alert?")
  meta      : last_run / last_success / per-market status / data failures
"""
import json, os, tempfile
from datetime import datetime, timezone, timedelta

STATE_FILE = os.environ.get("STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_v2.json"))
CAPS = {"closed": 1000, "alert_log": 200, "decisions": 300}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty() -> dict:
    return {"version": 2, "positions": {}, "closed": [], "seen": {}, "outbox": [], "alert_log": [],
            "decisions": [], "meta": {"markets": {}, "data_failures": {}}}


def load(path: str = None) -> dict:
    path = path or STATE_FILE
    if not os.path.exists(path):
        return empty()
    with open(path) as f:
        s = json.load(f)
    base = empty(); base.update(s)
    return base


def save(state: dict, path: str = None):
    path = path or STATE_FILE
    for k, cap in CAPS.items():
        state[k] = state[k][-cap:]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=1, default=str)
    os.replace(tmp, path)               # atomic: a crash can never leave a half-written state file


def queue_alert(state: dict, text: str, kind: str, ticker: str = "", pos_id: str = ""):
    state["outbox"].append({"id": f"{now_iso()}|{kind}|{ticker}|{len(state['outbox'])}", "created": now_iso(),
                            "kind": kind, "ticker": ticker, "pos_id": pos_id, "text": text, "attempts": 0})


def log_decision(state: dict, market: str, ticker: str, what: str, why: str):
    state["decisions"].append({"t": now_iso(), "market": market, "ticker": ticker, "what": what, "why": why})
