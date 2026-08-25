"""
Harmonic Trading Dashboard (Streamlit).

Run with:  streamlit run dashboard.py

Tabs:
  1. Scan Now       -- pick a market/ticker, run pattern detection live, see chart + trade plan
  2. Backtest        -- run the backtester over any ticker/date range, see full stats + equity curve
  3. Watchlist Scan   -- run pattern detection across an entire watchlist at once
  4. Settings         -- view/edit the risk & sensitivity config being used
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from data_sources import DEFAULT_SOURCE, WATCHLISTS, DEFAULT_DEVIATION
from patterns import find_patterns, PATTERN_RULES
from backtest import backtest, _atr
from confluence import score_confluence, rsi
import trade_manager as tm
import leaderboard as lb

st.set_page_config(page_title="Harmonic \u00b7 Pattern Terminal", layout="wide", page_icon="\U0001F9ED")

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
# The subject here is literally a drafting instrument: ratio-measured
# geometry (X-A-B-C-D) laid over price. Palette and type lean into that --
# an ink-dark ground, a brass "instrument" accent for structure/actions, and
# desaturated teal/coral/steel for bullish/bearish/watching states (not the
# generic single neon-on-black look). Space Grotesk carries the geometric
# display role, Plex Sans is body text, Plex Mono is reserved for anything
# that is a number a trader has to read precisely.
BRAND_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
    --bg: #0A0D12;
    --panel: #10141B;
    --panel-2: #151B24;
    --border: #232A38;
    --text: #E7E9EE;
    --muted: #8890A2;
    --brass: #C9A45C;
    --brass-dim: #8C6F3E;
    --teal: #4FB0A2;
    --coral: #E2685F;
    --steel: #6C9BD1;
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif; }
.stApp { background: var(--bg); }
.block-container { padding-top: 1.4rem; max-width: 1400px; }

/* ---- typography ------------------------------------------------------ */
h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif; font-weight: 600 !important;
                 letter-spacing: -0.01em; color: var(--text); }
h3 { color: var(--text) !important; margin-top: 0.2em; }
p, li, span, label { color: var(--text); }
.stCaption, [data-testid="stCaptionContainer"] { color: var(--muted) !important; }
code { color: var(--brass); background: var(--panel-2) !important; }

/* ---- masthead ---------------------------------------------------------- */
.hpt-masthead { display: flex; align-items: center; gap: 14px; padding-bottom: 4px; }
.hpt-wordmark { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.7rem;
                color: var(--text); letter-spacing: -0.01em; }
.hpt-wordmark span { color: var(--brass); }
.hpt-tagline { color: var(--muted); font-size: 0.86rem; margin-top: -2px; }

/* ---- tabs: underline instrument-rail nav, not boxy browser tabs ------ */
.stTabs [data-baseweb="tab-list"] {
    gap: 26px; border-bottom: 1px solid var(--border); margin-bottom: 6px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent; padding: 8px 2px 12px 2px; color: var(--muted);
    font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 0.92rem;
    border: none; border-bottom: 2px solid transparent;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text); }
.stTabs [aria-selected="true"] {
    background: transparent !important; color: var(--brass) !important;
    border-bottom: 2px solid var(--brass) !important;
}
.stTabs [data-baseweb="tab-highlight"] { background: transparent; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 18px; }

/* ---- metrics: instrument-dial cards ----------------------------------- */
[data-testid="stMetric"] {
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 12px 16px; border-top: 2px solid var(--brass-dim);
}
[data-testid="stMetricLabel"] { color: var(--muted) !important; font-size: 0.72rem !important;
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600 !important; }
[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', 'SFMono-Regular', monospace !important;
    font-weight: 600 !important; color: var(--text) !important; }

/* ---- buttons ----------------------------------------------------------- */
.stButton>button {
    background: var(--brass); color: #17130A; font-family: 'Space Grotesk', sans-serif;
    font-weight: 600; border: none; border-radius: 5px; letter-spacing: 0.01em;
}
.stButton>button:hover { background: #DBB56E; color: #17130A; }
.stButton>button[kind="secondary"] { background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); }

/* ---- expanders (setup / trade-plan cards) ------------------------------ */
.streamlit-expanderHeader, [data-testid="stExpander"] summary {
    background: var(--panel) !important; border: 1px solid var(--border) !important;
    border-radius: 6px; font-family: 'Space Grotesk', sans-serif; font-weight: 600 !important;
}
[data-testid="stExpander"] { border: none !important; }
[data-testid="stExpanderDetails"] { background: var(--panel); border: 1px solid var(--border);
    border-top: none; border-radius: 0 0 6px 6px; padding: 4px 6px; }

/* ---- dataframes / tables ------------------------------------------------ */
[data-testid="stDataFrame"] { border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }

/* ---- inputs -------------------------------------------------------------- */
.stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
    background: var(--panel) !important; border-color: var(--border) !important;
    color: var(--text) !important; border-radius: 5px !important;
}
.stSlider [data-baseweb="slider"] div[role="slider"] { background: var(--brass) !important; }
.stCheckbox label { color: var(--text) !important; }

/* ---- alerts / info boxes -------------------------------------------------- */
[data-testid="stAlertContentInfo"] { color: var(--text); }
div[data-baseweb="notification"] { border-radius: 6px; }

/* ---- dividers -------------------------------------------------------------- */
hr { border-color: var(--border) !important; }
</style>
"""
st.markdown(BRAND_CSS, unsafe_allow_html=True)

# small hand-drawn X-A-B-C-D zigzag -- the app's one signature mark, echoed
# nowhere else so it stays a mark rather than a decoration
ZIGZAG_MARK = """
<svg width="34" height="28" viewBox="0 0 34 28" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polyline points="2,22 9,6 16,18 24,4 32,20" stroke="#C9A45C" stroke-width="2.2"
            stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <circle cx="2" cy="22" r="2" fill="#6C9BD1"/>
  <circle cx="9" cy="6" r="2" fill="#E2685F"/>
  <circle cx="16" cy="18" r="2" fill="#6C9BD1"/>
  <circle cx="24" cy="4" r="2" fill="#E2685F"/>
  <circle cx="32" cy="20" r="2.4" fill="#C9A45C"/>
</svg>
"""

MARKET_TICKERS = WATCHLISTS
TIMEFRAME_OPTIONS = ["15m", "30m", "1h", "4h", "1d"]


# ---------------------------------------------------------------------------
def plot_chart(df: pd.DataFrame, patterns: list, title: str = "", atr_series: pd.Series = None):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
                         vertical_spacing=0.03, subplot_titles=(title, "RSI(14)"))

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="Price", increasing_line_color="#4FB0A2", decreasing_line_color="#E2685F",
        hovertext=[f"Open: {o:.4f}<br>High: {h:.4f}<br>Low: {l:.4f}<br>Close: {c:.4f}"
                   for o, h, l, c in zip(df['Open'], df['High'], df['Low'], df['Close'])],
        hoverinfo="x+text"
    ), row=1, col=1)

    colors = ["#C9A45C", "#6C9BD1", "#4FB0A2", "#E2685F", "#8F7CE8", "#D68FC9", "#7FC97F"]

    def _mid(p1, p2):
        return p1.timestamp + (p2.timestamp - p1.timestamp) / 2, (p1.price + p2.price) / 2

    for i, p in enumerate(patterns):
        pts = [p.X, p.A, p.B, p.C] + ([p.D] if p.D else [])
        xs = [pt.timestamp for pt in pts]
        ys = [pt.price for pt in pts]
        labels = ["X", "A", "B", "C", "D"][:len(pts)]
        color = colors[i % len(colors)]
        # offset AWAY from the pattern: a high pivot's label goes above it,
        # a low pivot's label goes below -- otherwise a low point's label
        # sits right where its two connecting lines converge/cross, which
        # is the most cluttered, hardest-to-read spot on the chart
        text_positions = ["top center" if pt.kind == "H" else "bottom center" for pt in pts]

        # primary X-A-B-C-D zigzag
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers+text",
                                  text=labels, textposition=text_positions,
                                  textfont=dict(size=13, color=color),
                                  line=dict(color=color, width=2.2, dash="dot" if p.D is None else "solid"),
                                  marker=dict(size=9, color=color),
                                  name=f"{p.name} ({p.direction.value}) Q{p.quality_score}"),
                      row=1, col=1)

        # ratio labels on each leg (AB/XA, BC/AB, CD/BC or CD/XC)
        leg_pairs = [(p.X, p.A, "AB/XA"), (p.A, p.B, "BC/AB"), (p.B, p.C, "CD/BC")]
        for p1, p2, ratio_key in leg_pairs:
            val = p.ratios.get(ratio_key)
            if val is not None:
                mx, my = _mid(p1, p2)
                fig.add_annotation(x=mx, y=my, text=f"{val:.3f} ({ratio_key})",
                                    showarrow=False, font=dict(size=10.5, color=color),
                                    bgcolor="rgba(10,12,18,0.55)", row=1, col=1)

        # dashed projection wings: X->D (overall AD/XA ratio) and B->D, echoing
        # the crossing "wings" a harmonic-pattern drawing tool shows
        if p.D is not None:
            fig.add_trace(go.Scatter(x=[p.X.timestamp, p.D.timestamp], y=[p.X.price, p.D.price],
                                      mode="lines", line=dict(color=color, width=1.3, dash="dash"),
                                      opacity=0.55, showlegend=False, hoverinfo="skip"),
                          row=1, col=1)
            fig.add_trace(go.Scatter(x=[p.B.timestamp, p.D.timestamp], y=[p.B.price, p.D.price],
                                      mode="lines", line=dict(color=color, width=1.1, dash="dash"),
                                      opacity=0.35, showlegend=False, hoverinfo="skip"),
                          row=1, col=1)
            ad_val = p.ratios.get("AD/XA")
            if ad_val is not None:
                mx, my = _mid(p.X, p.D)
                fig.add_annotation(x=mx, y=my, text=f"{ad_val:.3f} (AD/XA)",
                                    showarrow=False, font=dict(size=10.5, color=color),
                                    bgcolor="rgba(10,12,18,0.55)", row=1, col=1)

        if p.D is None:
            # still forming -- shade the projected PRZ
            fig.add_hrect(y0=p.prz_lo, y1=p.prz_hi, fillcolor=color, opacity=0.15,
                          line_width=0, row=1, col=1)
        else:
            # confirmed -- draw the actual stop/entry/target trade plan across
            # the full chart width, same numbers the dashboard's trade plan
            # card and the Telegram ENTER NOW alert use
            bullish = p.direction.value == "bullish"
            entry = p.D.price
            if atr_series is not None:
                idx = min(p.D.index, len(atr_series) - 1)
                buffer = (atr_series.iloc[idx] if not pd.isna(atr_series.iloc[idx]) else 0) * config.ATR_STOP_BUFFER
            else:
                buffer = 0
            stop = (p.X.price - buffer) if bullish else (p.X.price + buffer)
            cd_leg = abs(p.C.price - entry)
            t1 = entry + 0.382 * cd_leg if bullish else entry - 0.382 * cd_leg
            t2 = entry + 0.618 * cd_leg if bullish else entry - 0.618 * cd_leg
            t3 = p.A.price

            fig.add_hline(y=stop, line=dict(color="#E2685F", width=1.3), row=1, col=1,
                          annotation_text=f"Stop: {stop:.4f}", annotation_position="left",
                          annotation_font=dict(color="#E2685F", size=11))
            fig.add_hline(y=entry, line=dict(color=color, width=1.3, dash="dot"), row=1, col=1,
                          annotation_text=f"Entry: {entry:.4f}", annotation_position="left",
                          annotation_font=dict(color=color, size=11))
            for label, val in [("Target 1", t1), ("Target 2", t2), ("Target 3", t3)]:
                fig.add_hline(y=val, line=dict(color="#4FB0A2", width=1.1), row=1, col=1,
                              annotation_text=f"{label}: {val:.4f}", annotation_position="left",
                              annotation_font=dict(color="#4FB0A2", size=10.5))

            # pattern name tag near D
            fig.add_annotation(x=p.D.timestamp, y=stop if bullish else t3, text=f" {p.name} ",
                                showarrow=False, font=dict(size=11, color="#9FC1E8"),
                                bgcolor="rgba(21,27,36,0.92)", bordercolor="#6C9BD1",
                                borderwidth=1, row=1, col=1, yshift=-14 if bullish else 14)

    r = rsi(df['Close'])
    fig.add_trace(go.Scatter(x=df.index, y=r, name="RSI", line=dict(color="#8F7CE8")), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#4A5262", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#4A5262", row=2, col=1)

    fig.update_layout(height=750, template="plotly_dark", margin=dict(t=70, b=10, l=10, r=10),
                       paper_bgcolor="#0A0D12", plot_bgcolor="#10141B",
                       font=dict(family="IBM Plex Sans, sans-serif", color="#E7E9EE"),
                       legend=dict(orientation="h", y=1.03),
                       dragmode="pan",  # click-drag pans by default; scroll/pinch to zoom
                       hovermode="x unified")
    # zoom/pan controls: range selector buttons + a draggable range slider under the price panel
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=30, label="1M", step="day", stepmode="backward"),
                dict(count=90, label="3M", step="day", stepmode="backward"),
                dict(count=180, label="6M", step="day", stepmode="backward"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(step="all", label="All"),
            ],
            bgcolor="#151B24", activecolor="#C9A45C", font=dict(color="#E7E9EE", size=11),
            y=1.18, yanchor="top",
        ),
        row=1, col=1,
    )
    fig.update_xaxes(rangeslider=dict(visible=False), row=1, col=1, gridcolor="#1B212B")
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06, bgcolor="#10141B"), row=2, col=1, gridcolor="#1B212B")
    fig.update_yaxes(gridcolor="#1B212B")
    return fig


def trade_plan_box(df, p, atr_series):
    bullish = p.direction.value == "bullish"
    entry = p.D.price if p.D is not None else (p.prz_lo + p.prz_hi) / 2
    idx = p.D.index if p.D is not None else p.C.index
    idx = min(idx, len(atr_series) - 1)
    buffer = (atr_series.iloc[idx] if not pd.isna(atr_series.iloc[idx]) else 0) * config.ATR_STOP_BUFFER
    stop = (p.X.price - buffer) if bullish else (p.X.price + buffer)
    cd_leg = abs(p.C.price - entry)
    t1 = entry + 0.382 * cd_leg if bullish else entry - 0.382 * cd_leg
    t2 = entry + 0.618 * cd_leg if bullish else entry - 0.618 * cd_leg
    t3 = p.A.price
    risk = abs(entry - stop)
    rr2 = abs(t2 - entry) / risk if risk else 0

    conf = score_confluence(df, p)

    status = "CONFIRMED \u2705" if (p.confirmed and p.D is not None) else "WATCHING \U0001F440 (forming)"
    st.markdown(f"### {p.name} -- {p.direction.value.upper()} -- {status}")
    st.caption(PATTERN_RULES[p.name].notes)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry (PRZ)", f"{entry:.4f}")
    c2.metric("Stop Loss", f"{stop:.4f}", delta=f"{-risk:.4f}", delta_color="inverse")
    c3.metric("Target 2 (0.618 CD)", f"{t2:.4f}", delta=f"R:R {rr2:.2f}")
    c4.metric("Ratio Quality", f"{p.quality_score}/100")

    with st.expander("Full trade plan & reasoning", expanded=True):
        st.write(f"**Target 1** (0.382 of CD leg): `{t1:.4f}` -- close 1/3 position, move stop to breakeven")
        st.write(f"**Target 2** (0.618 of CD leg): `{t2:.4f}` -- close 1/3 position")
        st.write(f"**Target 3** (point A): `{t3:.4f}` -- close remainder or trail")
        st.write(f"**Ratios found:** {p.ratios}")
        st.write(f"**RSI confluence:** {conf['rsi']['note']}")
        st.write(f"**Volume confluence:** {conf['volume']['note']}")
        st.write(f"**Confluence-adjusted score:** {conf['adjusted_score']}/100")
        st.info(
            f"**Why this trade:** Price traced an X-A-B-C-D structure matching the {p.name} "
            f"Fibonacci ratio rules. The D point sits inside the Potential Reversal Zone "
            f"(overlap of the XA and CD/XC projections), which is where {p.name} patterns are "
            f"statistically expected to reverse. {'This has been confirmed by price reaching D.' if p.D else 'Price is approaching but has not yet tagged the PRZ -- this is a watch-list setup, not a live entry.'}"
        )


# ---------------------------------------------------------------------------
st.markdown(f"""
<div class="hpt-masthead">
    {ZIGZAG_MARK}
    <div>
        <div class="hpt-wordmark">Harmonic<span>.</span>Terminal</div>
        <div class="hpt-tagline">AUS &middot; US &middot; India &middot; Forex &mdash; Gartley, Bat, Butterfly, Crab, Deep Crab, Cypher, Shark</div>
    </div>
</div>
""", unsafe_allow_html=True)
st.write("")

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Overview", "Scan", "Backtest", "Watchlist",
    "Open Trades", "Leaderboard", "Validation", "Settings"])

# --- TAB 0: Live Overview ----------------------------------------------------
with tab0:
    st.caption("Auto-refreshes every 60s. Click any row below to see its chart inline -- no need to switch tabs.")

    @st.fragment(run_every=60)
    def live_overview_fragment():
        import datetime
        state = tm.load_state()
        board = lb.load_leaderboard()

        open_items = {k: v for k, v in state.items() if v["status"] in ("OPEN", "PARTIAL_T1", "PARTIAL_T2")}
        pending_items = {k: v for k, v in state.items() if v["status"] in ("AWAITING_CONFIRMATION", "WATCHING")}
        closed_items = {k: v for k, v in state.items() if v["status"].startswith("CLOSED")}

        last_update = max((v.get("last_update", "") for v in state.values()), default="")
        board_rows = lb.leaderboard_summary(board)
        top = next((r for r in board_rows if r["live_avg_r"] is not None), None)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("\U0001F7E2 Open Trades", len(open_items))
        c2.metric("\U0001F440 Watching / Awaiting", len(pending_items))
        c3.metric("\u2705 Closed (tracked)", len(closed_items))
        c4.metric("\U0001F551 Last Scan", last_update[:16].replace("T", " ") if last_update else "No scans yet")

        if top:
            st.caption(f"\U0001F3C6 Best-performing combo so far: **{top['ticker']} {top['pattern']}** "
                       f"-- {top['live_avg_r']}R avg over {top['live_n']} live trades")

        st.divider()

        if not open_items and not pending_items:
            st.info("Nothing tracked yet. Run the scanner (GitHub Actions, or manually) to populate this view.")
            return

        selected_key = st.session_state.get("overview_selected_setup")

        if open_items:
            st.markdown("#### \U0001F7E2 Currently open")
            rows, key_lookup = [], {}
            for k, v in open_items.items():
                direction_word = "LONG" if v["direction"] == "bullish" else "SHORT"
                label = f"{v['ticker']} -- {v['pattern']} ({direction_word})"
                rows.append({"Setup": label, "Status": v["status"], "Entry": round(v["entry"], 4),
                             "Stop": round(v["stop"], 4), "T1": round(v["t1"], 4), "T2": round(v["t2"], 4),
                             "T3": round(v["t3"], 4), "Fraction Left": f"{v.get('fraction_remaining', 1.0):.0%}"})
                key_lookup[label] = k
            open_df = pd.DataFrame(rows)
            event = st.dataframe(open_df, use_container_width=True, hide_index=True,
                                  on_select="rerun", selection_mode="single-row", key="overview_open_table")
            if event.selection.rows:
                clicked_label = open_df.iloc[event.selection.rows[0]]["Setup"]
                selected_key = key_lookup[clicked_label]
                st.session_state["overview_selected_setup"] = selected_key

        if pending_items:
            st.markdown("#### \U0001F440 Watching / awaiting confirmation")
            rows, key_lookup2 = [], {}
            for k, v in pending_items.items():
                direction_word = "LONG" if v["direction"] == "bullish" else "SHORT"
                label = f"{v['ticker']} -- {v['pattern']} ({direction_word})"
                rows.append({"Setup": label, "Status": v["status"], "Projected Entry": round(v["entry"], 4)})
                key_lookup2[label] = k
            pending_df = pd.DataFrame(rows)
            event2 = st.dataframe(pending_df, use_container_width=True, hide_index=True,
                                   on_select="rerun", selection_mode="single-row", key="overview_pending_table")
            if event2.selection.rows:
                clicked_label = pending_df.iloc[event2.selection.rows[0]]["Setup"]
                selected_key = key_lookup2[clicked_label]
                st.session_state["overview_selected_setup"] = selected_key

        if selected_key and selected_key in state:
            s = state[selected_key]
            st.divider()
            st.markdown(f"### Chart: {s['ticker']} -- {s['pattern']} ({s['market']}/{s['timeframe']})")
            pattern_obj = tm.reconstruct_pattern(s)
            if pattern_obj is None:
                st.info("This setup predates chart-point storage -- no chart available for it.")
            else:
                try:
                    live_df = DEFAULT_SOURCE.fetch(s["ticker"], interval=s["timeframe"],
                                                    period=config.SCAN_PERIOD.get(s["market"], "1y"))
                    live_atr = _atr(live_df)
                    fig = plot_chart(live_df, [pattern_obj], title=f"{s['ticker']} -- {s['timeframe']}",
                                      atr_series=live_atr)
                    st.plotly_chart(fig, use_container_width=True, key=f"overview_chart_{selected_key}")
                except Exception as e:
                    st.warning(f"Could not load live chart for {s['ticker']}: {e}")

    live_overview_fragment()

# --- TAB 1: Scan Now --------------------------------------------------------
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    market = col1.selectbox("Market", list(MARKET_TICKERS.keys()), key="scan_market")
    ticker = col2.selectbox("Ticker", MARKET_TICKERS[market], key="scan_ticker")
    custom_ticker = col2.text_input("...or type a custom ticker", "", key="scan_custom")
    timeframe = col3.selectbox("Timeframe", TIMEFRAME_OPTIONS, index=4, key="scan_tf")
    period = col4.selectbox("History", ["3mo", "6mo", "1y", "2y"], index=2, key="scan_period")

    deviation = st.slider("ZigZag sensitivity (%)", 0.3, 8.0,
                           float(DEFAULT_DEVIATION.get(market, 3.0)), 0.1, key="scan_dev")
    min_quality = st.slider("Minimum ratio quality to display", 0, 100, 50, key="scan_minq")

    if st.button("Run Scan", type="primary", key="run_scan_btn"):
        use_ticker = custom_ticker.strip() if custom_ticker.strip() else ticker
        with st.spinner(f"Fetching {use_ticker} and detecting patterns..."):
            try:
                df = DEFAULT_SOURCE.fetch(use_ticker, interval=timeframe, period=period)
                pats = find_patterns(df, deviation_pct=deviation, tolerance=config.RATIO_TOLERANCE)
                pats = [p for p in pats if p.quality_score >= min_quality]
                atr_series = _atr(df)
                import regime_filter as rf
                regime = rf.assess_regime(df, atr_series)
                st.session_state["last_scan"] = (df, pats, use_ticker, atr_series, regime)
            except Exception as e:
                st.error(f"Could not fetch data: {e}")
                st.session_state.pop("last_scan", None)

    if "last_scan" in st.session_state:
        df, pats, use_ticker, atr_series, regime = st.session_state["last_scan"]
        if not regime["tradeable_regime"]:
            st.warning(f"\u26A0\uFE0F **Regime caution:** {regime['volume']['note']} {regime['volatility']['note']} "
                       f"{regime['calendar']['note'] if regime['calendar']['flag'] else ''}\n\n"
                       f"The live scanner would suppress new ENTER NOW alerts here until conditions normalize.")
        if not pats:
            st.warning("No qualifying patterns found for this ticker/timeframe/sensitivity combination.")
        else:
            st.plotly_chart(plot_chart(df, pats, title=f"{use_ticker} -- {timeframe}", atr_series=atr_series), use_container_width=True)
            st.markdown(f"## {len(pats)} pattern(s) found")
            for p in sorted(pats, key=lambda x: -x.quality_score):
                trade_plan_box(df, p, atr_series)
                st.divider()

# --- TAB 2: Backtest ---------------------------------------------------------
with tab2:
    st.subheader("Backtest a ticker across its history")
    bc1, bc2, bc3, bc4 = st.columns(4)
    bt_market = bc1.selectbox("Market", list(MARKET_TICKERS.keys()), key="bt_market")
    bt_ticker = bc2.selectbox("Ticker", MARKET_TICKERS[bt_market], key="bt_ticker")
    bt_tf = bc3.selectbox("Timeframe", TIMEFRAME_OPTIONS, index=4, key="bt_tf")
    bt_period = bc4.selectbox("History", ["1y", "2y", "5y", "max"], index=1, key="bt_period")

    rc1, rc2, rc3, rc4, rc5, rc6 = st.columns(6)
    bt_dev = rc1.slider("ZigZag sensitivity (%)", 0.3, 8.0, float(DEFAULT_DEVIATION.get(bt_market, 3.0)), 0.1, key="bt_dev")
    bt_minq = rc2.slider("Min ratio quality", 0, 100, 60, key="bt_minq")
    bt_risk = rc3.number_input("Risk per trade (%)", 0.1, 10.0, 1.0, 0.1, key="bt_risk")
    bt_equity = rc4.number_input("Starting equity", 100, 10_000_000, 10000, 100, key="bt_equity")
    bt_cost = rc5.number_input("Round-trip cost (% of price)", 0.0, 2.0, 0.05, 0.01, key="bt_cost",
                                help="Spread + slippage + commission. Don't set to 0 -- unrealistic backtests ignore this.")
    bt_confirm = rc6.checkbox("Require candle confirmation", value=True, key="bt_confirm",
                               help="Matches live ENTER NOW logic exactly: only enters after a confirmation candle "
                                    "AND RSI/MACD divergence appear within 3 bars of D -- not the raw PRZ touch. "
                                    "This is intentionally strict and will show FEWER trades than turning it off "
                                    "(which backtests the raw pattern-completion entry instead). Compare both: "
                                    "off shows the pattern's raw historical edge, on shows what your Telegram "
                                    "alerts will actually do.")

    if st.button("Run Backtest", type="primary", key="run_bt_btn"):
        with st.spinner(f"Backtesting {bt_ticker}..."):
            try:
                df = DEFAULT_SOURCE.fetch(bt_ticker, interval=bt_tf, period=bt_period)
                result = backtest(df, deviation_pct=bt_dev, tolerance=config.RATIO_TOLERANCE,
                                   min_quality=bt_minq, risk_per_trade_pct=bt_risk,
                                   starting_equity=bt_equity, cost_pct=bt_cost,
                                   require_confirmation=bt_confirm)
                st.session_state["last_bt"] = result
            except Exception as e:
                st.error(f"Backtest failed: {e}")
                st.session_state.pop("last_bt", None)

    if "last_bt" in st.session_state:
        res = st.session_state["last_bt"]
        if res["n_trades"] == 0:
            st.warning(res.get("message", "No trades generated."))
        else:
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Trades", res["n_trades"])
            m2.metric("Win Rate", f"{res['win_rate_pct']}%")
            m3.metric("Avg R", res["avg_r"])
            m4.metric("Profit Factor", res["profit_factor"])
            m5.metric("Return", f"{res['return_pct']}%")
            m6.metric("Max Drawdown", f"{res['max_drawdown_pct']}%")

            ec = res["equity_curve"]
            ec_df = pd.DataFrame(ec, columns=["date", "equity"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ec_df["date"], y=ec_df["equity"], line=dict(color="#4FB0A2")))
            fig.update_layout(title="Equity Curve", template="plotly_dark", height=350,
                               paper_bgcolor="#0A0D12", plot_bgcolor="#10141B",
                               font=dict(family="IBM Plex Sans, sans-serif", color="#E7E9EE"),
                               margin=dict(t=40, b=10, l=10, r=10))
            fig.update_xaxes(gridcolor="#1B212B")
            fig.update_yaxes(gridcolor="#1B212B")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### Performance by pattern type")
            bp_df = pd.DataFrame(res["by_pattern"]).T
            st.dataframe(bp_df, use_container_width=True)

            st.markdown("#### Time-to-target (how long trades historically took)")
            st.caption("Based on this backtest's actual trade history -- use as a statistical ETA, "
                       "not a guarantee. 'Bars' = number of candles on the selected timeframe.")
            timing = res["timing"]
            tcols = st.columns(3)
            for i, tgt in enumerate(["T1", "T2", "T3"]):
                t = timing[tgt]
                with tcols[i]:
                    st.markdown(f"**{tgt}**")
                    if t["n_reached"] == 0:
                        st.write("Not reached in any trade")
                    else:
                        st.write(f"Reached in {t['n_reached']}/{res['n_trades']} trades")
                        st.write(f"Median: **{t['median_bars']} bars**")
                        st.write(f"Avg: {t['avg_bars']} bars (range {t['min_bars']}-{t['max_bars']})")
                        st.write(f"Median calendar time: {t['median_time']}")

            st.markdown("#### Trade log")
            trades_df = pd.DataFrame([{
                "Pattern": t.pattern, "Direction": t.direction, "Entry Date": t.entry_date,
                "Entry": round(t.entry_price, 4), "Stop": round(t.stop_price, 4),
                "Exit Date": t.exit_date, "Exit": round(t.exit_price, 4) if t.exit_price else None,
                "Outcome": t.outcome, "R": round(t.r_multiple, 2) if t.r_multiple is not None else None,
                "Bars to T1": t.bars_to_t1, "Bars to T2": t.bars_to_t2, "Bars to T3": t.bars_to_t3,
                "Quality": t.quality_score,
            } for t in res["trades"]])
            st.dataframe(trades_df, use_container_width=True)

# --- TAB 3: Watchlist Scan ---------------------------------------------------
with tab3:
    st.subheader("Scan an entire watchlist at once")
    ws_market = st.selectbox("Market", list(MARKET_TICKERS.keys()), key="ws_market")
    ws_minq = st.slider("Min ratio quality", 0, 100, 65, key="ws_minq")
    if st.button("Scan Watchlist", type="primary", key="run_ws_btn"):
        rows = []
        progress = st.progress(0)
        tickers = MARKET_TICKERS[ws_market]
        for i, t in enumerate(tickers):
            try:
                df = DEFAULT_SOURCE.fetch(t, interval=config.SCAN_TIMEFRAMES[ws_market],
                                           period=config.SCAN_PERIOD[ws_market])
                pats = find_patterns(df, deviation_pct=config.ZIGZAG_DEVIATION[ws_market],
                                      tolerance=config.RATIO_TOLERANCE)
                for p in pats:
                    if p.quality_score >= ws_minq:
                        rows.append({
                            "Ticker": t, "Pattern": p.name, "Direction": p.direction.value,
                            "Status": "CONFIRMED" if p.D else "WATCHING",
                            "Quality": p.quality_score,
                            "D price": round(p.D.price, 4) if p.D else None,
                            "PRZ Low": round(p.prz_lo, 4), "PRZ High": round(p.prz_hi, 4),
                        })
            except Exception as e:
                st.warning(f"{t}: {e}")
            progress.progress((i + 1) / len(tickers))
        if rows:
            st.dataframe(pd.DataFrame(rows).sort_values("Quality", ascending=False), use_container_width=True)
        else:
            st.info("No qualifying patterns found across this watchlist right now.")

# --- TAB 4: Open Trades / Live Status -----------------------------------------
with tab4:
    st.subheader("Setups tracked by the scanner")
    st.caption("This reflects whatever the scanner (scanner.py, run via GitHub Actions) has found on its "
               "last run. Run the scanner at least once for this to show anything.")
    state = tm.load_state()
    if not state:
        st.info("No tracked setups yet. Run the scanner at least once, or wait for the next scheduled scan.")
    else:
        status_order = {"OPEN": 0, "PARTIAL_T1": 1, "PARTIAL_T2": 2, "AWAITING_CONFIRMATION": 3,
                         "WATCHING": 4, "CLOSED_T3": 5, "CLOSED_STOP": 6, "CLOSED_INVALIDATED": 7}
        status_labels = {"OPEN": "\U0001F7E2 Open", "PARTIAL_T1": "\U0001F7E1 Partial (T1 hit)",
                          "PARTIAL_T2": "\U0001F7E1 Partial (T2 hit)", "AWAITING_CONFIRMATION": "\u23F3 Awaiting confirmation",
                          "WATCHING": "\U0001F440 Watching", "CLOSED_T3": "\u2705 Closed (T3)",
                          "CLOSED_STOP": "\U0001F534 Closed (stop)", "CLOSED_INVALIDATED": "\u26AA Invalidated"}

        sorted_items = sorted(state.items(), key=lambda kv: status_order.get(kv[1]["status"], 9))
        active_items = [(k, v) for k, v in sorted_items if v["status"] in ("OPEN", "PARTIAL_T1", "PARTIAL_T2")]
        pending_items = [(k, v) for k, v in sorted_items if v["status"] in ("AWAITING_CONFIRMATION", "WATCHING")]
        closed_items = [(k, v) for k, v in sorted_items if v["status"].startswith("CLOSED")]

        m1, m2, m3 = st.columns(3)
        m1.metric("Open / Partial", len(active_items))
        m2.metric("Watching / Awaiting", len(pending_items))
        m3.metric("Closed (tracked history)", len(closed_items))

        def render_setup_card(setup_id, s):
            direction_word = "LONG" if s["direction"] == "bullish" else "SHORT"
            with st.expander(f"{status_labels.get(s['status'], s['status'])} -- {s['ticker']} -- "
                              f"{s['pattern']} ({direction_word}) -- {s['market']}/{s['timeframe']}",
                              expanded=(s["status"] in ("OPEN", "PARTIAL_T1", "PARTIAL_T2"))):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entry", f"{s['entry']:.4f}")
                c2.metric("Stop", f"{s['stop']:.4f}")
                c3.metric("T1 / T2 / T3", f"{s['t1']:.4f} / {s['t2']:.4f} / {s['t3']:.4f}")
                c4.metric("Fraction left", f"{s.get('fraction_remaining', 1.0):.0%}")
                st.caption(f"Last update: {s.get('last_update', '?')}")

                pattern_obj = tm.reconstruct_pattern(s)
                if pattern_obj is None:
                    st.info("This setup was tracked before chart data was stored -- no chart available "
                            "for it (will appear for setups tracked from now on).")
                    return
                try:
                    live_df = DEFAULT_SOURCE.fetch(s["ticker"], interval=s["timeframe"],
                                                    period=config.SCAN_PERIOD.get(s["market"], "1y"))
                    live_atr = _atr(live_df)
                    fig = plot_chart(live_df, [pattern_obj], title=f"{s['ticker']} -- {s['timeframe']}",
                                      atr_series=live_atr)
                    st.plotly_chart(fig, use_container_width=True, key=f"chart_{setup_id}")
                except Exception as e:
                    st.warning(f"Could not load live chart for {s['ticker']}: {e}")

        if active_items:
            st.markdown("### Currently open")
            for setup_id, s in active_items:
                render_setup_card(setup_id, s)

        if pending_items:
            st.markdown("### Watching / awaiting confirmation")
            for setup_id, s in pending_items:
                render_setup_card(setup_id, s)

        if closed_items:
            st.markdown("### Closed history")
            for setup_id, s in closed_items[:15]:
                render_setup_card(setup_id, s)
            if len(closed_items) > 15:
                st.caption(f"...and {len(closed_items) - 15} more closed setups not shown.")

# --- TAB 5: Leaderboard --------------------------------------------------------
with tab5:
    st.subheader("Performance by pattern \u00d7 instrument")
    st.caption("Tracks realized results per (market, ticker, pattern) combo, from live closed trades "
               "and optionally seeded from backtests. The scanner auto-suppresses ENTER NOW alerts for "
               "combos with a demonstrably weak live track record (see should_suppress in leaderboard.py).")

    board = lb.load_leaderboard()
    if not board:
        st.info("No leaderboard data yet. It fills in as the scanner's live trades close, or you can "
                 "seed it from a backtest below.")
    else:
        rows = lb.leaderboard_summary(board)
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.markdown("---")
    st.markdown("#### Seed the leaderboard from a backtest")
    st.caption("Bulk-loads a backtest's trade history into the leaderboard's backtest bucket, giving new "
               "combos a track record to lean on before enough live trades have accrued.")
    sc1, sc2, sc3 = st.columns(3)
    seed_market = sc1.selectbox("Market", list(MARKET_TICKERS.keys()), key="seed_market")
    seed_ticker = sc2.selectbox("Ticker", MARKET_TICKERS[seed_market], key="seed_ticker")
    seed_period = sc3.selectbox("History", ["1y", "2y", "5y"], index=1, key="seed_period")
    if st.button("Seed from backtest", key="seed_btn"):
        with st.spinner(f"Backtesting {seed_ticker} to seed the leaderboard..."):
            try:
                df = DEFAULT_SOURCE.fetch(seed_ticker, interval=config.SCAN_TIMEFRAMES[seed_market], period=seed_period)
                result = backtest(df, deviation_pct=config.ZIGZAG_DEVIATION[seed_market],
                                   tolerance=config.RATIO_TOLERANCE, min_quality=config.MIN_QUALITY_SCORE)
                board = lb.load_leaderboard()
                board = lb.seed_from_backtest(board, seed_market, seed_ticker, result)
                lb.save_leaderboard(board)
                st.success(f"Seeded {result['n_trades']} backtest trades for {seed_ticker} into the leaderboard.")
            except Exception as e:
                st.error(f"Could not seed leaderboard: {e}")

# --- TAB 6: Validation ----------------------------------------------------------
with tab6:
    st.subheader("Out-of-sample validation")
    st.caption("Splits history into an in-sample chunk (what you tune settings against) and an untouched "
               "out-of-sample chunk (what you verify against). A big gap between the two means your "
               "settings are likely overfit to noise, not a real edge.")
    vc1, vc2, vc3, vc4 = st.columns(4)
    v_market = vc1.selectbox("Market", list(MARKET_TICKERS.keys()), key="v_market")
    v_ticker = vc2.selectbox("Ticker", MARKET_TICKERS[v_market], key="v_ticker")
    v_period = vc3.selectbox("History", ["2y", "5y", "max"], index=1, key="v_period")
    v_split = vc4.slider("In-sample %", 50, 90, 70, key="v_split")

    vr1, vr2, vr3 = st.columns(3)
    v_dev = vr1.slider("ZigZag sensitivity (%)", 0.3, 8.0, float(DEFAULT_DEVIATION.get(v_market, 3.0)), 0.1, key="v_dev")
    v_minq = vr2.slider("Min ratio quality", 0, 100, 60, key="v_minq")
    v_confirm = vr3.checkbox("Require candle confirmation", value=True, key="v_confirm")

    if st.button("Run Validation", type="primary", key="run_v_btn"):
        with st.spinner(f"Running walk-forward validation on {v_ticker}..."):
            try:
                from backtest import walk_forward_validate
                df = DEFAULT_SOURCE.fetch(v_ticker, interval=config.SCAN_TIMEFRAMES[v_market], period=v_period)
                vres = walk_forward_validate(df, in_sample_pct=v_split / 100, deviation_pct=v_dev,
                                              tolerance=config.RATIO_TOLERANCE, min_quality=v_minq,
                                              require_confirmation=v_confirm)
                st.session_state["last_validation"] = vres
            except Exception as e:
                st.error(f"Validation failed: {e}")
                st.session_state.pop("last_validation", None)

    if "last_validation" in st.session_state:
        vres = st.session_state["last_validation"]
        if "error" in vres:
            st.warning(vres["error"])
        else:
            verdict = vres["verdict"]
            if "overfit" in verdict:
                st.error(f"\u26A0\uFE0F **{verdict}**")
            elif verdict == "insufficient_data":
                st.warning(f"\u2753 **{verdict}** -- need more trades in each half to judge reliably.")
            else:
                st.success(f"\u2705 **{verdict}**")

            vcol1, vcol2 = st.columns(2)
            with vcol1:
                st.markdown(f"##### In-sample ({vres['in_sample']['n_bars']} bars)")
                ir = vres["in_sample"]["result"]
                if ir.get("n_trades", 0) == 0:
                    st.write("No trades.")
                else:
                    st.metric("Trades", ir["n_trades"])
                    st.metric("Win Rate", f"{ir['win_rate_pct']}%")
                    st.metric("Expectancy", f"{ir['expectancy_r']}R")
                    st.metric("Profit Factor", ir["profit_factor"])
            with vcol2:
                st.markdown(f"##### Out-of-sample ({vres['out_of_sample']['n_bars']} bars)")
                orr = vres["out_of_sample"]["result"]
                if orr.get("n_trades", 0) == 0:
                    st.write("No trades.")
                else:
                    st.metric("Trades", orr["n_trades"])
                    st.metric("Win Rate", f"{orr['win_rate_pct']}%")
                    st.metric("Expectancy", f"{orr['expectancy_r']}R")
                    st.metric("Profit Factor", orr["profit_factor"])

# --- TAB 7: Settings ----------------------------------------------------------
with tab7:
    st.subheader("Current configuration (edit config.py to change)")
    st.json({
        "SCAN_TIMEFRAMES": config.SCAN_TIMEFRAMES,
        "ZIGZAG_DEVIATION": config.ZIGZAG_DEVIATION,
        "MIN_QUALITY_SCORE": config.MIN_QUALITY_SCORE,
        "RATIO_TOLERANCE": config.RATIO_TOLERANCE,
        "RISK_PER_TRADE_PCT": config.RISK_PER_TRADE_PCT,
        "ATR_STOP_BUFFER": config.ATR_STOP_BUFFER,
        "MAX_CONCURRENT_TRADES": config.MAX_CONCURRENT_TRADES,
        "MAX_CORRELATED_TRADES": config.MAX_CORRELATED_TRADES,
        "MAX_DAILY_RISK_PCT": config.MAX_DAILY_RISK_PCT,
        "USE_TRAILING_STOP_AFTER_T2": config.USE_TRAILING_STOP_AFTER_T2,
        "TRAILING_ATR_MULT": config.TRAILING_ATR_MULT,
        "SCAN_INTERVAL_MINUTES": config.SCAN_INTERVAL_MINUTES,
    })
    st.markdown("""
    **Watchlists** (edit in `data_sources.py`):
    """)
    for m, tickers in WATCHLISTS.items():
        st.write(f"**{m}**: {', '.join(tickers)}")
