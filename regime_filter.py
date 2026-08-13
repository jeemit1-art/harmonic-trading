"""
Volatility / liquidity regime filter. A technically perfect harmonic
pattern means much less during a dead holiday session (thin volume,
structure is noise) or a volatility blowout (structure gets steamrolled
regardless of ratios). This module flags both conditions so the scanner
can skip alerts, and dashboard users can see why a setup is marked risky.
"""
from datetime import date
import numpy as np
import pandas as pd

# Common low-liquidity windows ((month, day) start/end, inclusive) to treat
# with extra caution across most markets -- thin volume distorts everything,
# including harmonic structure. Extend/edit for your markets' actual
# holiday calendars.
LOW_LIQUIDITY_WINDOWS = [
    ((12, 23), (1, 2)),    # Christmas/New Year (wraps across year boundary)
    ((7, 1), (7, 10)),     # US summer slowdown (rough proxy, tune as needed)
]


def _in_window(d: date, window) -> bool:
    (m1, d1), (m2, d2) = window
    start_md = (m1, d1)
    end_md = (m2, d2)
    current_md = (d.month, d.day)
    if start_md <= end_md:
        return start_md <= current_md <= end_md
    # window wraps across the year boundary (e.g. Dec 23 -> Jan 2)
    return current_md >= start_md or current_md <= end_md


def is_low_liquidity_period(check_date: date = None) -> dict:
    check_date = check_date or date.today()
    for window in LOW_LIQUIDITY_WINDOWS:
        if _in_window(check_date, window):
            return {"flag": True, "note": f"{check_date.isoformat()} falls in a typically thin-volume window -- "
                                           f"harmonic structure is less trustworthy here."}
    return {"flag": False, "note": "Not a known low-liquidity calendar period."}


def check_volume_regime(df: pd.DataFrame, lookback: int = 60, dry_up_threshold: float = 0.4) -> dict:
    """
    Flags if recent volume has dried up relative to its own history --
    thin participation means the "supply/demand" story behind a harmonic
    pattern is much weaker.
    """
    if 'Volume' not in df.columns or len(df) < lookback + 5:
        return {"flag": None, "note": "Not enough volume data to assess."}
    recent = df['Volume'].iloc[-5:].mean()
    baseline = df['Volume'].iloc[-lookback:-5].mean()
    if baseline == 0 or pd.isna(baseline):
        return {"flag": None, "note": "Not enough volume data to assess."}
    ratio = recent / baseline
    dried_up = ratio < dry_up_threshold
    return {
        "flag": dried_up,
        "ratio": round(float(ratio), 2),
        "note": (f"Recent volume is only {ratio:.0%} of its {lookback}-bar baseline -- "
                 f"thin participation, treat signals here with extra caution."
                 if dried_up else f"Volume is {ratio:.0%} of baseline -- normal participation.")
    }


def check_volatility_regime(df: pd.DataFrame, atr_series: pd.Series, lookback: int = 100,
                             extreme_percentile: float = 90.0) -> dict:
    """
    Flags if current volatility is in an extreme percentile of its recent
    history -- either a blowout (stops get run, targets get skipped past)
    or, less commonly, historically compressed (pattern may be too small
    to be tradeable after costs).

    Uses ATR as a % of price (not raw dollar ATR) so the comparison isn't
    biased by the instrument's price level drifting over the lookback
    window -- a stock that's simply risen in price over the year will have
    a naturally rising *dollar* ATR even with unchanged *percentage*
    volatility, which would otherwise show up as a false "elevated
    volatility" flag on every trending instrument, not a real regime change.
    """
    if atr_series is None or len(atr_series.dropna()) < lookback:
        return {"flag": None, "note": "Not enough ATR history to assess."}

    atr_pct = (atr_series / df['Close']).dropna()
    if len(atr_pct) < lookback:
        return {"flag": None, "note": "Not enough ATR history to assess."}

    recent_window = atr_pct.iloc[-lookback:]
    current_val = recent_window.iloc[-1]

    # guard against a single incomplete/partial "today" bar (e.g. fetched
    # mid-session) distorting the reading -- if the current bar's ATR%
    # is a wild multiple of the window's own median, treat it as unreliable
    # data rather than a real volatility regime call
    median_val = recent_window.median()
    if median_val > 0 and current_val > median_val * 4:
        return {"flag": None, "note": "Latest bar's volatility reading looks anomalous "
                                       "(possibly an incomplete/partial bar) -- skipping the volatility check "
                                       "rather than risk a false signal."}

    pct = (recent_window < current_val).mean() * 100

    if pct >= extreme_percentile:
        return {"flag": "high", "percentile": round(float(pct), 1),
                "note": f"Current volatility is in the {pct:.0f}th percentile of the last {lookback} bars -- "
                        f"elevated blowout risk, consider sizing down or skipping."}
    elif pct <= (100 - extreme_percentile):
        return {"flag": "low", "percentile": round(float(pct), 1),
                "note": f"Current volatility is in the {pct:.0f}th percentile (unusually compressed) -- "
                        f"targets may be too tight to clear transaction costs."}
    return {"flag": None, "percentile": round(float(pct), 1),
            "note": f"Volatility is in normal range ({pct:.0f}th percentile)."}


def assess_regime(df: pd.DataFrame, atr_series: pd.Series = None) -> dict:
    """Combined regime check -- call this once per scan per ticker."""
    liquidity_cal = is_low_liquidity_period()
    volume = check_volume_regime(df)
    volatility = check_volatility_regime(df, atr_series) if atr_series is not None else \
        {"flag": None, "note": "No ATR series supplied."}

    tradeable = not liquidity_cal["flag"] and not volume.get("flag") and volatility.get("flag") != "high"

    return {
        "tradeable_regime": tradeable,
        "calendar": liquidity_cal,
        "volume": volume,
        "volatility": volatility,
    }
