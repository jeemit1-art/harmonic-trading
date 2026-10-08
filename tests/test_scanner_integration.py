import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import numpy as np, pandas as pd
import config, scanner, state as st, leaderboard as lb
from engine import new_position


def make_df(n_total):
    idx = pd.date_range("2024-01-01", periods=120, freq="B")
    c = np.r_[np.full(80, 100.0), [100, 100], np.linspace(97, 115, 38)]          # flat, then dip, then rally
    o = np.r_[c[:1], c[:-1]]
    h, l = np.maximum(o, c) + 0.2, np.minimum(o, c) - 0.2
    l[81] = 94.0                                                                  # wick through the 95 stop
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1000}, index=idx)
    return df.iloc[:n_total]


class Stub:
    def __init__(self): self.df = None
    def fetch_many(self, tickers, interval, period, market="US", retries=3): return {tickers[0]: self.df}


def seed_state(path, df):
    s = st.empty()
    pos = {"id": "T:bullish:x", "market": "US", "ticker": "T", "timeframe": "1d", "pattern": "Gartley", "direction": "bullish",
           "quality": 80, "status": "PENDING", "signal_ts": str(df.index[79]), "last_bar": str(df.index[79]), "entry": None,
           "stop": 95.0, "orig_stop": 95.0, "t1": 105.0, "t2": 110.0, "t3": 120.0, "fraction_remaining": 1.0,
           "realized_r": 0.0, "bars_held": 0, "trailing": False, "bars_to_t1": None, "bars_to_t2": None,
           "r_multiple": None, "exit_price": None, "max_chase": 103.0, "points": {}, "confluence": {}}
    s["positions"][pos["id"]] = pos
    st.save(s, path)


def test_stopped_trade_never_alerts_targets_even_when_pattern_is_gone(tmp_path, monkeypatch):
    path = str(tmp_path / "s.json")
    monkeypatch.setattr(lb, "LEADERBOARD_FILE", str(tmp_path / "lb.json"))
    monkeypatch.setitem(scanner.WATCHLISTS, "US", ["T"])
    stub = Stub(); monkeypatch.setattr(scanner, "DEFAULT_SOURCE", stub)
    config.COST_PCT = {"US": 0.0}
    full = make_df(120)
    seed_state(path, full)

    stub.df = make_df(90)                       # contains entry bar, the stop wick, and a partial rally
    scanner.run_scan(["US"], state_path=path)
    s1 = st.load(path)
    kinds1 = [a["kind"] for a in s1["outbox"] if a["kind"] != "SUMMARY"]
    assert kinds1 == ["ENTERED", "STOP"], kinds1                     # Telegram unconfigured -> alerts retained, not lost
    assert not s1["positions"] and len(s1["closed"]) == 1 and s1["closed"][0]["status"] == "CLOSED_STOP"

    stub.df = full                              # price has since rallied far through T1/T2/T3
    scanner.run_scan(["US"], state_path=path)
    s2 = st.load(path)
    kinds2 = [a["kind"] for a in s2["outbox"] if a["kind"] != "SUMMARY"]
    assert kinds2 == ["ENTERED", "STOP"], "closed trade produced new alerts after the stop!"


def test_delayed_run_still_sees_the_stop(tmp_path, monkeypatch):
    path = str(tmp_path / "s.json")
    monkeypatch.setattr(lb, "LEADERBOARD_FILE", str(tmp_path / "lb.json"))
    monkeypatch.setitem(scanner.WATCHLISTS, "US", ["T"])
    stub = Stub(); monkeypatch.setattr(scanner, "DEFAULT_SOURCE", stub)
    full = make_df(120)
    seed_state(path, full)
    stub.df = full                              # the scheduler skipped every run until bar 120; stop was at bar 81
    scanner.run_scan(["US"], state_path=path)
    kinds = [a["kind"] for a in st.load(path)["outbox"] if a["kind"] != "SUMMARY"]
    assert "STOP" in kinds and "T1" not in kinds
