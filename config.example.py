"""
Central config. Edit these values to tune the system -- nothing else in
the codebase should need touching for day-to-day adjustments.
"""

# --- Telegram -------------------------------------------------------------
# 1. Message @BotFather on Telegram -> /newbot -> copy the token below.
# 2. Message your new bot once (anything), then visit:
#    https://api.telegram.org/bot<TOKEN>/getUpdates
#    and copy the "chat":{"id": ...} value into TELEGRAM_CHAT_ID.
TELEGRAM_BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"  # get from @BotFather
TELEGRAM_CHAT_ID = "PASTE_YOUR_CHAT_ID_HERE"

# --- Scanning ---------------------------------------------------------------
# Timeframe per market. Harmonic patterns are structural -- 1h/4h/1d give
# far cleaner, more tradeable swings than anything below 15m (lower
# timeframes are dominated by noise and spread costs, especially forex).
SCAN_TIMEFRAMES = {
    "AUS": "1d",
    "US": "1d",
    "INDIA": "1d",
    "FOREX": "4h",
}

# How much history to pull each scan (needs enough bars to build 5+ swing pivots)
SCAN_PERIOD = {
    "AUS": "1y",
    "US": "1y",
    "INDIA": "1y",
    "FOREX": "180d",
}

# ZigZag sensitivity -- % move required to confirm a new swing pivot.
# Larger = fewer, more significant patterns. Smaller = more patterns, more noise.
ZIGZAG_DEVIATION = {
    "AUS": 3.0, "US": 3.0, "INDIA": 3.0, "FOREX": 0.8,
}

# Minimum ratio-quality score (0-100) to bother alerting on. Backtest
# different thresholds per market/timeframe -- 65+ is a reasonable start.
MIN_QUALITY_SCORE = 65.0

# Fibonacci ratio tolerance band (+/- this amount around each rule's range).
# Tighter = fewer but higher-conviction signals.
RATIO_TOLERANCE = 0.05

# --- Risk management --------------------------------------------------------
RISK_PER_TRADE_PCT = 1.0        # % of account risked per trade
ATR_STOP_BUFFER = 0.5           # extra stop distance beyond X, in multiples of ATR(14)
MAX_CONCURRENT_TRADES = 5       # cap open risk across the whole watchlist
MAX_CORRELATED_TRADES = 2       # max simultaneous same-direction trades in the same sector/currency bucket
MAX_DAILY_RISK_PCT = 3.0        # stop taking new trades once this much is at risk today

# after T2 hits, trail the stop behind price instead of waiting for a fixed
# T3 (point A) -- lets strong moves run further while still locking in gains
# progressively. Set False to use the fixed T3 exit instead.
USE_TRAILING_STOP_AFTER_T2 = True
TRAILING_ATR_MULT = 1.5

# --- News/earnings blackout -------------------------------------------------
# Manually maintained high-impact macro events (no reliable free real-time
# calendar API exists -- see news_filter.py for why). Populate with events
# relevant to your instruments; each blocks ENTER NOW alerts for the listed
# tickers/markets within the given window around the event.
# Example:
# NEWS_BLACKOUT_EVENTS = [
#     {"name": "RBA Rate Decision", "affects": ["AUS", "AUDUSD=X", "AUDJPY=X"],
#      "datetime": "2026-08-12T04:30:00+00:00", "hours_before": 2, "hours_after": 1},
# ]
NEWS_BLACKOUT_EVENTS = []
EARNINGS_BLACKOUT_HOURS_BEFORE = 48
EARNINGS_BLACKOUT_HOURS_AFTER = 24

# --- How often the scanner runs (minutes) when deployed with cron/systemd ---
SCAN_INTERVAL_MINUTES = 60
