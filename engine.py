"""
Shared trading engine. The SAME functions are used by the backtester and the
live scanner, so backtest results describe what the alerts will actually do.

Rules (all evaluated on CLOSED bars only):
  SIGNAL  : confirmed D + confirmation candle (+ RSI/MACD divergence vs B)
            and the trigger happened within FRESH_BARS of the latest bar.
  PLAN    : stop beyond X (or beyond D for extension patterns) + ATR buffer;
            targets are projected from D (T1/T2 = 0.382/0.618 of C->D, T3 = A).
  GATES   : stop must be on the correct side; price must not have already
            touched the stop or T1 since D; R:R to T2 from the real entry
            must be >= MIN_RR_T2; stop distance within sane bounds.
  ENTRY   : OPEN of the bar after the signal bar (what you can actually get).
  EXITS   : replayed bar by bar, stop first (conservative), gap-aware fills,
            1/3 at T1 (stop->BE), 1/3 at T2, last third trails (or T3), time stop.
"""
import numpy as np
import pandas as pd

import config
from confluence import (check_candlestick_confirmation, check_rsi_divergence,
                        check_macd_divergence, score_confluence)

OPEN_STATES = ("PENDING", "OPEN", "PARTIAL_T1", "PARTIAL_T2")


def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df['High'], df['Low'], df['Close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _side(p) -> int:
    return 1 if p.direction.value == "bullish" else -1


# --------------------------------------------------------------------------
# Signal + plan
# --------------------------------------------------------------------------
def evaluate_signal(df: pd.DataFrame, p, min_quality: float = None, require_momentum: bool = None):
    """
    df = CLOSED bars up to and including 'now' (last row). Returns
    {"signal_bar": int, "candle": dict, "rsi":..., "macd":...} or None.
    """
    min_quality = config.MIN_QUALITY_SCORE if min_quality is None else min_quality
    require_momentum = config.REQUIRE_MOMENTUM if require_momentum is None else require_momentum
    if p.D is None or p.quality_score < min_quality:
        return None
    now = len(df) - 1
    candle = check_candlestick_confirmation(df, p, max_bars_after_d=3)
    if not candle.get("confirmed"):
        return None
    rsi_c, macd_c = check_rsi_divergence(df, p), check_macd_divergence(df, p)
    if require_momentum and not (rsi_c.get("has_divergence") or macd_c.get("has_divergence")):
        return None
    signal_bar = max(p.D.confirmed_at, candle["bar_index"])
    if signal_bar > now or now - signal_bar > config.FRESH_BARS:
        return None
    return {"signal_bar": signal_bar, "candle": candle, "rsi": rsi_c, "macd": macd_c}


def build_plan(df: pd.DataFrame, p, atr: pd.Series) -> dict:
    s = _side(p)
    D, C = p.D.price, p.C.price
    cd = abs(C - D)
    t1, t2 = D + s * 0.382 * cd, D + s * 0.618 * cd
    t3 = p.A.price
    if s * (t3 - t2) <= 0:            # Cypher/Shark: A can sit below T2
        t3 = D + s * 1.0 * cd
    a = atr.iloc[len(df) - 1]
    buf = 0.0 if pd.isna(a) else float(a) * config.ATR_STOP_BUFFER
    stop_ref = min(p.X.price, D) if s == 1 else max(p.X.price, D)   # extension patterns: stop beyond D
    stop = stop_ref - s * buf
    return {"stop": float(stop), "t1": float(t1), "t2": float(t2), "t3": float(t3), "D": float(D)}


def check_plan(df: pd.DataFrame, p, plan: dict, entry_ref: float) -> tuple[bool, str]:
    """Geometry + path sanity BEFORE alerting. This is what stops 'alert after the stop hit'."""
    s = _side(p)
    stop, t1, t2 = plan["stop"], plan["t1"], plan["t2"]
    risk = s * (entry_ref - stop)
    if risk <= 0:
        return False, "stop is not on the loss side of entry"
    stop_pct = risk / entry_ref * 100
    if stop_pct < config.MIN_STOP_PCT:
        return False, f"stop too tight ({stop_pct:.2f}%) - costs would eat the R"
    if stop_pct > config.MAX_STOP_PCT:
        return False, f"stop too wide ({stop_pct:.1f}%)"
    if s * (t1 - entry_ref) <= 0:
        return False, "price already beyond T1"
    rr = s * (t2 - entry_ref) / risk
    if rr < config.MIN_RR_T2:
        return False, f"R:R to T2 only {rr:.2f} from current price"
    # path check: since D, has price already breached the stop or reached T1?
    seg = df.iloc[p.D.index + 1:]
    if len(seg):
        if s == 1 and (seg['Low'].min() <= stop or seg['High'].max() >= t1):
            return False, "price already hit stop or T1 since D"
        if s == -1 and (seg['High'].max() >= stop or seg['Low'].min() <= t1):
            return False, "price already hit stop or T1 since D"
    return True, f"ok (R:R to T2 {rr:.2f}, stop {stop_pct:.2f}%)"


def max_chase_price(plan: dict, s: int) -> float:
    """Worst entry price that still gives MIN_RR_T2 to T2 -- printed in the alert as 'do not chase past'."""
    stop, t2, rr = plan["stop"], plan["t2"], config.MIN_RR_T2
    # s*(t2-e) = rr * s*(e-stop)  ->  e = (t2 + rr*stop)/(1+rr)
    return (t2 + rr * stop) / (1 + rr)


def new_position(p, plan: dict, market: str, ticker: str, timeframe: str, signal_ts, setup_id: str,
                 conf_summary: dict = None) -> dict:
    s = _side(p)
    return {
        "id": setup_id, "market": market, "ticker": ticker, "timeframe": timeframe,
        "pattern": p.name, "direction": p.direction.value, "quality": p.quality_score,
        "status": "PENDING", "signal_ts": str(signal_ts), "last_bar": str(signal_ts),
        "entry": None, "stop": plan["stop"], "orig_stop": plan["stop"],
        "t1": plan["t1"], "t2": plan["t2"], "t3": plan["t3"], "fraction_remaining": 1.0,
        "realized_r": 0.0, "bars_held": 0, "trailing": False,
        "bars_to_t1": None, "bars_to_t2": None, "r_multiple": None, "exit_price": None,
        "max_chase": max_chase_price(plan, s),
        "points": {k: ({"index": int(v.index), "timestamp": str(v.timestamp), "price": float(v.price), "kind": v.kind}
                       if v is not None else None)
                   for k, v in (("X", p.X), ("A", p.A), ("B", p.B), ("C", p.C), ("D", p.D))},
        "confluence": conf_summary or {},
    }


# --------------------------------------------------------------------------
# Bar-by-bar position management (used live AND in backtests)
# --------------------------------------------------------------------------
def advance_position(pos: dict, df: pd.DataFrame, atr: pd.Series = None) -> list[dict]:
    """
    Replays every CLOSED bar after pos['last_bar'] in order. Safe to call any
    number of times (idempotent) and handles multiple transitions in one call,
    so a delayed or skipped scheduler run cannot hide a stop or a target.
    Returns the list of events produced (ENTERED, T1, T2, T3, STOP, BE_STOP,
    TRAIL_STOP, TIME_STOP, INVALIDATED).
    """
    events = []
    if pos["status"] not in OPEN_STATES:
        return events
    s = 1 if pos["direction"] == "bullish" else -1
    last = pd.Timestamp(pos["last_bar"])
    if df.index.tz is not None and last.tzinfo is None:
        last = last.tz_localize(df.index.tz)
    new = df[df.index > last]
    if new.empty:
        return events
    if atr is None:
        atr = atr_series(df)
    use_trail = getattr(config, "USE_TRAILING_STOP_AFTER_T2", False)
    mult = getattr(config, "TRAILING_ATR_MULT", 1.5)

    def ev(kind, ts, price, note=""):
        events.append({"type": kind, "bar": str(ts), "price": float(price), "note": note})

    def risk0():
        return abs(pos["entry"] - pos["orig_stop"])

    def r_of(price):
        return s * (price - pos["entry"]) / risk0()

    def close_out(kind, status, ts, price):
        pos["realized_r"] += pos["fraction_remaining"] * r_of(price)
        pos["fraction_remaining"] = 0.0
        cost_r = config.COST_PCT.get(pos["market"], 0.1) / 100.0 * pos["entry"] / risk0()
        pos["r_multiple"] = pos["realized_r"] - cost_r
        pos["exit_price"] = float(price)
        pos["status"] = status
        pos["closed_at"] = str(ts)
        ev(kind, ts, price)

    for ts, row in new.iterrows():
        o, h, l, c = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
        pos["last_bar"] = str(ts)

        if pos["status"] == "PENDING":
            slip = o * config.ENTRY_SLIPPAGE_PCT / 100.0 if hasattr(config, "ENTRY_SLIPPAGE_PCT") else 0.0
            entry = o + s * slip
            risk = s * (entry - pos["stop"])
            rr = s * (pos["t2"] - entry) / risk if risk > 0 else -1
            if risk <= 0 or s * (pos["t1"] - entry) <= 0 or rr < config.MIN_RR_T2 * 0.75:
                pos["status"] = "CLOSED_INVALIDATED"
                pos["closed_at"] = str(ts)
                ev("INVALIDATED", ts, o, f"next bar opened at {o:.5f} - gapped past the plan (R:R {rr:.2f}); do not enter")
                return events
            pos["entry"], pos["status"], pos["opened_at"] = float(entry), "OPEN", str(ts)
            ev("ENTERED", ts, entry, "assumed fill at next bar open")

        pos["bars_held"] += 1
        stop = pos["stop"]

        # 1) stop first (conservative); gap-through fills at the open, not the stop
        if (l <= stop) if s == 1 else (h >= stop):
            fill = min(stop, o) if s == 1 else max(stop, o)
            if pos["status"] == "OPEN":
                close_out("STOP", "CLOSED_STOP", ts, fill)
            elif pos["status"] == "PARTIAL_T1":
                close_out("BE_STOP", "CLOSED_BE", ts, fill)
            else:
                close_out("TRAIL_STOP" if pos["trailing"] else "BE_STOP", "CLOSED_TRAILING", ts, fill)
            return events

        # 2) targets (limit orders: gap in your favour fills at the open)
        def reached(level):
            return (h >= level) if s == 1 else (l <= level)

        def tfill(level):
            return max(level, o) if s == 1 else min(level, o)

        if pos["status"] == "OPEN" and reached(pos["t1"]):
            px = tfill(pos["t1"])
            pos["realized_r"] += (1 / 3) * r_of(px)
            pos["fraction_remaining"] = 2 / 3
            pos["status"], pos["stop"], pos["bars_to_t1"] = "PARTIAL_T1", pos["entry"], pos["bars_held"]
            ev("T1", ts, px, "close 1/3, stop to breakeven")
        if pos["status"] == "PARTIAL_T1" and reached(pos["t2"]):
            px = tfill(pos["t2"])
            pos["realized_r"] += (1 / 3) * r_of(px)
            pos["fraction_remaining"] = 1 / 3
            pos["status"], pos["bars_to_t2"] = "PARTIAL_T2", pos["bars_held"]
            ev("T2", ts, px, "close another 1/3")
        if pos["status"] == "PARTIAL_T2":
            if use_trail:
                a = atr.get(ts, np.nan) if hasattr(atr, "get") else np.nan
                if not pd.isna(a):
                    cand = c - s * float(a) * mult
                    new_stop = max(pos["stop"], cand) if s == 1 else min(pos["stop"], cand)
                    if new_stop != pos["stop"]:
                        pos["stop"] = float(new_stop)
                        pos["trailing"] = True
            elif reached(pos["t3"]):
                close_out("T3", "CLOSED_T3", ts, tfill(pos["t3"]))
                return events

        # 3) time stop
        if pos["bars_held"] >= config.MAX_HOLD_BARS:
            close_out("TIME_STOP", "CLOSED_TIME", ts, c)
            return events
    return events
