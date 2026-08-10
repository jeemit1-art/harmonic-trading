"""
Trade state manager. This is what turns "a pattern exists" into a clear,
actionable "ENTER NOW" or "EXIT NOW" -- the scanner alone can only tell you
a pattern matched; this module tracks each setup through its lifecycle and
decides when action is actually required, across scan runs.

Lifecycle per setup:

  WATCHING            -> pattern forming, price approaching PRZ (heads-up only)
  AWAITING_CONFIRMATION -> D has printed / price is in the PRZ, but no
                           candlestick confirmation yet (do NOT enter)
  OPEN                -> candlestick confirmation + momentum confluence
                           landed -> ENTER NOW alert fired, position tracked
  PARTIAL_T1 / PARTIAL_T2 -> first/second target hit, stop moved to
                           breakeven, remaining size tracked
  CLOSED_T3 / CLOSED_STOP / CLOSED_INVALIDATED -> fully closed

State persists in trade_state.json between scanner runs so it survives
cron restarts.
"""
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

import config

STATE_FILE = os.path.join(os.path.dirname(__file__), "trade_state.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def make_setup_id(market, ticker, timeframe, pattern_name, x_index) -> str:
    """Stable ID for a specific X-A-B-C-D structure so we don't double-track it."""
    return f"{market}:{ticker}:{timeframe}:{pattern_name}:{x_index}"


def update_setup(state: dict, setup_id: str, market: str, ticker: str, timeframe: str,
                  pattern, confluence: dict, current_price: float,
                  entry: float, stop: float, t1: float, t2: float, t3: float,
                  atr: float = None) -> dict:
    """
    Advance (or create) a setup's state based on the latest scan data.
    Returns a dict describing what action, if any, should be alerted:
        {"action": "ENTER_NOW" | "EXIT_PARTIAL_T1" | "EXIT_PARTIAL_T2" |
                    "EXIT_FULL_T3" | "EXIT_STOP" | "WATCHING" | "AWAITING" | None, ...}

    atr: current ATR(14) value, used for the trailing stop after T2 (see
    config.USE_TRAILING_STOP_AFTER_T2). If not supplied, the fixed T3
    (point A) exit is used instead -- trailing is an enhancement, not a
    requirement.
    """
    existing = state.get(setup_id)
    direction = pattern.direction.value
    bullish = direction == "bullish"

    if existing is None:
        # brand new setup
        if confluence.get("entry_ready"):
            state[setup_id] = {
                "market": market, "ticker": ticker, "timeframe": timeframe,
                "pattern": pattern.name, "direction": direction,
                "status": "OPEN", "fraction_remaining": 1.0,
                "entry": entry, "stop": stop, "original_stop": stop,
                "t1": t1, "t2": t2, "t3": t3,
                "opened_at": _now(), "last_update": _now(),
            }
            return {"action": "ENTER_NOW", "setup": state[setup_id]}
        elif pattern.D is not None:
            state[setup_id] = {
                "market": market, "ticker": ticker, "timeframe": timeframe,
                "pattern": pattern.name, "direction": direction,
                "status": "AWAITING_CONFIRMATION", "fraction_remaining": 1.0,
                "entry": entry, "stop": stop, "t1": t1, "t2": t2, "t3": t3,
                "opened_at": _now(), "last_update": _now(),
            }
            return {"action": "AWAITING", "setup": state[setup_id]}
        else:
            state[setup_id] = {
                "market": market, "ticker": ticker, "timeframe": timeframe,
                "pattern": pattern.name, "direction": direction,
                "status": "WATCHING", "fraction_remaining": 1.0,
                "entry": entry, "stop": stop, "t1": t1, "t2": t2, "t3": t3,
                "opened_at": _now(), "last_update": _now(),
            }
            return {"action": "WATCHING", "setup": state[setup_id]}

    # existing setup -- advance its state
    status = existing["status"]
    existing["last_update"] = _now()

    if status == "AWAITING_CONFIRMATION":
        if confluence.get("entry_ready"):
            existing["status"] = "OPEN"
            existing["fraction_remaining"] = 1.0
            return {"action": "ENTER_NOW", "setup": existing}
        # invalidate if price has closed back through X (pattern failed) --
        # caller passes current_price already
        x_broken = (current_price < existing["stop"]) if bullish else (current_price > existing["stop"])
        if x_broken:
            existing["status"] = "CLOSED_INVALIDATED"
            return {"action": "SETUP_INVALIDATED", "setup": existing}
        return {"action": None, "setup": existing}  # still waiting, no new alert

    if status in ("OPEN", "PARTIAL_T1", "PARTIAL_T2"):
        use_trailing = getattr(config, "USE_TRAILING_STOP_AFTER_T2", False) and atr is not None

        # once past T2, trail the stop behind price instead of waiting for a
        # fixed T3 -- lets a strong move run further while still locking in
        # gains progressively. Only ever tightens, never loosens.
        if status == "PARTIAL_T2" and use_trailing:
            trail_mult = getattr(config, "TRAILING_ATR_MULT", 1.5)
            candidate = (current_price - atr * trail_mult) if bullish else (current_price + atr * trail_mult)
            if bullish:
                existing["stop"] = max(existing["stop"], candidate)
            else:
                existing["stop"] = min(existing["stop"], candidate)
            existing["trailing"] = True

        stop = existing["stop"]
        t1, t2, t3 = existing["t1"], existing["t2"], existing["t3"]

        hit_stop = (current_price <= stop) if bullish else (current_price >= stop)
        if hit_stop:
            existing["status"] = "CLOSED_STOP" if status != "PARTIAL_T2" or not use_trailing else "CLOSED_TRAILING"
            existing["fraction_remaining"] = 0.0
            action = "EXIT_TRAILING_STOP" if (status == "PARTIAL_T2" and use_trailing) else "EXIT_STOP"
            return {"action": action, "setup": existing}

        if status == "OPEN":
            hit_t1 = (current_price >= t1) if bullish else (current_price <= t1)
            if hit_t1:
                existing["status"] = "PARTIAL_T1"
                existing["fraction_remaining"] = 0.667
                existing["stop"] = existing["entry"]  # move to breakeven
                return {"action": "EXIT_PARTIAL_T1", "setup": existing}

        if status == "PARTIAL_T1":
            hit_t2 = (current_price >= t2) if bullish else (current_price <= t2)
            if hit_t2:
                existing["status"] = "PARTIAL_T2"
                existing["fraction_remaining"] = 0.333
                if use_trailing:
                    trail_mult = getattr(config, "TRAILING_ATR_MULT", 1.5)
                    candidate = (current_price - atr * trail_mult) if bullish else (current_price + atr * trail_mult)
                    existing["stop"] = max(existing["stop"], candidate) if bullish else min(existing["stop"], candidate)
                    existing["trailing"] = True
                return {"action": "EXIT_PARTIAL_T2", "setup": existing}

        if status == "PARTIAL_T2" and not use_trailing:
            hit_t3 = (current_price >= t3) if bullish else (current_price <= t3)
            if hit_t3:
                existing["status"] = "CLOSED_T3"
                existing["fraction_remaining"] = 0.0
                return {"action": "EXIT_FULL_T3", "setup": existing}

        return {"action": None, "setup": existing}  # open, nothing new to report

    return {"action": None, "setup": existing}  # already closed, nothing to do


def prune_closed(state: dict, keep_recent: int = 200):
    """Drop old closed setups so the state file doesn't grow forever."""
    closed = {k: v for k, v in state.items() if v["status"].startswith("CLOSED")}
    active = {k: v for k, v in state.items() if not v["status"].startswith("CLOSED")}
    if len(closed) > keep_recent:
        sorted_closed = sorted(closed.items(), key=lambda kv: kv[1].get("last_update", ""), reverse=True)
        closed = dict(sorted_closed[:keep_recent])
    return {**active, **closed}
