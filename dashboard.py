"""
Monitoring dashboard. Answers, in order: is the system alive? what do I hold and
how close is it to stop/targets? what has it actually earned? why did/didn't it alert?

State source: config.STATE_URL (raw GitHub URL, optionally with GITHUB_TOKEN) so the
dashboard sees fresh state without a redeploy; falls back to the local state file.
"""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import config
import state as stt
from data_sources import DEFAULT_SOURCE, WATCHLISTS, DEFAULT_DEVIATION
from engine import OPEN_STATES

st.set_page_config(page_title="Harmonic Monitor", layout="wide", page_icon="\U0001F4C8")


@st.cache_data(ttl=60)
def load_state() -> dict:
    if config.STATE_URL:
        h = {"Authorization": f"token {config.GITHUB_TOKEN}"} if config.GITHUB_TOKEN else {}
        r = requests.get(config.STATE_URL, headers=h, timeout=15)
        r.raise_for_status()
        s = stt.empty(); s.update(r.json())
        return s
    return stt.load()


def age(iso):
    if not iso:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


def r_now(p):
    if p.get("entry") is None or p.get("last_close") is None:
        return None
    s = 1 if p["direction"] == "bullish" else -1
    risk = abs(p["entry"] - p["orig_stop"])
    open_r = s * (p["last_close"] - p["entry"]) / risk
    return p.get("realized_r", 0.0) + p.get("fraction_remaining", 1.0) * open_r


st.title("Harmonic Monitor")
try:
    S = load_state()
except Exception as e:
    st.error(f"Could not load state: {e}")
    st.stop()

tab_h, tab_o, tab_c, tab_l, tab_b = st.tabs(["Health", "Open trades", "Results", "Alerts & decisions", "Backtest"])

# ------------------------------------------------------------------ HEALTH
with tab_h:
    # expected max age (hours) before a market scan is considered overdue
    limits = {"AUS": 30, "US": 30, "INDIA": 30, "FOREX": 6}
    cols = st.columns(len(WATCHLISTS))
    for col, m in zip(cols, WATCHLISTS):
        mm = S["meta"]["markets"].get(m)
        if not mm:
            col.metric(m, "never ran"); continue
        a = age(mm.get("last_success"))
        bad = a is None or a > limits[m] or mm["tickers_ok"] < 0.8 * mm["tickers_total"]
        col.metric(f"{'🔴' if bad else '🟢'} {m}", f"{a:.1f}h ago" if a is not None else "no success",
                   f"{mm['tickers_ok']}/{mm['tickers_total']} tickers")
    c1, c2, c3 = st.columns(3)
    c1.metric("Alerts waiting to be delivered", len(S["outbox"]))
    c2.metric("Open / pending trades", len(S["positions"]))
    c3.metric("Closed trades recorded", len(S["closed"]))
    if S["outbox"]:
        st.warning("Undelivered alerts (Telegram failing?): " + "; ".join(f"{a['kind']} {a['ticker']} ({a.get('last_error','')[:60]})" for a in S["outbox"][:5]))

# ------------------------------------------------------------------ OPEN
with tab_o:
    if not S["positions"]:
        st.info("No open or pending trades.")
    else:
        rows = []
        for pid, p in S["positions"].items():
            s = 1 if p["direction"] == "bullish" else -1
            lc = p.get("last_close")
            rows.append({"Ticker": p["ticker"], "Side": "LONG" if s == 1 else "SHORT", "Pattern": p["pattern"], "Status": p["status"],
                         "Entry": p.get("entry"), "Last close": lc, "Stop": round(p["stop"], 5), "T1": round(p["t1"], 5), "T2": round(p["t2"], 5),
                         "R now": None if r_now(p) is None else round(r_now(p), 2),
                         "To stop %": None if lc is None else round(s * (lc - p["stop"]) / lc * 100, 2),
                         "To T1 %": None if lc is None else round(s * (p["t1"] - lc) / lc * 100, 2),
                         "Bars held": p.get("bars_held"), "Do not chase past": round(p["max_chase"], 5) if p["status"] == "PENDING" else None,
                         "id": pid})
        df = pd.DataFrame(rows)
        sel = st.dataframe(df.drop(columns="id"), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
        st.caption("Prices are the last CLOSED bar at the last scan -- this is a monitor, not a live feed. Keep a real stop order at your broker.")
        if sel.selection.rows:
            p = S["positions"][df.iloc[sel.selection.rows[0]]["id"]]
            try:
                d = DEFAULT_SOURCE.fetch(p["ticker"], p["timeframe"], config.SCAN_PERIOD[p["market"]], p["market"])
                fig = go.Figure(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close))
                for name, y, col in [("Stop", p["stop"], "#ff5c6c"), ("T1", p["t1"], "#26d98c"), ("T2", p["t2"], "#26d98c"), ("T3", p["t3"], "#26d98c")] + \
                                    ([("Entry", p["entry"], "#F5A623")] if p.get("entry") else []):
                    fig.add_hline(y=y, line_color=col, line_dash="dot", annotation_text=f"{name} {y:.4f}")
                pts = [p["points"][k] for k in "XABCD" if p.get("points", {}).get(k)]
                if pts:
                    fig.add_trace(go.Scatter(x=[q["timestamp"] for q in pts], y=[q["price"] for q in pts], mode="lines+markers+text",
                                             text=list("XABCD")[:len(pts)], line=dict(color="#9C8CFF")))
                fig.update_layout(template="plotly_dark", height=620, xaxis_rangeslider_visible=False, margin=dict(t=30, b=10))
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.warning(f"Chart unavailable: {e}")

# ------------------------------------------------------------------ RESULTS
with tab_c:
    cl = [c for c in S["closed"] if c.get("r_multiple") is not None and c["status"] != "CLOSED_INVALIDATED"]
    if not cl:
        st.info("No closed trades yet. Until you have 30+, treat every statistic here as noise.")
    else:
        df = pd.DataFrame(cl).sort_values("closed_at")
        r = df["r_multiple"].astype(float)
        boots = np.random.default_rng(1).choice(r.values, (2000, len(r))).mean(axis=1)
        a, b, c_, d = st.columns(4)
        a.metric("Trades", len(r)); b.metric("Win rate", f"{(r > 0).mean():.0%}")
        c_.metric("Expectancy", f"{r.mean():+.2f}R", f"5th pct {np.percentile(boots, 5):+.2f}R")
        d.metric("Total", f"{r.sum():+.1f}R")
        if len(r) < 30:
            st.warning(f"Only {len(r)} closed trades: the confidence band is huge. Don't scale up on this.")
        eq = r.cumsum()
        fig = go.Figure(go.Scatter(x=df["closed_at"], y=eq, mode="lines+markers", line=dict(color="#26a69a")))
        fig.update_layout(template="plotly_dark", title="Cumulative R", height=330, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
        g = df.groupby(["market", "pattern"])["r_multiple"].agg(["count", "mean", lambda x: (x > 0).mean()])
        g.columns = ["n", "avg R", "win rate"]
        st.dataframe(g.round(2), use_container_width=True)
        st.dataframe(df[["closed_at", "market", "ticker", "pattern", "direction", "status", "entry", "exit_price", "r_multiple", "bars_held"]].tail(100)
                     .iloc[::-1], use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ ALERTS
with tab_l:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Delivered alerts")
        for a in reversed(S["alert_log"][-40:]):
            with st.expander(f"{a['t'][:16]}  {a['kind']}  {a['ticker']}"):
                st.text(a["text"])
    with c2:
        st.subheader("Why a signal did NOT alert")
        d = pd.DataFrame(S["decisions"][-150:][::-1])
        st.dataframe(d if len(d) else pd.DataFrame({"info": ["nothing suppressed yet"]}), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ BACKTEST
with tab_b:
    st.caption("Same engine as the live scanner. Pool several tickers: a single ticker produces too few trades to mean anything.")
    m = st.selectbox("Market", list(WATCHLISTS))
    n = st.slider("Tickers to pool", 3, 40, 12)
    period = st.selectbox("History", ["2y", "5y", "10y"], index=1) if config.SCAN_TIMEFRAMES[m] == "1d" else "730d"
    if st.button("Run pooled backtest"):
        from backtest import run_backtest, summarize
        tf = config.SCAN_TIMEFRAMES[m]
        data = DEFAULT_SOURCE.fetch_many(WATCHLISTS[m][:n], tf, period, m)
        allp = []
        bar = st.progress(0)
        for i, (t, d) in enumerate(data.items()):
            res = run_backtest(d, market=m, ticker=t, timeframe=tf, deviation_pct=config.ZIGZAG_DEVIATION[m])
            allp += res.get("trades", [])
            bar.progress((i + 1) / len(data))
        pooled = summarize(allp, 10000, config.RISK_PER_TRADE_PCT)
        if pooled["n_trades"] == 0:
            st.warning("No trades.")
        else:
            x = st.columns(5)
            x[0].metric("Trades", pooled["n_trades"]); x[1].metric("Win rate", f"{pooled['win_rate_pct']}%")
            x[2].metric("Expectancy", f"{pooled['expectancy_r']}R"); x[3].metric("5th pct (bootstrap)", f"{pooled['expectancy_r_p5']}R")
            x[4].metric("Max DD", f"{pooled['max_drawdown_pct']}%")
            st.write("Go/no-go: need >=100 pooled trades AND 5th-percentile expectancy > 0 AND a positive out-of-sample half.")
            st.dataframe(pd.DataFrame(pooled["by_pattern"]).T)
