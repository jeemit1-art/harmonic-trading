"""
Backtester built on engine.py -- the same signal, plan, gating and exit code
the live scanner runs. Differences from the original backtester, all of which
made the old numbers optimistic or meaningless:

  * NO LOOKAHEAD: at bar t only bars <= t exist. A pattern is usable only once
    its D pivot is CONFIRMED (D.confirmed_at) -- the old code entered at the
    candle right after D's price, days before D could have been known.
  * CORRECT INDICES: the old _simulate_trade ran candle/RSI/MACD checks on the
    full dataframe using window-local pivot indices, i.e. it inspected the
    wrong candles for almost every trade.
  * Entry at the NEXT bar's open, gap-aware stop/target fills, ATR trailing,
    time stop, per-ticker single position, costs in R.
  * Reports a bootstrap lower bound on expectancy so one lucky streak can't
    pass for an edge.
"""
import numpy as np
import pandas as pd

import config
from patterns import find_patterns
from engine import (evaluate_signal, build_plan, check_plan, new_position, advance_position, atr_series)


def run_backtest(df: pd.DataFrame, market: str = "US", ticker: str = "TEST", timeframe: str = "1d",
                 deviation_pct: float = 3.0, tolerance: float = None, min_quality: float = None,
                 risk_per_trade_pct: float = 1.0, starting_equity: float = 10000.0,
                 lookback_window: int = 250, step: int = 1, require_momentum: bool = None,
                 warmup: int = 60) -> dict:
    tolerance = config.RATIO_TOLERANCE if tolerance is None else tolerance
    atr_full = atr_series(df)
    positions, seen = [], set()
    busy_until = -1                                  # one open position per ticker
    n = len(df)
    for t in range(max(warmup, 30), n - 1, step):
        if t <= busy_until:
            continue
        window = df.iloc[max(0, t - lookback_window + 1): t + 1]
        pats = find_patterns(window, deviation_pct=deviation_pct, tolerance=tolerance, include_forming=False,
                             include_tentative=config.USE_TENTATIVE_D)
        best = None
        for p in pats:
            sig = evaluate_signal(window, p, min_quality=min_quality, require_momentum=require_momentum)
            if sig is None:
                continue
            sid = f"{ticker}:{p.direction.value}:{p.D.timestamp}"
            if sid in seen:
                continue
            plan = build_plan(window, p, atr_series(window))
            ok, why = check_plan(window, p, plan, float(window['Close'].iloc[-1]))
            if not ok:
                continue
            if best is None or p.quality_score > best[0].quality_score:
                best = (p, plan, sid)
        if best is None:
            continue
        p, plan, sid = best
        seen.add(sid)
        pos = new_position(p, plan, market, ticker, timeframe, window.index[-1], sid)
        advance_position(pos, df, atr_full)             # future bars only decide the OUTCOME
        if pos["status"] == "CLOSED_INVALIDATED":
            continue
        if pos["status"] in ("PENDING", "OPEN", "PARTIAL_T1", "PARTIAL_T2"):
            # ran off the end of data: mark the remainder to the last close
            s = 1 if pos["direction"] == "bullish" else -1
            risk = abs(pos["entry"] - pos["orig_stop"]) if pos["entry"] else None
            if not risk:
                continue
            pos["realized_r"] += pos["fraction_remaining"] * s * (float(df['Close'].iloc[-1]) - pos["entry"]) / risk
            pos["r_multiple"] = pos["realized_r"] - config.COST_PCT.get(market, 0.1) / 100 * pos["entry"] / risk
            pos["status"], pos["closed_at"] = "CLOSED_OPEN_AT_END", str(df.index[-1])
        positions.append(pos)
        busy_until = df.index.get_loc(pd.Timestamp(pos["closed_at"])) if pd.Timestamp(pos["closed_at"]) in df.index else n
    return summarize(positions, starting_equity, risk_per_trade_pct)


def summarize(positions: list, starting_equity: float, risk_pct: float, seed: int = 7) -> dict:
    if not positions:
        return {"trades": [], "n_trades": 0, "message": "No qualifying trades in this period."}
    positions = sorted(positions, key=lambda p: p["closed_at"])
    rs = np.array([p["r_multiple"] for p in positions], dtype=float)
    wins, losses = rs[rs > 0], rs[rs <= 0]
    eq, curve, peak, max_dd = starting_equity, [(positions[0]["signal_ts"], starting_equity)], starting_equity, 0.0
    for p in positions:
        eq *= (1 + risk_pct / 100.0 * p["r_multiple"])
        curve.append((p["closed_at"], eq))
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    rng = np.random.default_rng(seed)
    boots = rng.choice(rs, size=(2000, len(rs)), replace=True).mean(axis=1)
    by_pattern = {}
    for p in positions:
        by_pattern.setdefault(p["pattern"], []).append(p["r_multiple"])

    def timing(key):
        v = [p[key] for p in positions if p.get(key) is not None]
        return {"n_reached": len(v), "median_bars": float(np.median(v)) if v else None,
                "min_bars": int(min(v)) if v else None, "max_bars": int(max(v)) if v else None}
    return {
        "trades": positions, "n_trades": len(positions),
        "win_rate_pct": round(100 * float((rs > 0).mean()), 1),
        "expectancy_r": round(float(rs.mean()), 3),
        "expectancy_r_p5": round(float(np.percentile(boots, 5)), 3),   # 5th pct of bootstrap: "worst plausible" edge
        "avg_win_r": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_r": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 2) if losses.sum() != 0 else float("inf"),
        "return_pct": round((eq / starting_equity - 1) * 100, 1), "final_equity": round(eq, 2),
        "max_drawdown_pct": round(max_dd, 1), "equity_curve": curve,
        "by_pattern": {k: {"n": len(v), "avg_r": round(float(np.mean(v)), 2),
                           "win_rate": round(100 * float(np.mean(np.array(v) > 0)), 1)} for k, v in by_pattern.items()},
        "timing": {"T1": timing("bars_to_t1"), "T2": timing("bars_to_t2")},
    }


def walk_forward_validate(df: pd.DataFrame, in_sample_pct: float = 0.7, **kw) -> dict:
    split = int(len(df) * in_sample_pct)
    if split < 150 or len(df) - split < 150:
        return {"error": "Not enough data for a meaningful split."}
    a, b = run_backtest(df.iloc[:split], **kw), run_backtest(df.iloc[split:], **kw)
    if a.get("n_trades", 0) < 5 or b.get("n_trades", 0) < 5:
        verdict = "insufficient_data"
    elif a["expectancy_r"] <= 0:
        verdict = "in_sample_already_unprofitable"
    elif b["expectancy_r"] <= 0:
        verdict = "overfit_likely -- out-of-sample expectancy negative"
    elif (a["expectancy_r"] - b["expectancy_r"]) / a["expectancy_r"] > 0.5:
        verdict = "overfit_warning -- out-of-sample >50% weaker"
    else:
        verdict = "consistent"
    return {"in_sample": a, "out_of_sample": b, "verdict": verdict, "split_date": df.index[split]}
