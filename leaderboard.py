"""
Performance leaderboard. Tracks how each (market, ticker, pattern) combo
has actually performed -- from live closed trades (the ground truth) and
optionally seeded from backtests -- and lets the scanner auto-suppress
ENTER NOW alerts for combos that are demonstrably underperforming.

Not all harmonic patterns perform equally on all instruments. Rather than
treating "Gartley on AAPL" and "Crab on AUDUSD" as equally trustworthy
forever, this lets the system learn from what's actually happened.

Data lives in leaderboard.json: one row per (market, ticker, pattern),
updated every time a tracked trade fully closes (CLOSED_T3, CLOSED_STOP,
or a partial-exit that locks in a known R).
"""
import json
import os
from datetime import datetime, timezone

LEADERBOARD_FILE = os.path.join(os.path.dirname(__file__), "leaderboard.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_leaderboard() -> dict:
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE) as f:
            return json.load(f)
    return {}


def save_leaderboard(board: dict):
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(board, f, indent=2, default=str)


def _key(market: str, ticker: str, pattern: str) -> str:
    return f"{market}:{ticker}:{pattern}"


def record_outcome(board: dict, market: str, ticker: str, pattern: str,
                    r_multiple: float, source: str = "live") -> dict:
    """
    Record one closed trade's realized R-multiple against a combo's
    running stats. source is 'live' (from the scanner/trade_manager) or
    'backtest' (seeded from a backtest run) -- kept separate so live
    results, which matter most, aren't diluted by backtest volume.
    """
    k = _key(market, ticker, pattern)
    row = board.get(k, {
        "market": market, "ticker": ticker, "pattern": pattern,
        "live_trades": [], "backtest_trades": [],
        "last_update": _now(),
    })
    bucket = "live_trades" if source == "live" else "backtest_trades"
    row.setdefault(bucket, []).append({"r": round(float(r_multiple), 3), "date": _now()})
    row["last_update"] = _now()
    board[k] = row
    return board


def _stats(trade_list: list) -> dict:
    if not trade_list:
        return {"n": 0, "win_rate": None, "avg_r": None, "expectancy": None}
    rs = [t["r"] for t in trade_list]
    wins = [r for r in rs if r > 0]
    return {
        "n": len(rs),
        "win_rate": round(100 * len(wins) / len(rs), 1),
        "avg_r": round(sum(rs) / len(rs), 2),
        "expectancy": round(sum(rs) / len(rs), 3),
    }


def get_combo_stats(board: dict, market: str, ticker: str, pattern: str) -> dict:
    row = board.get(_key(market, ticker, pattern))
    if not row:
        return {"live": _stats([]), "backtest": _stats([]), "has_data": False}
    return {
        "live": _stats(row.get("live_trades", [])),
        "backtest": _stats(row.get("backtest_trades", [])),
        "has_data": True,
    }


def should_suppress(board: dict, market: str, ticker: str, pattern: str,
                     min_live_trades: int = 5, min_expectancy: float = 0.0,
                     min_backtest_trades: int = 10, min_backtest_expectancy: float = 0.1) -> dict:
    """
    Decide whether an ENTER NOW alert for this combo should be suppressed
    based on its track record. Conservative by design: with too few trades
    to judge, it does NOT suppress (avoids killing a combo on noise) --
    it only suppresses once there's enough sample size showing a
    genuinely negative or weak expectancy.
    """
    stats = get_combo_stats(board, market, ticker, pattern)
    live = stats["live"]
    bt = stats["backtest"]

    if live["n"] >= min_live_trades:
        if live["expectancy"] < min_expectancy:
            return {"suppress": True,
                    "reason": f"Live track record: {live['n']} trades, expectancy {live['expectancy']}R "
                              f"(below threshold {min_expectancy}R) -- suppressing new alerts for this combo."}
        return {"suppress": False, "reason": f"Live track record supports trading this combo "
                                              f"({live['n']} trades, {live['expectancy']}R expectancy)."}

    # not enough live data yet -- fall back to backtest as a soft check
    if bt["n"] >= min_backtest_trades and bt["expectancy"] < min_backtest_expectancy:
        return {"suppress": True,
                "reason": f"Backtest history: {bt['n']} trades, expectancy {bt['expectancy']}R "
                          f"(below threshold {min_backtest_expectancy}R) -- suppressing until live data accrues."}

    return {"suppress": False, "reason": "Not enough track record yet to judge this combo -- trading normally."}


def leaderboard_summary(board: dict) -> list:
    """Flat, sorted list for display (dashboard / reports)."""
    rows = []
    for k, row in board.items():
        live = _stats(row.get("live_trades", []))
        bt = _stats(row.get("backtest_trades", []))
        rows.append({
            "market": row["market"], "ticker": row["ticker"], "pattern": row["pattern"],
            "live_n": live["n"], "live_win_rate": live["win_rate"], "live_avg_r": live["avg_r"],
            "bt_n": bt["n"], "bt_win_rate": bt["win_rate"], "bt_avg_r": bt["avg_r"],
            "last_update": row.get("last_update"),
        })
    rows.sort(key=lambda r: (r["live_avg_r"] if r["live_avg_r"] is not None else -999), reverse=True)
    return rows


def seed_from_backtest(board: dict, market: str, ticker: str, backtest_result: dict) -> dict:
    """Bulk-load a backtest's trades into the leaderboard's backtest bucket."""
    for t in backtest_result.get("trades", []):
        if t.r_multiple is not None:
            board = record_outcome(board, market, ticker, t.pattern, t.r_multiple, source="backtest")
    return board
