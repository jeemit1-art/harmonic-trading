"""
Market scanner. Run this on a schedule (cron / systemd timer, see
DEPLOYMENT.md) on your cloud VM. Each run:

  1. Pulls latest data for every ticker in every watchlist.
  2. Checks the volatility/liquidity regime -- skips tickers in a known
     bad regime (thin volume, extreme volatility, holiday period).
  3. Detects confirmed AND forming harmonic patterns.
  4. Scores confluence (RSI/MACD divergence, volume, ADX, candlestick
     confirmation, higher-timeframe trend).
  5. Checks the leaderboard -- suppresses ENTER NOW for (market, ticker,
     pattern) combos with a demonstrably weak track record.
  6. Checks news/earnings blackout -- suppresses ENTER NOW near known
     high-impact events.
  7. Checks risk/correlation caps -- suppresses ENTER NOW if it would
     breach max concurrent trades, max daily risk, or correlated exposure.
  8. Advances each setup's tracked state (trade_manager.py) and fires the
     appropriate explicit alert: WATCHING, AWAITING confirmation,
     ENTER NOW, or EXIT NOW (partial/full/stop/trailing-stop).
  9. Records closed trades to the leaderboard for future suppression checks.

Usage:
    python3 scanner.py                 # scan everything once
    python3 scanner.py --market FOREX  # scan a single market
"""
import argparse
import sys
import traceback
from datetime import datetime, timezone

import pandas as pd

import config
from data_sources import DEFAULT_SOURCE, WATCHLISTS
from patterns import find_patterns
from confluence import score_confluence
from telegram_alert import (send_telegram_message, format_pattern_alert, format_action_alert,
                             send_telegram_photo, format_enter_now_caption)
from backtest import _atr, estimate_time_to_targets
import trade_manager as tm
import leaderboard as lb
import correlation as corr
import regime_filter as rf
import news_filter as nf
from chart_image import generate_pattern_chart

# Only these actions actually get pushed to Telegram by default -- WATCHING
# alerts are informational and can flood your phone if left on. Flip
# ALERT_ON_WATCHING to True if you want the heads-up messages too.
ALERT_ON_WATCHING = False
ALERT_ON_AWAITING = False

CLOSED_ACTIONS = ("EXIT_FULL_T3", "EXIT_STOP", "EXIT_TRAILING_STOP")
PARTIAL_ACTIONS = ("EXIT_PARTIAL_T1", "EXIT_PARTIAL_T2")


def scan_ticker(market: str, ticker: str, state: dict, board: dict) -> int:
    tf = config.SCAN_TIMEFRAMES[market]
    period = config.SCAN_PERIOD[market]
    deviation = config.ZIGZAG_DEVIATION[market]

    df = DEFAULT_SOURCE.fetch(ticker, interval=tf, period=period)
    if len(df) < 60:
        return 0

    atr = _atr(df)
    current_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else None

    # regime check -- skip new entries (but still process existing open
    # trades' exits below) if conditions are bad for trusting new signals
    regime = rf.assess_regime(df, atr)
    regime_ok = regime["tradeable_regime"]
    if not regime_ok:
        print(f"[{datetime.now(timezone.utc).isoformat()}] REGIME WARNING {market} {ticker}: "
              f"{regime['volume']['note']} {regime['volatility']['note']}")

    patterns = find_patterns(df, deviation_pct=deviation, tolerance=config.RATIO_TOLERANCE)
    if not patterns:
        return 0

    htf_df = None
    try:
        if tf != "1d":
            htf_df = DEFAULT_SOURCE.fetch(ticker, interval="1d", period="2y")
    except Exception:
        htf_df = None

    current_price = float(df['Close'].iloc[-1])
    n_sent = 0

    for p in patterns:
        if p.quality_score < config.MIN_QUALITY_SCORE:
            continue

        bullish = p.direction.value == "bullish"
        key_point = p.D.index if p.D is not None else p.C.index

        # RECENCY FILTER: skip anything whose reversal point isn't recent.
        # Without this, a scan of a year of history will happily surface
        # patterns that completed months ago as if they were live signals --
        # that's how you get an "entry" price nowhere near the current
        # market price. Only patterns within the last MAX_PATTERN_AGE_BARS
        # bars are considered live/actionable.
        bars_old = (len(df) - 1) - key_point
        if bars_old > config.MAX_PATTERN_AGE_BARS:
            continue

        # STABLE setup ID: use the pivot's actual timestamp, not its
        # positional array index. The lookback window slides forward every
        # scan (old bars age out, new ones arrive), so a positional index
        # for the same real-world pivot can drift between runs -- using the
        # timestamp instead means the same real pattern is recognized as
        # "already tracked" correctly across scans, rather than looking
        # like a brand new setup every single run.
        x_key = p.X.timestamp.isoformat() if hasattr(p.X.timestamp, "isoformat") else str(p.X.timestamp)
        setup_id = tm.make_setup_id(market, ticker, tf, p.name, x_key)

        conf = score_confluence(df, p, htf_df=htf_df)

        if p.D is not None:
            entry = p.D.price
        else:
            entry = (p.prz_lo + p.prz_hi) / 2

        idx = min(key_point, len(atr) - 1)
        buffer = (atr.iloc[idx] if not pd.isna(atr.iloc[idx]) else 0) * config.ATR_STOP_BUFFER
        stop = (p.X.price - buffer) if bullish else (p.X.price + buffer)
        cd_leg = abs(p.C.price - entry)
        t1 = entry + 0.382 * cd_leg if bullish else entry - 0.382 * cd_leg
        t2 = entry + 0.618 * cd_leg if bullish else entry - 0.618 * cd_leg
        t3 = p.A.price

        # ACTIONABILITY CHECK: even a recent pattern can already be "missed"
        # if price has run away from entry by the time the scan runs. Skip
        # rather than alert on an entry that's no longer realistically
        # reachable at a sane risk:reward.
        entry_deviation_pct = abs(current_price - entry) / entry * 100 if entry else 0
        price_still_actionable = entry_deviation_pct <= config.MAX_ENTRY_DEVIATION_PCT

        # gate entry_ready further: regime must be OK, and price must still
        # be actionable -- checked BEFORE calling update_setup so a bad
        # regime/stale price prevents a brand new ENTER_NOW from ever being
        # created (existing open trades still get their exits processed
        # normally regardless)
        gated_conf = dict(conf)
        if not regime_ok and setup_id not in state:
            gated_conf["entry_ready"] = False
        if not price_still_actionable and setup_id not in state:
            gated_conf["entry_ready"] = False

        result = tm.update_setup(state, setup_id, market, ticker, tf, p, gated_conf,
                                  current_price, entry, stop, t1, t2, t3, atr=current_atr)
        action = result["action"]
        setup = result["setup"]

        if action == "ENTER_NOW":
            # leaderboard suppression check
            suppress = lb.should_suppress(board, market, ticker, p.name)
            if suppress["suppress"]:
                print(f"[{datetime.now(timezone.utc).isoformat()}] SUPPRESSED (leaderboard) "
                      f"{market} {ticker} {p.name}: {suppress['reason']}")
                # roll the state back to AWAITING so it can re-trigger later if the
                # track record improves, rather than silently losing the setup
                setup["status"] = "AWAITING_CONFIRMATION"
                continue

            # news/earnings blackout check
            news = nf.check_news_blackout(ticker, market)
            if news["blackout"]:
                print(f"[{datetime.now(timezone.utc).isoformat()}] SUPPRESSED (news blackout) "
                      f"{market} {ticker} {p.name}: {news['earnings']['note']} {news['macro']['note']}")
                setup["status"] = "AWAITING_CONFIRMATION"
                continue

            # risk/correlation cap check
            risk_check = corr.check_risk_caps(state, market, ticker, p.name, p.direction.value)
            if not risk_check["allowed"]:
                print(f"[{datetime.now(timezone.utc).isoformat()}] SUPPRESSED (risk cap) "
                      f"{market} {ticker} {p.name}: {risk_check['reason']}")
                setup["status"] = "AWAITING_CONFIRMATION"
                continue

            eta = None
            try:
                eta = estimate_time_to_targets(df, p.name, deviation_pct=deviation,
                                                tolerance=config.RATIO_TOLERANCE)
            except Exception:
                pass

            # send the chart image first (with a short caption), then the
            # full detailed text -- if image generation fails for any
            # reason, fall back to text-only rather than losing the alert
            try:
                img_bytes = generate_pattern_chart(df, p, entry, stop, t1, t2, t3,
                                                    ticker, market, tf, status="CONFIRMED")
                caption = format_enter_now_caption(setup, current_price, confluence=conf)
                send_telegram_photo(img_bytes, caption=caption)
            except Exception as e:
                print(f"[scanner] Chart image generation/send failed for {ticker}: {e}")

            msg = format_action_alert("ENTER_NOW", setup, current_price, confluence=conf, eta=eta)
            ok = send_telegram_message(msg)
            n_sent += 1
            print(f"[{datetime.now(timezone.utc).isoformat()}] ENTER_NOW {market} {ticker} "
                  f"{p.name} score={p.quality_score} {'sent' if ok else 'queued (no telegram)'}")

        elif action in PARTIAL_ACTIONS + CLOSED_ACTIONS:
            msg = format_action_alert(action, setup, current_price)
            ok = send_telegram_message(msg)
            n_sent += 1
            print(f"[{datetime.now(timezone.utc).isoformat()}] {action} {market} {ticker} {p.name} "
                  f"{'sent' if ok else 'queued (no telegram)'}")

            if action in CLOSED_ACTIONS:
                # record the realized outcome to the leaderboard. Approximate
                # the closed trade's blended R the same way the backtester
                # does isn't available live without re-deriving it exactly,
                # so use the fraction-weighted price move vs initial risk as
                # a reasonable live proxy.
                initial_risk = abs(setup["entry"] - setup.get("original_stop", setup["entry"]))
                if initial_risk > 0:
                    sign = 1 if bullish else -1
                    approx_r = sign * (current_price - setup["entry"]) / initial_risk
                    board = lb.record_outcome(board, market, ticker, p.name, approx_r, source="live")

        elif action == "SETUP_INVALIDATED":
            print(f"[{datetime.now(timezone.utc).isoformat()}] INVALIDATED {market} {ticker} {p.name}")

        elif action == "AWAITING" and ALERT_ON_AWAITING:
            msg = format_pattern_alert(market, ticker, tf, p, entry, stop, t1, t2, t3, conf, "WATCHING")
            send_telegram_message(msg)
            n_sent += 1

        elif action == "WATCHING" and ALERT_ON_WATCHING:
            msg = format_pattern_alert(market, ticker, tf, p, entry, stop, t1, t2, t3, conf, "WATCHING")
            send_telegram_message(msg)
            n_sent += 1

    return n_sent


def run_scan(markets: list[str] = None):
    markets = markets or list(WATCHLISTS.keys())
    state = tm.load_state()
    board = lb.load_leaderboard()
    total_new = 0

    for market in markets:
        for ticker in WATCHLISTS[market]:
            try:
                total_new += scan_ticker(market, ticker, state, board)
            except Exception as e:
                print(f"[scanner] ERROR scanning {market}:{ticker} -- {e}", file=sys.stderr)
                traceback.print_exc()

    state = tm.prune_closed(state)
    tm.save_state(state)
    lb.save_leaderboard(board)
    print(f"\nScan complete. {total_new} alert(s) sent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=list(WATCHLISTS.keys()), default=None,
                         help="Scan a single market only (default: all)")
    args = parser.parse_args()
    run_scan([args.market] if args.market else None)
