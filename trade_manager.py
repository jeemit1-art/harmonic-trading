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
                           landed -> ENTER NOW alert fired, a simulated
                           position is opened and sized (see below)
  PARTIAL_T1 / PARTIAL_T2 -> first/second target hit, stop moved to
                           breakeven, remaining size tracked
  CLOSED_T3 / CLOSED_STOP / CLOSED_INVALIDATED -> fully closed

Paper trading, not live execution: there is no broker/exchange integration
anywhere in this project. When a setup goes OPEN, this module sizes a
SIMULATED position (config.RISK_PER_TRADE_PCT of the paper_account.py
equity) and settles real P&L against that account as each leg of the
scaled exit closes, using the exact entry/stop/target levels the alert
sent -- no order is ever placed anywhere. Every setup also keeps an
"events" log (what happened and why) that the dashboard renders directly.

State persists in trade_state.json between scanner runs so it survives
cron restarts.
"""
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

import config
import paper_account as pa

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


def make_setup_id(market, ticker, timeframe, pattern_name, x_identifier) -> str:
    """
    Stable ID for a specific X-A-B-C-D structure so we don't double-track it.
    x_identifier should be the X pivot's TIMESTAMP (not its positional array
    index) -- the scan window slides forward every run, so a positional
    index for the same real-world pivot drifts between scans, while its
    actual calendar timestamp doesn't.
    """
    return f"{market}:{ticker}:{timeframe}:{pattern_name}:{x_identifier}"


def _log(setup: dict, event: str, price: float = None, pnl: float = None, note: str = ""):
    setup.setdefault("events", []).append({
        "ts": _now(), "event": event,
        "price": round(price, 5) if price is not None else None,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "note": note,
    })


def _open_position(setup: dict, account: dict):
    """
    Size a simulated position for a setup that just went OPEN: risk
    config.RISK_PER_TRADE_PCT of the current paper account equity, sized
    to the entry/stop distance. Stored on the setup so every later partial
    exit and the dashboard's mark-to-market can use it.
    """
    risk_pct = getattr(config, "RISK_PER_TRADE_PCT", 1.0)
    equity = pa.get_equity(account)
    risk_amount = equity * (risk_pct / 100.0)
    risk_per_unit = abs(setup["entry"] - setup["stop"])
    units = (risk_amount / risk_per_unit) if risk_per_unit > 0 else 0.0

    setup["units"] = units
    setup["risk_amount"] = risk_amount
    setup["equity_at_entry"] = equity
    setup["realized_pnl"] = 0.0
    direction_word = "LONG" if setup["direction"] == "bullish" else "SHORT"
    _log(setup, "OPEN", price=setup["entry"],
         note=f"Entered {direction_word} -- {units:.4f} units at {setup['entry']:.5f}, "
              f"risking ${risk_amount:.2f} ({risk_pct}% of ${equity:.2f} paper equity).")


def _settle_leg(setup: dict, account: dict, fraction: float, exit_price: float,
                 event: str, note: str):
    """Realize P&L for one leg of a scaled exit and post it to the paper account."""
    sign = 1 if setup["direction"] == "bullish" else -1
    units = setup.get("units", 0.0)
    pnl = units * fraction * (exit_price - setup["entry"]) * sign
    setup["realized_pnl"] = setup.get("realized_pnl", 0.0) + pnl
    pa.apply_realized_pnl(account, pnl,
                           note=f"{setup['ticker']} {setup['pattern']} -- {event}")
    _log(setup, event, price=exit_price, pnl=pnl, note=note)


def mark_to_market(setup: dict, current_price: float) -> dict:
    """
    Unrealized P&L on whatever fraction of the position is still open,
    plus total P&L (realized + unrealized) and the trade's live R-multiple.
    Returns zeros for a setup that never became a real position (WATCHING /
    AWAITING_CONFIRMATION / invalidated-before-entry).
    """
    units = setup.get("units")
    if units is None:
        return {"unrealized_pnl": 0.0, "realized_pnl": setup.get("realized_pnl", 0.0),
                "total_pnl": setup.get("realized_pnl", 0.0), "r_multiple": None}
    sign = 1 if setup["direction"] == "bullish" else -1
    remaining = setup.get("fraction_remaining", 1.0)
    unrealized = units * remaining * (current_price - setup["entry"]) * sign
    realized = setup.get("realized_pnl", 0.0)
    total = realized + unrealized
    risk_amount = setup.get("risk_amount")
    r_multiple = (total / risk_amount) if risk_amount else None
    return {"unrealized_pnl": unrealized, "realized_pnl": realized,
            "total_pnl": total, "r_multiple": r_multiple}


def update_setup(state: dict, setup_id: str, market: str, ticker: str, timeframe: str,
                  pattern, confluence: dict, current_price: float,
                  entry: float, stop: float, t1: float, t2: float, t3: float,
                  account: dict, atr: float = None, bar_high: float = None,
                  bar_low: float = None) -> dict:
    """
    Advance (or create) a setup's state based on the latest scan data.
    Returns a dict describing what action, if any, should be alerted:
        {"action": "ENTER_NOW" | "EXIT_PARTIAL_T1" | "EXIT_PARTIAL_T2" |
                    "EXIT_FULL_T3" | "EXIT_STOP" | "WATCHING" | "AWAITING" | None, ...}

    account: the paper trading account (paper_account.py) to size the
    position against and settle realized P&L into. Mutated in place --
    caller is responsible for loading/saving it, same as `state`.

    atr: current ATR(14) value, used for the trailing stop after T2 (see
    config.USE_TRAILING_STOP_AFTER_T2). If not supplied, the fixed T3
    (point A) exit is used instead -- trailing is an enhancement, not a
    requirement.

    bar_high/bar_low: the current bar's intraday High/Low. Stop and target
    hits are checked against THESE, not current_price (which is the
    close) -- a real stop or limit order executes on an intrabar touch,
    not just the closing price. If not supplied, falls back to
    current_price for both (less accurate -- can miss a stop that was
    breached and recovered within the same bar).
    """
    existing = state.get(setup_id)
    direction = pattern.direction.value
    bullish = direction == "bullish"
    check_high = bar_high if bar_high is not None else current_price
    check_low = bar_low if bar_low is not None else current_price

    def _pt(p):
        if p is None:
            return None
        ts = p.timestamp.isoformat() if hasattr(p.timestamp, "isoformat") else str(p.timestamp)
        return {"index": p.index, "timestamp": ts, "price": p.price, "kind": p.kind}

    pattern_points = {"X": _pt(pattern.X), "A": _pt(pattern.A), "B": _pt(pattern.B),
                       "C": _pt(pattern.C), "D": _pt(pattern.D)}

    if existing is None:
        # brand new setup
        if confluence.get("entry_ready"):
            new_setup = {
                "market": market, "ticker": ticker, "timeframe": timeframe,
                "pattern": pattern.name, "direction": direction,
                "status": "OPEN", "fraction_remaining": 1.0,
                "entry": entry, "stop": stop, "original_stop": stop,
                "t1": t1, "t2": t2, "t3": t3, "points": pattern_points,
                "opened_at": _now(), "last_update": _now(),
            }
            state[setup_id] = new_setup
            _open_position(new_setup, account)
            return {"action": "ENTER_NOW", "setup": new_setup}
        elif pattern.D is not None:
            new_setup = {
                "market": market, "ticker": ticker, "timeframe": timeframe,
                "pattern": pattern.name, "direction": direction,
                "status": "AWAITING_CONFIRMATION", "fraction_remaining": 1.0,
                "entry": entry, "stop": stop, "t1": t1, "t2": t2, "t3": t3, "points": pattern_points,
                "opened_at": _now(), "last_update": _now(),
            }
            _log(new_setup, "AWAITING_CONFIRMATION", price=entry,
                 note="D printed, price is in the PRZ -- waiting on a confirmation candle "
                      "and momentum confluence before this is a real signal. No position taken.")
            state[setup_id] = new_setup
            return {"action": "AWAITING", "setup": new_setup}
        else:
            new_setup = {
                "market": market, "ticker": ticker, "timeframe": timeframe,
                "pattern": pattern.name, "direction": direction,
                "status": "WATCHING", "fraction_remaining": 1.0,
                "entry": entry, "stop": stop, "t1": t1, "t2": t2, "t3": t3, "points": pattern_points,
                "opened_at": _now(), "last_update": _now(),
            }
            _log(new_setup, "WATCHING", price=entry,
                 note="Pattern forming, price approaching the projected PRZ. Heads-up only.")
            state[setup_id] = new_setup
            return {"action": "WATCHING", "setup": new_setup}

    # existing setup -- advance its state
    status = existing["status"]
    existing["last_update"] = _now()

    if status == "AWAITING_CONFIRMATION":
        if confluence.get("entry_ready"):
            existing["status"] = "OPEN"
            existing["fraction_remaining"] = 1.0
            existing.setdefault("points", pattern_points)  # backfill for older setups
            _open_position(existing, account)
            return {"action": "ENTER_NOW", "setup": existing}
        # invalidate if price has closed back through X (pattern failed) --
        # caller passes current_price already
        x_broken = (current_price < existing["stop"]) if bullish else (current_price > existing["stop"])
        if x_broken:
            existing["status"] = "CLOSED_INVALIDATED"
            _log(existing, "INVALIDATED", price=current_price,
                 note="Price traded through point X before a confirmation candle appeared. "
                      "Pattern failed -- no position was ever taken.")
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

        # stop-hit check uses the bar's intrabar extreme (Low for a long,
        # High for a short) -- a real stop order fires on any touch, not
        # just where price happened to close
        hit_stop = (check_low <= stop) if bullish else (check_high >= stop)
        if hit_stop:
            remaining_fraction = existing.get("fraction_remaining", 1.0)
            is_trailing_exit = (status == "PARTIAL_T2" and use_trailing)
            existing["status"] = "CLOSED_TRAILING" if is_trailing_exit else "CLOSED_STOP"
            existing["exit_price"] = stop  # the stop level itself, not current_price -- that's what actually would have filled
            action = "EXIT_TRAILING_STOP" if is_trailing_exit else "EXIT_STOP"
            if is_trailing_exit:
                note = (f"Trailing stop hit after T1+T2 -- final {remaining_fraction:.0%} closed at "
                        f"{stop:.5f}, locking in the move beyond Target 2.")
            elif status == "OPEN":
                note = f"Stop hit before Target 1 -- full position closed at {stop:.5f}. Pattern failed."
            else:
                note = (f"Stop (moved to breakeven after T1) hit -- remaining {remaining_fraction:.0%} "
                        f"closed near breakeven at {stop:.5f}.")
            _settle_leg(existing, account, remaining_fraction, stop, action, note)
            existing["fraction_remaining"] = 0.0
            return {"action": action, "setup": existing}

        # target-hit checks similarly use the favourable intrabar extreme
        if status == "OPEN":
            hit_t1 = (check_high >= t1) if bullish else (check_low <= t1)
            if hit_t1:
                existing["status"] = "PARTIAL_T1"
                existing["hit_t1"] = True
                existing["stop"] = existing["entry"]  # move to breakeven
                _settle_leg(existing, account, 1 / 3, t1, "EXIT_PARTIAL_T1",
                            f"Target 1 hit at {t1:.5f} -- closed 1/3 of the position, "
                            f"stop moved to breakeven ({existing['entry']:.5f}).")
                existing["fraction_remaining"] = 0.667
                return {"action": "EXIT_PARTIAL_T1", "setup": existing}

        if status == "PARTIAL_T1":
            hit_t2 = (check_high >= t2) if bullish else (check_low <= t2)
            if hit_t2:
                existing["status"] = "PARTIAL_T2"
                existing["hit_t2"] = True
                if use_trailing:
                    trail_mult = getattr(config, "TRAILING_ATR_MULT", 1.5)
                    candidate = (current_price - atr * trail_mult) if bullish else (current_price + atr * trail_mult)
                    existing["stop"] = max(existing["stop"], candidate) if bullish else min(existing["stop"], candidate)
                    existing["trailing"] = True
                note = (f"Target 2 hit at {t2:.5f} -- closed another 1/3. "
                        + ("Stop now trailing behind price for the final third."
                           if use_trailing else f"Stop remains at breakeven for the final third."))
                _settle_leg(existing, account, 1 / 3, t2, "EXIT_PARTIAL_T2", note)
                existing["fraction_remaining"] = 0.333
                return {"action": "EXIT_PARTIAL_T2", "setup": existing}

        if status == "PARTIAL_T2" and not use_trailing:
            hit_t3 = (check_high >= t3) if bullish else (check_low <= t3)
            if hit_t3:
                existing["status"] = "CLOSED_T3"
                existing["exit_price"] = t3  # actual fill for this leg -- used for leaderboard R
                _settle_leg(existing, account, existing.get("fraction_remaining", 0.333), t3, "EXIT_FULL_T3",
                            f"Target 3 / point A hit at {t3:.5f} -- final third closed. "
                            f"Full 3-target plan complete.")
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


def reconstruct_pattern(setup: dict):
    """
    Rebuilds a lightweight pattern-like object from a stored setup's
    "points" data, good enough to feed into dashboard.plot_chart() for
    display purposes (Open Trades tab). Returns None if the setup predates
    point-storage (older tracked setups won't have it -- backfilled
    automatically the next time they transition state).
    """
    points = setup.get("points")
    if not points:
        return None

    import pandas as pd
    from types import SimpleNamespace

    def _pivot(key):
        p = points.get(key)
        if p is None:
            return None
        return SimpleNamespace(index=p["index"], timestamp=pd.Timestamp(p["timestamp"]),
                                price=p["price"], kind=p["kind"])

    direction_value = setup["direction"]
    return SimpleNamespace(
        name=setup["pattern"],
        direction=SimpleNamespace(value=direction_value),
        X=_pivot("X"), A=_pivot("A"), B=_pivot("B"), C=_pivot("C"), D=_pivot("D"),
        ratios={},  # not stored -- leg ratio labels simply won't render, no crash
        quality_score=None,
        prz_lo=setup.get("entry"), prz_hi=setup.get("entry"),
    )
