"""
Paper trading account. There is no broker/exchange integration in this
project -- an ENTER_NOW alert never places a real order anywhere. What it
DOES do (via trade_manager.py) is open a simulated position sized off this
account's equity using config.RISK_PER_TRADE_PCT, and settle real P&L
against it using the exact entry/stop/target levels the alert sent. This
module is just the ledger: current equity, and a running log of every
realized P&L event so the dashboard can show an equity curve and a
account-level return, not just individual trade outcomes.

State persists in paper_account.json between scanner runs, same pattern as
trade_state.json / leaderboard.json. Delete the file to reset the account
back to config.PAPER_STARTING_EQUITY.
"""
import json
import os
from datetime import datetime, timezone

import config

ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), "paper_account.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_account() -> dict:
    if os.path.exists(ACCOUNT_FILE):
        with open(ACCOUNT_FILE) as f:
            return json.load(f)
    starting = getattr(config, "PAPER_STARTING_EQUITY", 10000.0)
    return {
        "starting_equity": starting,
        "equity": starting,
        "realized_pnl_total": 0.0,
        "n_closed_legs": 0,
        "equity_curve": [{"date": _now(), "equity": starting, "note": "Account opened"}],
        "created_at": _now(),
    }


def save_account(account: dict):
    with open(ACCOUNT_FILE, "w") as f:
        json.dump(account, f, indent=2, default=str)


def get_equity(account: dict) -> float:
    return float(account.get("equity", getattr(config, "PAPER_STARTING_EQUITY", 10000.0)))


def apply_realized_pnl(account: dict, amount: float, note: str = "") -> dict:
    """
    Settle one realized P&L event (a full close, or one leg of a scaled
    exit) against the account. Appends to the equity curve so the
    dashboard can chart it, distinct from the backtester's equity curve --
    this one reflects what actually happened across live scanner runs.
    """
    account["equity"] = float(account.get("equity", 0.0)) + amount
    account["realized_pnl_total"] = float(account.get("realized_pnl_total", 0.0)) + amount
    account["n_closed_legs"] = int(account.get("n_closed_legs", 0)) + 1
    account.setdefault("equity_curve", []).append({
        "date": _now(), "equity": round(account["equity"], 2),
        "pnl": round(amount, 2), "note": note,
    })
    return account
