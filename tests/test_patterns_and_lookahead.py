import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import numpy as np, pandas as pd
import config
from patterns import find_patterns, zigzag_pivots
from backtest import run_backtest
from make_synth import random_walk


def leg(a, b, n):
    return np.linspace(a, b, n)


def gartley_df(hammer=True):
    X, A = 100.0, 150.0
    B = A - 0.618 * (A - X); C = B + 0.5 * (A - B); D = A - 0.786 * (A - X)
    path = np.r_[leg(X, A, 40), leg(A, B, 30)[1:], leg(B, C, 20)[1:], leg(C, D, 25)[1:], leg(D, D + 12, 12)[1:]]
    n = len(path)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    o = np.r_[path[0], path[:-1]]
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, path) + 0.2, "Low": np.minimum(o, path) - 0.2,
                       "Close": path, "Volume": 1000}, index=idx)
    return df, dict(X=X, A=A, B=B, C=C, D=D)


def test_one_result_per_structure_no_duplicates():
    df, _ = gartley_df()
    pats = [p for p in find_patterns(df, 5.0, 0.06, include_forming=False) if p.D is not None]
    keys = [(p.X.timestamp, p.D.timestamp) for p in pats]
    assert len(keys) == len(set(keys)) and any(p.name == "Gartley" for p in pats)


def test_every_pattern_has_valid_geometry():
    for seed in range(1, 6):
        df = random_walk(1200, seed)
        for p in find_patterns(df, 3.0, 0.05):
            if p.D is None:
                continue
            s = 1 if p.direction.value == "bullish" else -1
            assert s * p.D.price < s * p.C.price                 # D on the reversal side of C
            if p.name in ("Gartley", "Bat"):
                assert s * p.D.price > s * p.X.price             # retracement patterns stay inside XA
            if p.name in ("Butterfly", "Crab", "Deep Crab", "Alt Bat"):
                assert s * p.D.price < s * p.X.price             # extension patterns go beyond X


def test_pivot_confirmed_after_pivot_bar():
    df = random_walk(800, 3)
    for p in zigzag_pivots(df, 3.0):
        assert p.confirmed_at >= p.index        # a pivot can never be known before it happens


def _signals_upto(df, cutoff, dev=1.5):
    """Every signal the engine would raise at each bar t <= cutoff (windows end at t, like the backtester)."""
    from engine import evaluate_signal
    out = []
    for t in range(60, cutoff):
        w = df.iloc[max(0, t - 249): t + 1]
        for p in find_patterns(w, dev, 0.05, include_forming=False, include_tentative=True):
            sig = evaluate_signal(w, p, min_quality=0, require_momentum=False)
            if sig:
                out.append((t, p.name, str(p.D.timestamp), round(p.D.price, 6), sig["signal_bar"]))
    return out


def test_no_lookahead_signals_do_not_depend_on_future_bars():
    """Replace everything after the cutoff with a DIFFERENT random path; signals up to the cutoff must not change."""
    total = 0
    for seed in range(1, 13):
        df_a = random_walk(700, seed, vol=0.02)
        tail = random_walk(700, seed + 100, vol=0.04, start=float(df_a['Close'].iloc[449]))
        df_b = df_a.copy()
        df_b.iloc[450:, :] = tail.iloc[450:, :].values
        a, b = _signals_upto(df_a, 450), _signals_upto(df_b, 450)
        assert a == b, "signals changed when only FUTURE bars changed -> lookahead"
        total += len(a)
    assert total >= 8, f"only {total} signals compared - test not meaningful"
