import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime, timezone
import numpy as np, pandas as pd
from data_sources import resample_4h, drop_incomplete


def hourly(start, n):
    idx = pd.date_range(start, periods=n, freq="h", tz="UTC")
    p = np.arange(n, dtype=float) + 100
    return pd.DataFrame({"Open": p, "High": p + 1, "Low": p - 1, "Close": p + 0.5, "Volume": 10}, index=idx)


def test_resample_4h_aggregates_correctly():
    r = resample_4h(hourly("2024-03-04 00:00", 8))
    assert len(r) == 2 and r["Open"].iloc[0] == 100 and r["High"].iloc[0] == 104 and r["Low"].iloc[0] == 99
    assert r["Close"].iloc[0] == 103.5 and r["Volume"].iloc[0] == 40


def test_partial_4h_bar_is_dropped():
    r = resample_4h(hourly("2024-03-04 00:00", 10))          # last 4h bar only has 2 hours of data
    now = datetime(2024, 3, 4, 10, 5, tzinfo=timezone.utc)
    kept = drop_incomplete(r, "4h", "FOREX", now)
    assert kept.index[-1] == pd.Timestamp("2024-03-04 04:00", tz="UTC")     # 08:00 bar ends 12:00 > now


def test_daily_bar_today_dropped_until_after_close():
    idx = pd.to_datetime(["2024-03-06", "2024-03-07"])
    df = pd.DataFrame({"Open": 1., "High": 2., "Low": 0.5, "Close": 1.5, "Volume": 1}, index=idx)
    during = datetime(2024, 3, 7, 18, 0, tzinfo=timezone.utc)          # 13:00 New York (EST): session open
    after = datetime(2024, 3, 7, 21, 30, tzinfo=timezone.utc)          # 16:30 New York
    assert len(drop_incomplete(df, "1d", "US", during)) == 1
    assert len(drop_incomplete(df, "1d", "US", after)) == 2


def test_asx_daily_bar_available_same_evening_utc():
    idx = pd.to_datetime(["2024-03-07"])
    df = pd.DataFrame({"Open": 1., "High": 2., "Low": 0.5, "Close": 1.5, "Volume": 1}, index=idx)
    t = datetime(2024, 3, 7, 6, 45, tzinfo=timezone.utc)               # 17:45 AEDT same day
    assert len(drop_incomplete(df, "1d", "AUS", t)) == 1
