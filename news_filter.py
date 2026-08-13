"""
News / earnings blackout filter.

Honest limitation up front: there is no reliable, free, real-time
economic calendar API for macro events (rate decisions, CPI prints, NFP,
etc.) that's safe to depend on for live trading. Paid options exist
(ForexFactory has no public API, TradingEconomics/FXStreet APIs are paid).
So this module does two things:

  1. Earnings dates -- fetched from yfinance where available (equities
     only; best-effort, coverage varies by exchange and can be stale).
  2. Macro events -- a manually maintained calendar in config.py
     (NEWS_BLACKOUT_EVENTS) that YOU populate with known high-impact
     events (central bank meetings, major data releases) relevant to
     your instruments. This isn't automatic, but it's honest and free,
     rather than pretending to have real-time macro coverage it doesn't.

If you want fully automated macro-event blackouts, wiring in a paid
calendar API (TradingEconomics, FXStreet) is a small addition to
`check_macro_blackout()` below -- swap the config-list lookup for an API call.
"""
from datetime import datetime, timedelta, timezone
import config

try:
    import yfinance as yf
except ImportError:
    yf = None


def check_earnings_blackout(ticker: str, hours_before: int = 48, hours_after: int = 24) -> dict:
    """
    Best-effort earnings-date check via yfinance. Returns flag=None (not
    flag=False) when data isn't available, so callers can distinguish
    "checked and clear" from "couldn't check" -- don't let a data gap
    silently look like a clean bill of health.
    """
    if yf is None:
        return {"flag": None, "note": "yfinance not available -- could not check earnings date."}
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if not cal:
            return {"flag": None, "note": "No earnings date data available for this ticker."}
        earnings_date = None
        if isinstance(cal, dict) and "Earnings Date" in cal:
            ed = cal["Earnings Date"]
            earnings_date = ed[0] if isinstance(ed, (list, tuple)) and ed else ed
        if earnings_date is None:
            return {"flag": None, "note": "No earnings date data available for this ticker."}

        if not isinstance(earnings_date, datetime):
            earnings_date = datetime.combine(earnings_date, datetime.min.time())
        earnings_date = earnings_date.replace(tzinfo=timezone.utc) if earnings_date.tzinfo is None else earnings_date

        now = datetime.now(timezone.utc)
        window_start = earnings_date - timedelta(hours=hours_before)
        window_end = earnings_date + timedelta(hours=hours_after)
        in_blackout = window_start <= now <= window_end

        return {
            "flag": in_blackout,
            "earnings_date": earnings_date.isoformat(),
            "note": (f"Earnings on {earnings_date.date()} -- within the {hours_before}h/{hours_after}h "
                     f"blackout window. Pattern structure is unreliable here regardless of ratio quality."
                     if in_blackout else f"Next earnings: {earnings_date.date()} -- outside blackout window.")
        }
    except Exception as e:
        return {"flag": None, "note": f"Could not fetch earnings data: {e}"}


def check_macro_blackout(ticker: str, market: str) -> dict:
    """
    Checks the manually maintained NEWS_BLACKOUT_EVENTS list in config.py.
    Populate it with events relevant to your instruments, e.g.:

        NEWS_BLACKOUT_EVENTS = [
            {"name": "RBA Rate Decision", "affects": ["AUS", "AUDUSD=X", "AUDJPY=X"],
             "datetime": "2026-08-12T04:30:00+00:00", "hours_before": 2, "hours_after": 1},
        ]
    """
    events = getattr(config, "NEWS_BLACKOUT_EVENTS", [])
    now = datetime.now(timezone.utc)
    for event in events:
        affects = event.get("affects", [])
        if ticker not in affects and market not in affects:
            continue
        try:
            event_time = datetime.fromisoformat(event["datetime"])
        except (KeyError, ValueError):
            continue
        window_start = event_time - timedelta(hours=event.get("hours_before", 2))
        window_end = event_time + timedelta(hours=event.get("hours_after", 1))
        if window_start <= now <= window_end:
            return {"flag": True, "event": event["name"],
                    "note": f"{event['name']} at {event_time.isoformat()} -- within blackout window."}
    return {"flag": False, "note": "No configured macro events in blackout window."}


def check_news_blackout(ticker: str, market: str) -> dict:
    """Combined check -- call this once per ticker before firing ENTER NOW."""
    earnings = check_earnings_blackout(ticker) if market != "FOREX" else {"flag": None, "note": "N/A for forex."}
    macro = check_macro_blackout(ticker, market)
    blackout = bool(earnings.get("flag")) or bool(macro.get("flag"))
    return {"blackout": blackout, "earnings": earnings, "macro": macro}
