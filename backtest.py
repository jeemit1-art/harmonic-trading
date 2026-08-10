"""
Backtester: walks a price history bar-by-bar, detects harmonic patterns as
they confirm, simulates the trade with standard harmonic trade-management
rules, and reports performance stats.

Trade rules (standard harmonic practice -- these are what the entry/SL/TP
in the live scanner also uses, so backtest and live logic match exactly):

  ENTRY : first touch of the PRZ (Potential Reversal Zone), OR on a
          confirmation candle close back inside the PRZ after tagging it
          (configurable -- confirmation entry has a lower win rate but
          fewer false-pattern losses).
  STOP  : beyond point X, with a small buffer (0.5 x ATR) -- a genuine
          harmonic pattern is invalidated if price trades through X.
  TARGETS (scaled exit, the standard "three-target" harmonic approach):
          T1 = 0.382 retracement of the CD leg  (close 33%, move stop to BE)
          T2 = 0.618 retracement of the CD leg  (close 33%)
          T3 = point A                          (close remainder, or trail)
  This scaled-exit approach is what most published harmonic track records
  use because D-point reversals frequently stall at T1/T2 rather than
  running all the way back to A.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

import config
from patterns import find_patterns, HarmonicPattern, Direction
from confluence import check_candlestick_confirmation, check_rsi_divergence, check_macd_divergence


@dataclass
class Trade:
    pattern: str
    direction: str
    entry_date: object
    entry_price: float
    stop_price: float
    t1: float
    t2: float
    t3: float
    exit_date: object = None
    exit_price: float = None
    r_multiple: float = None
    outcome: str = None          # 'T1','T2','T3','STOP','OPEN'
    quality_score: float = 0.0
    # timing -- when (bar count + calendar time) each milestone was reached,
    # relative to entry. None if that milestone was never reached.
    bars_to_t1: int = None
    bars_to_t2: int = None
    bars_to_t3: int = None
    time_to_t1: object = None    # pandas.Timedelta
    time_to_t2: object = None
    time_to_t3: object = None


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def backtest(df: pd.DataFrame, deviation_pct: float = 3.0, tolerance: float = 0.05,
             min_quality: float = 60.0, risk_per_trade_pct: float = 1.0,
             starting_equity: float = 10000.0, atr_stop_buffer: float = 0.5,
             lookback_window: int = 250, step: int = 5,
             cost_pct: float = 0.05, require_confirmation: bool = True) -> dict:
    """
    require_confirmation: if True (recommended, and the default), a trade
    is only taken if a candlestick confirmation (engulfing/hammer/shooting
    star) AND at least one momentum divergence (RSI or MACD) appear within
    3 bars after D -- exactly the same `entry_ready` gate the live scanner
    uses before firing an ENTER NOW alert. This makes backtest results a
    much more honest preview of what the live alerts will actually do,
    instead of assuming a perfect fill right at the raw PRZ touch.
    """
    """
    Walk-forward backtest: at each step, look at the trailing `lookback_window`
    bars, detect confirmed patterns whose D point falls in the most recent
    bars (i.e. "just completed"), and simulate the trade forward on unseen
    future bars. This avoids look-ahead bias (a common flaw in naive
    harmonic backtests that scan the whole series at once).
    """
    df = df.copy()
    atr = _atr(df)
    trades: list[Trade] = []
    equity = starting_equity
    equity_curve = [(df.index[0], equity)]
    seen_d_indices = set()

    n = len(df)
    for end in range(lookback_window, n, step):
        window = df.iloc[max(0, end - lookback_window):end]
        pats = find_patterns(window, deviation_pct=deviation_pct, tolerance=tolerance)
        for p in pats:
            if not p.confirmed or p.D is None:
                continue
            if p.quality_score < min_quality:
                continue
            global_d_idx = p.D.index + max(0, end - lookback_window)
            if global_d_idx in seen_d_indices:
                continue
            # only take patterns whose D point is very recent within this window
            if global_d_idx < end - step - 2 or global_d_idx >= end:
                continue
            seen_d_indices.add(global_d_idx)

            trade = _simulate_trade(df, p, global_d_idx, atr, atr_stop_buffer,
                                     require_confirmation=require_confirmation)
            if trade is None:
                continue
            # deduct transaction cost, expressed in R terms
            stop_dist_pct = abs(trade.entry_price - trade.stop_price) / trade.entry_price * 100
            if stop_dist_pct > 0:
                cost_in_r = cost_pct / stop_dist_pct
                trade.r_multiple -= cost_in_r
            trades.append(trade)

            # position sizing: risk_per_trade_pct of current equity, sized to the stop distance
            risk_amount = equity * (risk_per_trade_pct / 100.0)
            stop_dist = abs(trade.entry_price - trade.stop_price)
            if stop_dist > 0 and trade.r_multiple is not None:
                pnl = risk_amount * trade.r_multiple
                equity += pnl
                equity_curve.append((trade.exit_date, equity))

    return _summarize(trades, equity_curve, starting_equity)


def _simulate_trade(df: pd.DataFrame, p: HarmonicPattern, d_idx: int,
                     atr: pd.Series, atr_stop_buffer: float,
                     require_confirmation: bool = True) -> Trade | None:
    if d_idx + 1 >= len(df):
        return None

    bullish = p.direction == Direction.BULLISH

    entry_idx = d_idx
    entry_price = p.D.price

    if require_confirmation:
        candle_check = check_candlestick_confirmation(df, p, max_bars_after_d=3)
        if not candle_check.get("confirmed"):
            return None  # no confirmation within 3 bars -- no trade, matches live behaviour
        rsi_check = check_rsi_divergence(df, p)
        macd_check = check_macd_divergence(df, p)
        if not (rsi_check.get("has_divergence") or macd_check.get("has_divergence")):
            return None  # confirmation candle present but no momentum confluence -- skip
        # enter at the close of the confirmation candle, not the raw D touch --
        # this is the actual fillable price, matching what ENTER_NOW alerts use
        entry_idx = candle_check["bar_index"]
        entry_price = df['Close'].iloc[entry_idx]
        if entry_idx + 1 >= len(df):
            return None

    a_price = p.A.price
    cd_leg = abs(p.C.price - entry_price)
    buffer = (atr.iloc[entry_idx] if not np.isnan(atr.iloc[entry_idx]) else 0) * atr_stop_buffer

    if bullish:
        stop_price = p.X.price - buffer
        t1 = entry_price + 0.382 * cd_leg
        t2 = entry_price + 0.618 * cd_leg
        t3 = a_price
    else:
        stop_price = p.X.price + buffer
        t1 = entry_price - 0.382 * cd_leg
        t2 = entry_price - 0.618 * cd_leg
        t3 = a_price

    risk = abs(entry_price - stop_price)
    if risk == 0:
        return None

    trade = Trade(pattern=p.name, direction=p.direction.value,
                   entry_date=df.index[entry_idx], entry_price=entry_price,
                   stop_price=stop_price, t1=t1, t2=t2, t3=t3,
                   quality_score=p.quality_score)

    use_trailing = getattr(config, "USE_TRAILING_STOP_AFTER_T2", False)
    trail_mult = getattr(config, "TRAILING_ATR_MULT", 1.5)
    sign = 1 if bullish else -1

    # walk forward bar by bar from the entry bar to see what gets hit first
    future = df.iloc[entry_idx + 1:]
    hit_t1 = hit_t2 = False
    current_stop = stop_price
    bar_offset = 0
    for ts, row in future.iterrows():
        bar_offset += 1
        hi, lo, close = row['High'], row['Low'], row['Close']

        stop_hit = (lo <= current_stop) if bullish else (hi >= current_stop)
        if stop_hit:
            trade.exit_date, trade.exit_price = ts, current_stop
            if hit_t1 and hit_t2 and use_trailing:
                trade.outcome = 'TRAIL'
            else:
                trade.outcome = 'STOP' if not hit_t1 else ('T1->BE' if not hit_t2 else 'T1+T2->BE')
            trade.r_multiple = _blended_r(hit_t1, hit_t2, stop_hit=True, risk=risk,
                                           entry=entry_price, t1=t1, t2=t2, exit_price=current_stop,
                                           bullish=bullish)
            return trade

        if not hit_t1 and sign * (hi if bullish else lo) >= sign * t1:
            hit_t1 = True
            trade.bars_to_t1 = bar_offset
            trade.time_to_t1 = ts - trade.entry_date
            current_stop = entry_price  # move to breakeven

        if hit_t1 and not hit_t2 and sign * (hi if bullish else lo) >= sign * t2:
            hit_t2 = True
            trade.bars_to_t2 = bar_offset
            trade.time_to_t2 = ts - trade.entry_date
            if use_trailing:
                atr_here = atr.iloc[entry_idx + bar_offset] if entry_idx + bar_offset < len(atr) else atr.iloc[-1]
                atr_here = atr_here if not np.isnan(atr_here) else 0
                candidate = close - sign * atr_here * trail_mult
                current_stop = max(current_stop, candidate) if bullish else min(current_stop, candidate)

        elif hit_t1 and hit_t2 and use_trailing:
            # keep trailing every subsequent bar
            atr_here = atr.iloc[entry_idx + bar_offset] if entry_idx + bar_offset < len(atr) else atr.iloc[-1]
            atr_here = atr_here if not np.isnan(atr_here) else 0
            candidate = close - sign * atr_here * trail_mult
            current_stop = max(current_stop, candidate) if bullish else min(current_stop, candidate)

        elif hit_t1 and hit_t2 and not use_trailing:
            hit_t3 = sign * (hi if bullish else lo) >= sign * t3
            if hit_t3:
                trade.exit_date, trade.exit_price, trade.outcome = ts, t3, 'T3'
                trade.bars_to_t3 = bar_offset
                trade.time_to_t3 = ts - trade.entry_date
                trade.r_multiple = _blended_r(hit_t1, hit_t2, stop_hit=False, risk=risk,
                                               entry=entry_price, t1=t1, t2=t2, exit_price=t3,
                                               bullish=bullish)
                return trade

    # ran off the end of data still open -- mark to last close
    last_close = future['Close'].iloc[-1] if len(future) else entry_price
    trade.exit_date, trade.exit_price, trade.outcome = future.index[-1] if len(future) else None, last_close, 'OPEN'
    trade.r_multiple = sign * (last_close - entry_price) / risk
    return trade


def _blended_r(hit_t1, hit_t2, stop_hit, risk, entry, t1, t2, exit_price, bullish):
    """
    R-multiple for a scaled exit (1/3 at T1, 1/3 at T2, 1/3 at T3/stop),
    matching the three-target trade management described above. Once T1 is
    hit the stop is assumed moved to breakeven on the remaining size
    (standard practice), so a stop-out after T1 nets to roughly breakeven
    on the remaining thirds rather than a full -1R loss.
    """
    sign = 1 if bullish else -1
    legs = []
    if hit_t1:
        legs.append(sign * (t1 - entry) / risk)
    else:
        legs.append(-1.0 if stop_hit else sign * (exit_price - entry) / risk)
    if hit_t1:
        if hit_t2:
            legs.append(sign * (t2 - entry) / risk)
        else:
            legs.append(0.0 if stop_hit else sign * (exit_price - entry) / risk)  # BE stop after T1
        if hit_t2:
            legs.append(sign * (exit_price - entry) / risk)  # third leg rides to T3 or BE-stop
        elif hit_t1:
            legs.append(0.0 if stop_hit else sign * (exit_price - entry) / risk)
    return float(np.mean(legs)) if legs else (sign * (exit_price - entry) / risk)


def _summarize(trades: list[Trade], equity_curve, starting_equity: float) -> dict:
    if not trades:
        return {"trades": [], "n_trades": 0, "message": "No qualifying patterns found in this period."}

    r_multiples = [t.r_multiple for t in trades if t.r_multiple is not None]
    wins = [r for r in r_multiples if r > 0]
    losses = [r for r in r_multiples if r <= 0]
    equity_vals = [e for _, e in equity_curve]
    peak = -np.inf
    max_dd = 0.0
    for e in equity_vals:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    by_pattern = {}
    for t in trades:
        by_pattern.setdefault(t.pattern, []).append(t)
    pattern_stats = {
        name: {
            "n": len(ts),
            "win_rate": round(100 * sum(1 for t in ts if t.r_multiple and t.r_multiple > 0) / len(ts), 1),
            "avg_r": round(float(np.mean([t.r_multiple for t in ts if t.r_multiple is not None])), 2),
        } for name, ts in by_pattern.items()
    }

    def _timing_stats_for(trade_list, field_bars, field_time):
        bars = [getattr(t, field_bars) for t in trade_list if getattr(t, field_bars) is not None]
        times = [getattr(t, field_time) for t in trade_list if getattr(t, field_time) is not None]
        if not bars:
            return {"n_reached": 0, "avg_bars": None, "median_bars": None,
                    "min_bars": None, "max_bars": None, "avg_time": None, "median_time": None}
        return {
            "n_reached": len(bars),
            "avg_bars": round(float(np.mean(bars)), 1),
            "median_bars": round(float(np.median(bars)), 1),
            "min_bars": int(np.min(bars)),
            "max_bars": int(np.max(bars)),
            "avg_time": str(pd.Series(times).mean()) if times else None,
            "median_time": str(pd.Series(times).median()) if times else None,
        }

    timing = {
        "T1": _timing_stats_for(trades, "bars_to_t1", "time_to_t1"),
        "T2": _timing_stats_for(trades, "bars_to_t2", "time_to_t2"),
        "T3": _timing_stats_for(trades, "bars_to_t3", "time_to_t3"),
    }
    by_pattern_timing = {
        name: {
            "T1": _timing_stats_for(ts, "bars_to_t1", "time_to_t1"),
            "T2": _timing_stats_for(ts, "bars_to_t2", "time_to_t2"),
            "T3": _timing_stats_for(ts, "bars_to_t3", "time_to_t3"),
        } for name, ts in by_pattern.items()
    }

    return {
        "trades": trades,
        "n_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(r_multiples), 1) if r_multiples else 0,
        "avg_r": round(float(np.mean(r_multiples)), 2) if r_multiples else 0,
        "avg_win_r": round(float(np.mean(wins)), 2) if wins else 0,
        "avg_loss_r": round(float(np.mean(losses)), 2) if losses else 0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else float('inf'),
        "expectancy_r": round(float(np.mean(r_multiples)), 3) if r_multiples else 0,
        "final_equity": round(equity_vals[-1], 2),
        "return_pct": round((equity_vals[-1] / starting_equity - 1) * 100, 1),
        "max_drawdown_pct": round(max_dd, 1),
        "equity_curve": equity_curve,
        "by_pattern": pattern_stats,
        "timing": timing,
        "by_pattern_timing": by_pattern_timing,
    }


def estimate_time_to_targets(df: pd.DataFrame, pattern_name: str, deviation_pct: float = 3.0,
                              tolerance: float = 0.05, min_quality: float = 50.0,
                              require_confirmation: bool = False) -> dict:
    """
    Lightweight helper for the live scanner: runs a backtest over the
    supplied history and returns time-to-target stats for one specific
    pattern type, so an ENTER NOW alert can say "T1 has historically hit
    within N bars on this instrument" instead of leaving timing a total
    unknown. require_confirmation defaults to False here so there's enough
    sample size to be useful -- it's an ETA estimate, not a repeat of the
    strict entry gate.
    """
    result = backtest(df, deviation_pct=deviation_pct, tolerance=tolerance,
                       min_quality=min_quality, require_confirmation=require_confirmation)
    per_pattern = result.get("by_pattern_timing", {}).get(pattern_name)
    if not per_pattern or per_pattern["T1"]["n_reached"] < 3:
        overall = result.get("timing")
        return {"specific": False, "timing": overall, "n_trades_used": result.get("n_trades", 0)}
    return {"specific": True, "timing": per_pattern, "n_trades_used": per_pattern["T1"]["n_reached"]}


def walk_forward_validate(df: pd.DataFrame, in_sample_pct: float = 0.7, **backtest_kwargs) -> dict:
    """
    Out-of-sample validation: splits the price history into an in-sample
    chunk (tune your settings against this) and a completely untouched
    out-of-sample chunk (verify against this). If performance collapses
    out-of-sample, whatever settings looked good in-sample were likely
    overfit to noise -- a very common way harmonic backtests mislead
    people. This does NOT tune anything automatically; it just runs the
    same settings on both halves so you can compare them honestly.

    Usage: pick your deviation_pct/min_quality/etc by eye on the in-sample
    results, then check the out-of-sample results with the SAME settings
    before trusting them. A large gap (e.g. in-sample profit factor 3.0,
    out-of-sample 0.8) is a red flag, not something to explain away.
    """
    split_idx = int(len(df) * in_sample_pct)
    if split_idx < 100 or len(df) - split_idx < 100:
        return {"error": "Not enough data for a meaningful in-sample/out-of-sample split. "
                          "Use a longer history period."}

    in_sample_df = df.iloc[:split_idx]
    out_sample_df = df.iloc[split_idx:]

    in_sample_result = backtest(in_sample_df, **backtest_kwargs)
    out_sample_result = backtest(out_sample_df, **backtest_kwargs)

    def _flag(in_res, out_res):
        if in_res.get("n_trades", 0) < 5 or out_res.get("n_trades", 0) < 5:
            return "insufficient_data"
        in_exp = in_res.get("expectancy_r", 0)
        out_exp = out_res.get("expectancy_r", 0)
        if in_exp <= 0:
            return "in_sample_already_unprofitable"
        if out_exp <= 0:
            return "overfit_likely -- out-of-sample expectancy is negative despite positive in-sample"
        degradation = (in_exp - out_exp) / abs(in_exp) if in_exp != 0 else 0
        if degradation > 0.5:
            return f"overfit_warning -- out-of-sample expectancy is {degradation:.0%} lower than in-sample"
        return "consistent -- out-of-sample performance broadly matches in-sample"

    return {
        "split_date": df.index[split_idx],
        "in_sample": {"n_bars": split_idx, "date_range": (df.index[0], df.index[split_idx - 1]),
                      "result": in_sample_result},
        "out_of_sample": {"n_bars": len(df) - split_idx,
                          "date_range": (df.index[split_idx], df.index[-1]),
                          "result": out_sample_result},
        "verdict": _flag(in_sample_result, out_sample_result),
    }
