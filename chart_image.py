"""
Generates a chart image (PNG bytes) showing the harmonic pattern with its
XABCD structure, ratio labels, and entry/stop/target levels overlaid --
this is what gets attached to ENTER NOW Telegram alerts, and what the
dashboard's Open Trades tab renders for each tracked setup.

Uses matplotlib directly (candlesticks drawn manually via patches) rather
than a headless-browser-based renderer (Plotly+kaleido needs a bundled
Chrome install that's unreliable in CI environments) -- this keeps it
lightweight and dependable to run inside GitHub Actions.
"""
import io
import matplotlib
matplotlib.use("Agg")  # headless, no display needed -- required for CI/servers
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np

BG = "#0A0D12"
PANEL = "#10141B"
GRID = "#232A38"
TEXT = "#E7E9EE"
MUTED = "#8890A2"
BULL = "#4FB0A2"
BEAR = "#E2685F"
GOLD = "#C9A45C"
VIOLET = "#8F7CE8"
BLUE = "#6C9BD1"


def _draw_candles(ax, df: pd.DataFrame):
    x = np.arange(len(df))
    width = 0.6
    for i, (_, row) in enumerate(df.iterrows()):
        color = BULL if row["Close"] >= row["Open"] else BEAR
        ax.plot([i, i], [row["Low"], row["High"]], color=color, linewidth=0.9, zorder=2)
        lo, hi = sorted([row["Open"], row["Close"]])
        height = max(hi - lo, (df["High"].max() - df["Low"].min()) * 0.001)
        ax.add_patch(Rectangle((i - width / 2, lo), width, height, facecolor=color,
                                edgecolor=color, linewidth=0, zorder=3))
    return x


def generate_pattern_chart(df: pd.DataFrame, pattern, entry: float, stop: float,
                            t1: float, t2: float, t3: float, ticker: str, market: str,
                            timeframe: str, status: str = "CONFIRMED") -> bytes:
    """
    Renders the pattern chart and returns PNG bytes ready to send as a
    Telegram photo or display in the dashboard.
    """
    plt.rcParams["font.family"] = "monospace"
    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    # only show a reasonable trailing window around the pattern, not the
    # entire fetched history -- keeps the image readable
    x_pivot_idx = pattern.X.index
    start_idx = max(0, x_pivot_idx - 5)
    view = df.iloc[start_idx:]
    view_dates = view.index
    view = view.reset_index(drop=True)
    offset = start_idx

    _draw_candles(ax, view)
    ax.set_xlim(-1, len(view) + 8)  # extra right margin so level labels don't collide with the last candle

    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.6)

    # x-axis: show a handful of real date labels instead of raw bar indices
    n_ticks = min(8, len(view))
    tick_positions = np.linspace(0, len(view) - 1, n_ticks).astype(int)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([view_dates[i].strftime("%b %d") if hasattr(view_dates[i], "strftime")
                         else str(view_dates[i]) for i in tick_positions], rotation=0)

    # XABCD structure
    pts = [pattern.X, pattern.A, pattern.B, pattern.C] + ([pattern.D] if pattern.D else [])
    labels = ["X", "A", "B", "C", "D"][:len(pts)]
    xs = [p.index - offset for p in pts]
    ys = [p.price for p in pts]
    ax.plot(xs, ys, color=VIOLET, linewidth=2, marker="o", markersize=5, zorder=5)
    for pt, xi, yi, label in zip(pts, xs, ys, labels):
        color = GOLD if label == "D" else VIOLET
        # offset AWAY from the pattern: high pivots get their label above,
        # low pivots get it below -- otherwise a low point's label sits
        # right where the two connecting lines converge/cross, which is
        # exactly the most cluttered, hardest-to-read spot on the chart
        y_offset = 12 if pt.kind == "H" else -16
        va = "bottom" if pt.kind == "H" else "top"
        ax.annotate(label, (xi, yi), textcoords="offset points", xytext=(0, y_offset),
                    color=color, fontsize=12, fontweight="bold", ha="center", va=va, zorder=7,
                    bbox=dict(boxstyle="round,pad=0.15", fc=BG, ec="none", alpha=0.75))

    # ratio labels on each leg
    leg_pairs = [(pattern.X, pattern.A, "AB/XA"), (pattern.A, pattern.B, "BC/AB"),
                 (pattern.B, pattern.C, "CD/BC")]
    for p1, p2, key in leg_pairs:
        val = pattern.ratios.get(key)
        if val is not None:
            mx = (p1.index + p2.index) / 2 - offset
            my = (p1.price + p2.price) / 2
            ax.annotate(f"{val:.3f}", (mx, my), color=VIOLET, fontsize=8,
                        ha="center", bbox=dict(boxstyle="round,pad=0.2", fc=BG, ec="none", alpha=0.7))

    # entry / stop / target horizontal lines
    x_max = len(view) - 1
    label_x = x_max + 1
    levels = [
        (stop, BEAR, f"Stop {stop:.4f}", "-"),
        (entry, GOLD, f"Entry {entry:.4f}", ":"),
        (t1, BULL, f"T1 {t1:.4f}", "-"),
        (t2, BULL, f"T2 {t2:.4f}", "-"),
        (t3, BULL, f"T3 {t3:.4f}", "-"),
    ]
    # nudge labels apart vertically if two levels are close enough in price
    # to visually collide (e.g. entry sitting right at D)
    y_range = view["High"].max() - view["Low"].min()
    min_gap = y_range * 0.035
    sorted_levels = sorted(levels, key=lambda l: l[0])
    adjusted = []
    last_y = None
    for level, color, label, dash in sorted_levels:
        y = level if last_y is None else max(level, last_y + min_gap)
        adjusted.append((level, y, color, label, dash))
        last_y = y

    for level, label_y, color, label, dash in adjusted:
        ax.axhline(level, color=color, linewidth=1.1, linestyle=dash, alpha=0.85, zorder=1)
        ax.annotate(label, (label_x, label_y), color=color, fontsize=8.5, fontweight="bold",
                    ha="left", va="center", zorder=6)

    direction_word = "LONG" if pattern.direction.value == "bullish" else "SHORT"
    title = f"{ticker}  |  {market}  |  {timeframe}  |  {pattern.name} ({direction_word})  |  {status}"
    ax.set_title(title, color=TEXT, fontsize=12, fontweight="bold", loc="left", pad=12)
    ax.set_ylabel("Price", color=MUTED, fontsize=9)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
