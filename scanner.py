"""
Scanner v2. One run = one market, on CLOSED bars only. Order of operations
(the order is the fix for "alerts after the stop was hit"):

  1. fetch closed bars for the whole market (batched)
  2. MANAGE open positions FIRST -- replay every bar since last run, in order,
     handle several transitions at once, alert each exactly once. This happens
     whether or not the pattern is still detectable (v1 only managed trades
     whose pattern was re-detected, so many were never checked again).
  3. look for NEW signals on tickers with no open position
  4. gate (plan geometry, path check, regime, leaderboard, news, risk caps)
  5. queue alerts in the outbox, then deliver; undelivered alerts retry next run
  6. save state atomically

    python scanner.py --market AUS
    python scanner.py --market FOREX --dry-run     # no Telegram, no state write
"""
import argparse, sys, traceback
from datetime import datetime, timezone

import config
import state as st
import leaderboard as lb
import correlation as corr
import regime_filter as rf
import news_filter as nf
import telegram_alert as tg
from data_sources import DEFAULT_SOURCE, WATCHLISTS, is_dead, _load_health
from patterns import find_patterns
from engine import (evaluate_signal, build_plan, check_plan, new_position, advance_position,
                    atr_series, OPEN_STATES)
from confluence import score_confluence

ALERT_ON_WATCHING = False       # forming-pattern heads-up (noisy; off by default)


def _log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}", flush=True)


def _once(state, key, ttl_note="") -> bool:
    """True the first time a key is seen (used to avoid logging the same suppression every run)."""
    if key in state["seen"]:
        return False
    state["seen"][key] = st.now_iso()
    return True


def manage_positions(state: dict, board: dict, market: str, ticker: str, df, atr) -> int:
    n = 0
    for pid, pos in list(state["positions"].items()):
        if pos["market"] != market or pos["ticker"] != ticker:
            continue
        pos["last_close"], pos["last_close_ts"], pos["data_fail_runs"] = float(df["Close"].iloc[-1]), str(df.index[-1]), 0
        for ev in advance_position(pos, df, atr):
            st.queue_alert(state, tg.fmt_event(pos, ev), ev["type"], ticker, pid)
            _log(f"{ev['type']} {market} {ticker} {pos['pattern']} @ {ev['price']:.5f}")
            n += 1
        if pos["status"].startswith("CLOSED"):
            state["closed"].append(pos)
            del state["positions"][pid]
            if pos.get("r_multiple") is not None and pos["status"] != "CLOSED_INVALIDATED":
                lb.record_outcome(board, market, ticker, pos["pattern"], pos["r_multiple"], source="live")
    return n


def find_new_signal(state, market, ticker, df, atr, deviation):
    patterns = find_patterns(df, deviation_pct=deviation, tolerance=config.RATIO_TOLERANCE,
                             include_forming=False, include_tentative=config.USE_TENTATIVE_D)
    close = float(df["Close"].iloc[-1])
    cands = []
    for p in patterns:
        if p.D is None:
            continue
        sig = evaluate_signal(df, p)
        if sig is None:
            continue
        sid = f"{ticker}:{p.direction.value}:{p.D.timestamp}"
        if sid in state["seen"]:
            continue
        plan = build_plan(df, p, atr)
        ok, why = check_plan(df, p, plan, close)
        if not ok:
            state["seen"][sid] = st.now_iso()            # definitive: don't re-evaluate every run
            st.log_decision(state, market, ticker, f"REJECTED {p.name}", why)
            continue
        cands.append((p.quality_score, p, plan, sid, sig))
    return max(cands, key=lambda c: c[0]) if cands else None


def process_ticker(state, board, market, ticker, df, tf, dry) -> tuple[int, int]:
    deviation = config.ZIGZAG_DEVIATION[market]
    atr = atr_series(df)
    n_events = manage_positions(state, board, market, ticker, df, atr)
    if any(p["ticker"] == ticker and p["market"] == market for p in state["positions"].values()):
        return n_events, 0                                  # one position per ticker

    best = find_new_signal(state, market, ticker, df, atr, deviation)
    if best is None:
        return n_events, 0
    _, p, plan, sid, sig = best

    def suppress(kind, why):
        if _once(state, f"{sid}|{kind}"):
            st.log_decision(state, market, ticker, f"SUPPRESSED {p.name} ({kind})", why)
            _log(f"SUPPRESSED ({kind}) {market} {ticker} {p.name}: {why}")
        return n_events, 0

    regime = rf.assess_regime(df, atr)
    if not regime["tradeable_regime"]:
        return suppress("regime", f"{regime['volume']['note']} {regime['volatility']['note']}")
    sup = lb.should_suppress(board, market, ticker, p.name)
    if sup["suppress"]:
        return suppress("leaderboard", sup["reason"])
    news = nf.check_news_blackout(ticker, market)
    if news["blackout"]:
        return suppress("news", f"{news['earnings'].get('note','')} {news['macro'].get('note','')}")
    caps = corr.check_risk_caps(state["positions"], market, ticker, p.name, p.direction.value)
    if not caps["allowed"]:
        return suppress("risk_cap", caps["reason"])

    conf = score_confluence(df, p)
    pos = new_position(p, plan, market, ticker, tf, df.index[-1], sid,
                       {"candle": sig["candle"].get("type"), "rsi": sig["rsi"].get("has_divergence"),
                        "macd": sig["macd"].get("has_divergence"), "adx": conf["adx"].get("adx"),
                        "adjusted_score": conf["adjusted_score"], "tentative_D": p.tentative})
    close = float(df["Close"].iloc[-1])
    notes = [f"Trigger: {sig['candle'].get('type')} candle at the PRZ"
             + (" (D not yet a confirmed pivot -- early entry)" if p.tentative else ""),
             f"Momentum: RSI div {sig['rsi'].get('has_divergence')}, MACD div {sig['macd'].get('has_divergence')}",
             f"Ratios: " + ", ".join(f"{k} {v}" for k, v in p.ratios.items() if v is not None),
             f"HTF/ADX: {conf['adx']['note']}"]
    if not dry:
        try:
            from chart_image import generate_pattern_chart
            img = generate_pattern_chart(df, p, close, plan["stop"], plan["t1"], plan["t2"], plan["t3"],
                                         ticker, market, tf, status="SIGNAL")
            tg.send_photo(img, caption=f"{ticker} {p.name} {'LONG' if pos['direction']=='bullish' else 'SHORT'}")
        except Exception as e:
            _log(f"chart failed for {ticker}: {e}")
    state["positions"][pos["id"]] = pos
    state["seen"][sid] = st.now_iso()
    st.queue_alert(state, tg.fmt_signal(pos, close, notes), "SIGNAL", ticker, pos["id"])
    _log(f"SIGNAL {market} {ticker} {p.name} q={p.quality_score} stop={plan['stop']:.5f}")
    return n_events, 1


def run_scan(markets=None, dry=False, state_path=None) -> dict:
    state, board = st.load(state_path), lb.load_leaderboard()
    markets = markets or list(WATCHLISTS.keys())
    for market in markets:
        tf, period = config.SCAN_TIMEFRAMES[market], config.SCAN_PERIOD[market]
        health = _load_health()
        tickers = [t for t in WATCHLISTS[market] if not is_dead(health, t)]
        _log(f"== {market}: {len(tickers)} active of {len(WATCHLISTS[market])} listed, {tf}, {period}")
        try:
            data = DEFAULT_SOURCE.fetch_many(tickers, tf, period, market)
        except Exception as e:
            _log(f"fetch failed for {market}: {e}")
            traceback.print_exc()
            data = {}
        signals = events = 0
        for ticker in tickers:
            df = data.get(ticker)
            if df is None or len(df) < 60:
                for pos in state["positions"].values():          # tell the user if an OPEN trade went blind
                    if pos["ticker"] == ticker and pos["market"] == market:
                        pos["data_fail_runs"] = pos.get("data_fail_runs", 0) + 1
                        if pos["data_fail_runs"] == 3:
                            st.queue_alert(state, f"DATA PROBLEM: no price data for {ticker} for 3 runs. "
                                                  f"Open {pos['pattern']} trade is NOT being tracked -- manage it manually.",
                                           "DATA", ticker, pos["id"])
                continue
            try:
                e, s = process_ticker(state, board, market, ticker, df, tf, dry)
                events, signals = events + e, signals + s
            except Exception as ex:
                _log(f"ERROR {market}:{ticker} -- {ex}")
                traceback.print_exc()
        ok = len(data) >= 0.5 * len(tickers)
        state["meta"]["markets"][market] = {
            "last_run": st.now_iso(), "last_success": st.now_iso() if ok else state["meta"]["markets"].get(market, {}).get("last_success"),
            "tickers_ok": len(data), "tickers_total": len(tickers), "signals": signals, "events": events}
        n_open = sum(1 for p in state["positions"].values() if p["market"] == market)
        st.queue_alert(state, f"{'SCAN OK' if ok else 'SCAN DEGRADED'} {market} {tf}: {len(data)}/{len(tickers)} tickers, "
                              f"{signals} new signal(s), {events} trade event(s), {n_open} open.", "SUMMARY") \
            if getattr(config, "SEND_SUMMARY", True) else None
    state["meta"]["last_run"] = st.now_iso()
    if not dry:
        _log(f"delivery: {tg.flush_outbox(state)}")
        st.save(state, state_path)
        lb.save_leaderboard(board)
    return state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=list(WATCHLISTS.keys()))
    ap.add_argument("--dry-run", action="store_true", help="no Telegram, no state write")
    a = ap.parse_args()
    run_scan([a.market] if a.market else None, dry=a.dry_run)
