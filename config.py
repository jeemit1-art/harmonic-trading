"""
Central config. Edit these values to tune the system -- nothing else in
the codebase should need touching for day-to-day adjustments.
"""

# --- Telegram -------------------------------------------------------------
# 1. Message @BotFather on Telegram -> /newbot -> copy the token below.
# 2. Message your new bot once (anything), then visit:
#    https://api.telegram.org/bot<TOKEN>/getUpdates
#    and copy the "chat":{"id": ...} value into TELEGRAM_CHAT_ID.
#
# These read from environment variables first (set as GitHub Actions
# secrets when running in the cloud -- see .github/workflows/scanner.yml),
# falling back to the placeholder strings below for local testing. This
# means your real token never needs to be committed to the repo.
import os
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PASTE_YOUR_CHAT_ID_HERE")

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

# --- Recency / actionability filters -----------------------------------------
# A pattern scan looks across the whole SCAN_PERIOD lookback (e.g. 1 year),
# which means it will find plenty of historical patterns that completed
# long ago -- those are NOT live trade signals, just historical structure.
# Only patterns whose D point (or C point, for still-forming patterns)
# happened within this many bars of "now" are treated as live/alertable.
# Note: zigzag pivot confirmation inherently lags by design (it needs
# subsequent price action to confirm a reversal actually happened), so
# this can't be pushed down to just 1-2 bars without also blocking
# genuinely fresh signals -- it's a broad safety net against truly stale
# patterns (weeks/months old), not a tight recency filter on its own.
MAX_PATTERN_AGE_BARS = 25

# The primary, more precise gate: skip ENTER_NOW if current price has
# already moved more than this % away from the entry/PRZ price by the time
# the scan runs. Unlike the bar-count filter above, this directly measures
# whether the trade is still realistically reachable -- this is what stops
# an "entry" price from being announced nowhere near the current market
# price, regardless of how many bars old the underlying pattern is.
# Note: a strong reversal often moves quickly right after D (that's
# actually a good sign, not staleness) -- set this too tight and you'll
# filter out the best-confirming signals along with the genuinely stale
# ones. 5% catches "this happened weeks ago and price moved on" while
# still allowing a fast, strongly-confirming move through.
MAX_ENTRY_DEVIATION_PCT = 5.0

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


# ===========================================================================
# v2 additions -- these drive the shared engine used by BOTH scanner and backtest
# ===========================================================================
# A signal is only "fresh" if its trigger (D confirmed AND confirmation candle)
# happened within this many CLOSED bars of the latest closed bar. Anything older
# is history, not a trade.
FRESH_BARS = 2

# Skip the trade if reward to T2 divided by risk (measured from the REAL entry
# price, not D) is below this. Also used as the "don't chase" price limit.
MIN_RR_T2 = 1.0

# Stop distance sanity (percent of price). Too tight = costs eat the R; too
# wide = the pattern isn't giving you a defined-risk trade.
MIN_STOP_PCT = 0.4
MAX_STOP_PCT = 12.0

# Require RSI/MACD divergence (vs B) in addition to the confirmation candle.
REQUIRE_MOMENTUM = True

# Close any trade still open after this many bars (kills "zombie" trades that
# otherwise sit OPEN forever and block the concurrent-trade cap).
MAX_HOLD_BARS = 40

# Round-trip cost as % of price (spread + slippage + commission). BE HONEST here;
# every backtest number depends on it. Starting guesses, not facts.
COST_PCT = {"AUS": 0.20, "US": 0.08, "INDIA": 0.20, "FOREX": 0.03}

# Same-direction limit for tickers with no entry in correlation.TICKER_BUCKETS
# (they previously each got their own bucket, i.e. no cap at all).
MAX_SAME_DIR_PER_MARKET = 3

# Where the dashboard reads live state from. Set STATE_URL (raw GitHub URL) so the
# dashboard doesn't depend on a redeploy to see fresh state.
STATE_URL = os.environ.get("STATE_URL", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Extra slippage applied to the assumed next-open fill (% of price), on top of COST_PCT.
ENTRY_SLIPPAGE_PCT = 0.0

# Treat the running extreme since point C as a candidate D (earlier, repaint-prone but
# evaluated identically in backtest and live). Turn off to trade confirmed pivots only.
USE_TENTATIVE_D = True

# Send a one-line "scan ok" message per run. A MISSING summary is your dead-man's switch:
# if you stop receiving them, the scheduler/data feed is down.
SEND_SUMMARY = True
