import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import numpy as np, pandas as pd, pytest
import config
from engine import advance_position, atr_series

config.COST_PCT = {"US": 0.0}
config.ENTRY_SLIPPAGE_PCT = 0.0
config.USE_TRAILING_STOP_AFTER_T2 = False
config.MAX_HOLD_BARS = 40


def bars(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx).assign(Volume=1000)


def pos(df, direction="bullish", entry_ref=100, stop=95, t1=105, t2=110, t3=120):
    if direction == "bearish":
        stop, t1, t2, t3 = 2 * entry_ref - stop, 2 * entry_ref - t1, 2 * entry_ref - t2, 2 * entry_ref - t3
    return {"id": "x", "market": "US", "ticker": "T", "direction": direction, "status": "PENDING",
            "last_bar": str(df.index[0]), "entry": None, "stop": stop, "orig_stop": stop, "t1": t1, "t2": t2,
            "t3": t3, "fraction_remaining": 1.0, "realized_r": 0.0, "bars_held": 0, "trailing": False,
            "bars_to_t1": None, "bars_to_t2": None, "r_multiple": None}


def types(ev): return [e["type"] for e in ev]


def test_stop_then_target_only_reports_stop():
    # THE reported bug: stop touched, price later rallies through T1. Must report STOP only, never T1.
    df = bars([(100, 100, 100, 100),            # signal bar
               (100, 101, 94, 99),              # entry @100, wick through stop 95
               (99, 112, 98, 111)])             # later rally through T1/T2
    p = pos(df)
    ev = advance_position(p, df)
    assert types(ev) == ["ENTERED", "STOP"]
    assert p["status"] == "CLOSED_STOP" and p["r_multiple"] == pytest.approx(-1.0)


def test_delayed_run_catches_old_stop():
    # scheduler skipped 3 bars; only the last bar is 'now'. Old logic checked just the last bar.
    df = bars([(100, 100, 100, 100), (100, 101, 99, 100), (100, 100, 94, 99), (99, 104, 99, 103), (103, 106, 102, 105)])
    p = pos(df)
    ev = advance_position(p, df)
    assert "STOP" in types(ev) and "T1" not in types(ev)


def test_multiple_transitions_in_one_call_and_idempotent():
    df = bars([(100, 100, 100, 100), (100, 106, 99, 105), (105, 111, 104, 110)])
    p = pos(df)
    ev = advance_position(p, df)
    assert types(ev) == ["ENTERED", "T1", "T2"] and p["status"] == "PARTIAL_T2"
    assert advance_position(p, df) == []            # second call: nothing new, no duplicate alerts


def test_gap_through_stop_fills_at_open_not_stop():
    df = bars([(100, 100, 100, 100), (100, 102, 99, 101), (90, 91, 88, 89)])
    p = pos(df)
    advance_position(p, df)
    assert p["exit_price"] == 90 and p["r_multiple"] == pytest.approx(-2.0)


def test_gap_past_plan_invalidates_pending():
    df = bars([(100, 100, 100, 100), (94, 95, 93, 94)])   # next open already through the stop
    p = pos(df)
    ev = advance_position(p, df)
    assert types(ev) == ["INVALIDATED"] and p["status"] == "CLOSED_INVALIDATED"


def test_full_win_math():
    df = bars([(100, 100, 100, 100), (100, 106, 99, 105), (105, 111, 104, 110), (110, 121, 109, 120)])
    p = pos(df)
    advance_position(p, df)
    assert p["status"] == "CLOSED_T3"
    assert p["r_multiple"] == pytest.approx((1 + 2 + 4) / 3)       # risk 5: T1=+1R T2=+2R T3=+4R, thirds


def test_breakeven_after_t1():
    df = bars([(100, 100, 100, 100), (100, 106, 99, 105), (105, 106, 99.5, 100)])
    p = pos(df)
    ev = advance_position(p, df)
    assert types(ev) == ["ENTERED", "T1", "BE_STOP"]
    assert p["r_multiple"] == pytest.approx(1 / 3)


def test_short_side_mirror():
    df = bars([(100, 100, 100, 100), (100, 101, 94, 95), (95, 96, 89, 90)])
    p = pos(df, "bearish")
    advance_position(p, df)
    assert p["status"] in ("PARTIAL_T2", "CLOSED_T3") and p["realized_r"] > 0


def test_time_stop_closes_zombies():
    config.MAX_HOLD_BARS = 5
    df = bars([(100, 100, 100, 100)] + [(100, 101, 99.5, 100)] * 10)
    p = pos(df)
    ev = advance_position(p, df)
    config.MAX_HOLD_BARS = 40
    assert types(ev)[-1] == "TIME_STOP" and p["status"] == "CLOSED_TIME"


def test_closed_position_never_alerts_again():
    df = bars([(100, 100, 100, 100), (100, 101, 94, 99)])
    p = pos(df)
    advance_position(p, df)
    df2 = pd.concat([df, bars([(99, 130, 98, 125)]).set_axis([df.index[-1] + pd.offsets.BDay(1)])])
    assert advance_position(p, df2) == []
