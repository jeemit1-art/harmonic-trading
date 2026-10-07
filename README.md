# Harmonic Pattern Trading Dashboard

A complete system for detecting harmonic chart patterns (Gartley, Bat, Alt
Bat, Butterfly, Crab, Deep Crab, Cypher, Shark) across ASX, US, NSE/BSE, and
Forex, backtesting them properly, and alerting you on Telegram when a
pattern completes with a full entry/stop/target plan.

## Files

| File | Purpose |
|---|---|
| `patterns.py` | Core engine: ZigZag pivot detection + Fibonacci ratio matching for all 8 pattern types |
| `data_sources.py` | Data fetching (yfinance) + watchlists for AUS/US/India/Forex |
| `confluence.py` | RSI divergence, volume climax, higher-timeframe trend filters |
| `backtest.py` | Walk-forward backtester with realistic 3-target scaled exits and transaction costs |
| `scanner.py` | The script that runs on a schedule, scans watchlists, sends Telegram alerts |
| `telegram_alert.py` | Formats and sends the alert messages |
| `dashboard.py` | Streamlit UI: scan any ticker, backtest, watchlist-wide scan |
| `config.py` | All the knobs -- risk %, sensitivity, timeframes, Telegram credentials |
| `DEPLOYMENT.md` | How to get this running 24/7 on a free cloud VM |

## Quick start

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

## The pattern rules used (Scott Carney ratios -- the industry standard)

| Pattern | AB/XA | BC/AB | CD/BC (or CD/XC) | D completion |
|---|---|---|---|---|
| Gartley | 0.618 | 0.382-0.886 | 1.13-1.618 | 0.786 of XA |
| Bat | 0.382-0.50 | 0.382-0.886 | 1.618-2.618 | 0.886 of XA |
| Butterfly | 0.786 | 0.382-0.886 | 1.618-2.24 | 1.27-1.618 of XA |
| Crab | 0.382-0.618 | 0.382-0.886 | 2.24-3.618 | 1.618 of XA |
| Deep Crab | 0.886 | 0.382-0.886 | 2.0-3.618 | 1.618 of XA |
| Cypher | 0.382-0.618 | 1.13-1.414 | 0.786 of **XC** | -- |
| Shark | 0.446-0.618 | 1.13-1.618 | 0.886-1.13 of **XC** | 0.886-1.13 of XA |

The PRZ (Potential Reversal Zone) is the overlap of the D projections from
multiple ratios, not a single number -- that overlap is what the dashboard
shades on the chart.

## Trade management rules (used identically in backtest AND live alerts, so
backtest results actually reflect what the alerts will tell you to do)

- **Entry**: first touch of the PRZ.
- **Stop**: beyond point X + 0.5x ATR(14) buffer (a genuine pattern is
  invalidated if price trades through X).
- **Targets**: scaled exit -- 1/3 off at 0.382 of the CD leg (move stop to
  breakeven), 1/3 off at 0.618 of the CD leg, final 1/3 at point A or
  trailed. This is standard harmonic practice because D-point reversals
  frequently stall well before reaching A.

## What actually improves your edge (the "think of anything else" part)

1. **Confluence filtering is non-negotiable.** Raw ratio-matched patterns
   alone tend to sit around a 45-55% hit rate in independent studies --
   barely better than a coin flip before costs. `confluence.py` checks:
   - **RSI divergence** at D (price makes a new extreme, momentum doesn't)
   - **MACD histogram divergence** at D (a second, independent momentum read)
   - **Volume climax** at D (spike = possible capitulation)
   - **ADX** (patterns fighting a strongly trending market are lower conviction)
   - **Candlestick confirmation** (engulfing / hammer / shooting star within
     3 bars of D) -- **this is the most important filter**. Don't ever enter
     on the raw PRZ touch alone; wait for the market to actually show
     rejection with a real candle.
   - **Higher-timeframe trend alignment**
   The live scanner only fires an **ENTER NOW** alert once a candlestick
   confirmation AND at least one momentum divergence (RSI or MACD) are both
   present -- see "Entry/Exit alerts" below.
2. **Position sizing beats prediction.** ...
3. **Transaction costs are modeled -- don't turn them off.** ...
4. **Correlation risk across your watchlist.** ...
5. **Walk-forward, not whole-history, backtesting.** ...
6. **Paper trade the alerts for at least a month before risking real money.**

## Entry/Exit alerts: ENTER NOW / EXIT NOW

The scanner doesn't just tell you "a pattern exists" -- `trade_manager.py`
tracks every setup through a lifecycle and only pings you when there's an
actual decision to make:

```
WATCHING              pattern forming, price approaching the PRZ (silent by default)
AWAITING_CONFIRMATION D has printed / price is in the PRZ, but no candle
                       confirmation yet -- do NOT enter (silent by default)
   |
   v  (candlestick confirmation + RSI or MACD divergence both land)
OPEN  ---------------> 🟢🟢 ENTER NOW alert (full trade plan: entry/stop/T1/T2/T3)
   |
   v  (price reaches T1)
PARTIAL_T1 -----------> 🟡 EXIT NOW: close 1/3, stop moves to breakeven
   |
   v  (price reaches T2)
PARTIAL_T2 -----------> 🟡 EXIT NOW: close another 1/3
   |
   v  (price reaches T3, or stop is hit)
CLOSED_T3 / CLOSED_STOP -> 🔴 EXIT NOW: close the rest / stopped out
```

State persists in `trade_state.json` between scans (survives cron
restarts), so you get exactly one ENTER NOW alert per setup and one EXIT
alert per target/stop -- no duplicate spam. The dashboard's **Open Trades**
tab shows the same state visually.



## Deployment: GitHub Actions + Render (no VM needed)

GitHub is now central to running this, not optional -- see
`DEPLOYMENT.md` for full step-by-step instructions. The short version:

- **Scanner**: runs on **GitHub Actions** (`.github/workflows/scanner.yml`),
  triggered hourly by GitHub's own free scheduler. No VM, no server, no
  networking configuration. Your Telegram token/chat ID are stored as
  **GitHub Actions secrets** (Settings -> Secrets and variables -> Actions),
  read via environment variables in `config.py` -- never committed as
  plaintext. The workflow commits `trade_state.json` and `leaderboard.json`
  back to the repo after each run so state persists between scans.
- **Dashboard** (optional): deploy to **Render** by connecting your GitHub
  repo through their website -- they build and host it automatically,
  free tier available.

This means `config.py` is safe to commit now (it no longer hardcodes
secrets), unlike earlier versions of this project that assumed a
self-managed VM with a local `config.py` holding the real token.

## Time-to-target estimates

Price *level* targets (T1/T2/T3) are deterministic Fibonacci math, but
price *timing* isn't -- no system can promise "T1 in 3 days." What the
system does instead: every backtest tracks how many bars (and how much
calendar time) past trades actually took to reach each target, and the
**Backtest** tab shows median/average/range per target. The live scanner
uses the same historical data to attach an ETA line to every ENTER NOW
alert, e.g. *"T1 has historically hit in ~4 bars (median) on this
instrument's Gartley trades."* Treat it as a statistical tendency from
real past trades on that instrument, not a prediction -- it gets more
reliable the more historical trades feed it (the alert tells you the
sample size it's based on, and falls back to blended-across-patterns
timing if there aren't enough same-pattern trades yet).

## Profitability add-ons

Win rate alone doesn't determine profitability -- expectancy does:
`(win% x avg win) - (loss% x avg loss)`. Everything below is aimed at
pushing that number up, not just chasing a higher win rate.

**1. Trailing stop after T2** (`config.USE_TRAILING_STOP_AFTER_T2`, on by
default) -- instead of closing the final third at a fixed T3 (point A),
the stop trails behind price by `TRAILING_ATR_MULT x ATR(14)` once T2
hits. Lets strong moves run further than a fixed target would, while
still only ever tightening the stop, never loosening it. Both the live
scanner and the backtester use identical logic, so backtest results
reflect what actually happens live. Toggle off for the original fixed-T3
behaviour.

**2. Performance leaderboard** (`leaderboard.py`) -- tracks realized R
per (market, ticker, pattern) combo from live closed trades (and
optionally backtests, via the **Leaderboard** tab's seed button). Once a
combo has 5+ live trades with negative expectancy, the scanner
automatically suppresses new ENTER NOW alerts for it -- the system learns
what's actually working for you instead of treating every pattern-type
equally forever. Conservative by design: it won't suppress on too little
data, only once there's a real, sizeable losing track record.

**3. Correlation & risk-cap enforcement** (`correlation.py`) -- tags each
ticker with a rough sector/currency bucket and blocks a new ENTER NOW if
it would: exceed `MAX_CONCURRENT_TRADES`, push simultaneous open risk past
`MAX_DAILY_RISK_PCT`, or stack more than `MAX_CORRELATED_TRADES`
same-direction trades in the same bucket (e.g. three different "long
commodities" bets via three different ASX miners isn't three independent
trades). Edit `TICKER_BUCKETS` in `correlation.py` for your own watchlist.

**4. Volatility/liquidity regime filter** (`regime_filter.py`) -- flags
thin-volume periods (holiday windows, or volume that's dried up relative
to its own baseline) and volatility blowouts (ATR in the 90th+ percentile
of its recent history). The scanner won't fire a brand-new ENTER NOW
during a flagged regime, though it still processes exits on already-open
trades normally. Visible on the **Scan Now** tab as a caution banner.

**5. News/earnings blackout** (`news_filter.py`) -- best-effort earnings
date check via yfinance for equities, plus a manually maintained macro
event calendar (`config.NEWS_BLACKOUT_EVENTS`) you populate with events
relevant to your instruments (rate decisions, major data prints). No free
real-time economic calendar API exists that's reliable enough to depend
on for live trading -- this is honest about that rather than pretending
otherwise. A technically perfect pattern means little if earnings drop
tomorrow.

**6. Out-of-sample validation** (**Validation** tab, `walk_forward_validate()`
in `backtest.py`) -- splits history into an in-sample chunk (tune your
`deviation_pct`/`min_quality` against this) and an untouched out-of-sample
chunk (verify against this with the same settings). Flags `overfit_likely`
or `overfit_warning` if out-of-sample expectancy collapses relative to
in-sample -- the standard way harmonic backtests quietly lie to people is
by reporting numbers from settings that were tuned on the same data being
tested.

## Honest limitations

- **yfinance is unofficial and free** -- it can rate-limit, lag, or break.
  Fine for swing-timeframe harmonic trading (1h+), not suitable for
  scalping or anything latency-sensitive.
- **No execution is wired up.** This detects and alerts; it does not place
  orders. That's deliberate -- adding broker execution is a much bigger
  step you should only take after you trust the signal quality, and it
  would need explicit broker API integration (Zerodha Kite / IBKR / OANDA)
  which isn't in this build.
- **No strategy guarantees profit.** Harmonic patterns are a structured way
  to define risk and find statistically-favoured reversal zones, not a
  crystal ball. Every number this system gives you (win rate, R-multiple,
  quality score) is only as good as the backtest period and market regime
  it was measured on -- always re-validate before scaling up size.
