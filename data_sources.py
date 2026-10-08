"""
Data layer. Fixes vs v1:
  * yfinance has NO '4h' interval -- v1 asked for it, so every FOREX scan failed.
    4h bars are now built by resampling 1h.
  * Only CLOSED bars are returned. v1 happily analysed the still-forming last
    bar, so a hammer/engulfing candle could appear mid-session and vanish by close.
  * Batched downloads (one request per ~40 tickers) instead of ~2,400 sequential
    ones per run, which was slow enough that data was stale before the scan ended.
  * auto_adjust=False: levels match the prices you actually see and trade
    (splits adjusted, dividends not).
  * Tickers that keep returning nothing (delisted/renamed) are skipped for a week
    instead of burning three retries every run.
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

MARKET_TZ = {"AUS": "Australia/Sydney", "US": "America/New_York", "INDIA": "Asia/Kolkata", "FOREX": "UTC"}
# local time after which a DAILY bar is final (a little after the close, so closing auctions are included)
MARKET_DAILY_FINAL = {"AUS": (16, 30), "US": (16, 15), "INDIA": (15, 50), "FOREX": (0, 0)}
INTERVAL_DELTA = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "60m": "1h", "4h": "4h", "1d": "1D"}
HEALTH_FILE = os.environ.get("HEALTH_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_health.json"))
DEAD_AFTER, DEAD_FOR_DAYS, CHUNK = 3, 7, 40


# ----------------------------------------------------------------------------- pure helpers (unit-tested)
def resample_4h(df1h: pd.DataFrame) -> pd.DataFrame:
    d = df1h.copy()
    d.index = d.index.tz_localize("UTC") if d.index.tz is None else d.index.tz_convert("UTC")
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    out = d.resample("4h", origin="start_day").agg(agg)
    return out.dropna(subset=["Open", "High", "Low", "Close"])


def drop_incomplete(df: pd.DataFrame, interval: str, market: str = "US", now: datetime = None) -> pd.DataFrame:
    """Keep only bars that have fully closed as of `now`."""
    if df.empty:
        return df
    now = now or datetime.now(timezone.utc)
    if interval == "1d":
        tz = ZoneInfo(MARKET_TZ.get(market, "UTC"))
        local = now.astimezone(tz)
        h, m = MARKET_DAILY_FINAL.get(market, (0, 0))
        idx_dates = pd.DatetimeIndex(df.index).tz_localize(None).normalize() if df.index.tz is None \
            else pd.DatetimeIndex(df.index).tz_convert(tz).tz_localize(None).normalize()
        today = pd.Timestamp(local.date())
        final_today = (local.hour, local.minute) >= (h, m)
        keep = (idx_dates < today) | ((idx_dates == today) & final_today)
        if market == "FOREX":
            keep = idx_dates < today
        return df[keep]
    delta = pd.Timedelta(INTERVAL_DELTA.get(interval, "1h"))
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    return df[(idx + delta) <= pd.Timestamp(now)]


# ----------------------------------------------------------------------------- health file
def _load_health() -> dict:
    try:
        with open(HEALTH_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_health(h: dict):
    try:
        with open(HEALTH_FILE, "w") as f:
            json.dump(h, f)
    except Exception:
        pass


def is_dead(h: dict, ticker: str) -> bool:
    r = h.get(ticker)
    if not r or r.get("fails", 0) < DEAD_AFTER:
        return False
    return datetime.fromisoformat(r["last"]) > datetime.now(timezone.utc) - timedelta(days=DEAD_FOR_DAYS)


# ----------------------------------------------------------------------------- download
def _extract(raw: pd.DataFrame, ticker: str, single: bool):
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        l0, l1 = raw.columns.get_level_values(0), raw.columns.get_level_values(1)
        if ticker in l0:
            sub = raw[ticker]
        elif ticker in l1:
            sub = raw.xs(ticker, axis=1, level=1)
        else:
            return None
    else:
        sub = raw if single else None
    if sub is None:
        return None
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in sub.columns]
    if len(cols) < 5:
        return None
    sub = sub[cols].dropna(subset=["Open", "High", "Low", "Close"])
    return sub if len(sub) else None


def _yf_params(interval: str, period: str):
    if interval == "4h":
        return "1h", period
    return interval, period


class YFinanceSource:
    name = "yfinance"

    def fetch_many(self, tickers: list[str], interval: str, period: str, market: str = "US",
                   retries: int = 3) -> dict[str, pd.DataFrame]:
        if yf is None:
            raise RuntimeError("yfinance not installed")
        health = _load_health()
        wanted = [t for t in tickers if not is_dead(health, t)]
        yf_int, yf_period = _yf_params(interval, period)
        out: dict[str, pd.DataFrame] = {}
        for i in range(0, len(wanted), CHUNK):
            chunk = wanted[i:i + CHUNK]
            raw = None
            for attempt in range(retries):
                try:
                    raw = yf.download(chunk, interval=yf_int, period=yf_period, group_by="ticker", auto_adjust=False,
                                      threads=True, progress=False)
                    if raw is not None and not raw.empty:
                        break
                except Exception:
                    pass
                time.sleep(2 * (attempt + 1))
            for t in chunk:
                df = _extract(raw, t, single=len(chunk) == 1)
                if df is None:
                    r = health.get(t, {"fails": 0})
                    health[t] = {"fails": r["fails"] + 1, "last": datetime.now(timezone.utc).isoformat()}
                    continue
                if interval == "4h":
                    df = resample_4h(df)
                df = drop_incomplete(df, interval, market)
                if len(df):
                    out[t] = df
                    health.pop(t, None)
        _save_health(health)
        return out

    def fetch(self, ticker: str, interval: str = "1d", period: str = "1y", market: str = None,
              retries: int = 3) -> pd.DataFrame:
        market = market or _guess_market(ticker)
        res = self.fetch_many([ticker], interval, period, market, retries)
        if ticker not in res:
            raise RuntimeError(f"No data for {ticker} ({interval}/{period})")
        return res[ticker]


def _guess_market(t: str) -> str:
    if t.endswith(".AX"): return "AUS"
    if t.endswith(".NS") or t.endswith(".BO"): return "INDIA"
    if t.endswith("=X"): return "FOREX"
    return "US"


DEFAULT_SOURCE = YFinanceSource()

# ----------------------------------------------------------------------------- watchlists
from watchlists import WATCHLISTS  # noqa: E402  (full lists live in watchlists.py)
DEFAULT_DEVIATION = {"AUS": 3.0, "US": 3.0, "INDIA": 3.0, "FOREX": 0.6}
