"""
Confluence add-ons. Raw Fibonacci-ratio pattern matches alone have a
mediocre hit rate (harmonic trading literature and independent backtests
generally put unfiltered pattern completion around 45-55% win rate). What
consistently improves this in practice:

  1. RSI/Stochastic divergence at D  -- price makes a new extreme into the
     PRZ while momentum doesn't confirm it. This is the single most cited
     harmonic confluence factor (Carney calls it part of the "3-step
     confirmation").
  2. Volume climax/exhaustion at D -- a volume spike into the reversal zone
     suggests capitulation/blow-off rather than continuation.
  3. Higher-timeframe trend context -- patterns that complete in the
     direction of the higher-timeframe trend (counter-trend pullback
     completing) historically outperform patterns fighting a strong HTF trend.
  4. PRZ confluence width -- tighter overlap between the XA-based and
     BC/XC-based D projections (already scored in quality_score) matters,
     but combining it with the above raises reliability further.

None of this is a guarantee -- it's a filter that trims the weakest setups.
"""
import numpy as np
import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def check_rsi_divergence(df: pd.DataFrame, pattern, lookback: int = 30) -> dict:
    """
    Bullish pattern -> want bullish (regular) divergence at D: price makes a
    lower low than C, but RSI makes a higher low.
    Bearish pattern -> want bearish divergence: price higher high than C,
    RSI lower high.
    """
    r = rsi(df['Close'])
    if pattern.D is None:
        return {"has_divergence": False, "note": "Pattern not yet confirmed (D not printed)"}

    c_idx, d_idx = pattern.C.index, pattern.D.index
    if c_idx >= len(r) or d_idx >= len(r) or pd.isna(r.iloc[c_idx]) or pd.isna(r.iloc[d_idx]):
        return {"has_divergence": False, "note": "Insufficient data for RSI"}

    rsi_c, rsi_d = r.iloc[c_idx], r.iloc[d_idx]
    price_c, price_d = pattern.C.price, pattern.D.price

    if pattern.direction.value == "bullish":
        divergence = price_d < price_c and rsi_d > rsi_c
    else:
        divergence = price_d > price_c and rsi_d < rsi_c

    return {
        "has_divergence": bool(divergence),
        "rsi_at_C": round(float(rsi_c), 1),
        "rsi_at_D": round(float(rsi_d), 1),
        "note": "Momentum confirms reversal" if divergence else "No RSI divergence -- weaker signal"
    }


def check_volume_climax(df: pd.DataFrame, pattern, lookback: int = 20) -> dict:
    if 'Volume' not in df.columns or pattern.D is None:
        return {"has_climax": False, "note": "No volume data"}
    d_idx = pattern.D.index
    if d_idx >= len(df):
        return {"has_climax": False, "note": "Insufficient data"}
    window = df['Volume'].iloc[max(0, d_idx - lookback):d_idx + 1]
    if len(window) < 5 or window.mean() == 0:
        return {"has_climax": False, "note": "Insufficient data"}
    vol_at_d = df['Volume'].iloc[d_idx]
    avg_vol = window.iloc[:-1].mean()
    climax = vol_at_d > avg_vol * 1.5
    return {
        "has_climax": bool(climax),
        "volume_ratio": round(float(vol_at_d / avg_vol), 2) if avg_vol else None,
        "note": "Volume spike at D -- possible capitulation" if climax else "Normal volume at D"
    }


def check_htf_trend(htf_df: pd.DataFrame, pattern, ma_period: int = 50) -> dict:
    """
    Pass in a higher-timeframe dataframe (e.g. daily, if the pattern was
    found on 4h). Checks whether the pattern direction is a pullback INTO
    the higher-timeframe trend (favourable) or a fight AGAINST it (riskier).
    """
    if len(htf_df) < ma_period:
        return {"aligned": None, "note": "Not enough HTF history for trend MA"}
    ma = htf_df['Close'].rolling(ma_period).mean().iloc[-1]
    last_close = htf_df['Close'].iloc[-1]
    htf_trend_up = last_close > ma

    if pattern.direction.value == "bullish":
        aligned = htf_trend_up
    else:
        aligned = not htf_trend_up

    return {
        "aligned": bool(aligned),
        "htf_trend": "up" if htf_trend_up else "down",
        "note": ("Pattern aligns with higher-timeframe trend (favourable)" if aligned
                 else "Pattern is counter to higher-timeframe trend (lower conviction, size down)")
    }


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def check_macd_divergence(df: pd.DataFrame, pattern) -> dict:
    """
    Same divergence logic as RSI but on the MACD histogram -- a second,
    independent momentum read. When RSI AND MACD both diverge at D, that's
    materially stronger confluence than either alone.
    """
    if pattern.D is None:
        return {"has_divergence": False, "note": "Pattern not yet confirmed (D not printed)"}
    _, _, hist = macd(df['Close'])
    c_idx, d_idx = pattern.C.index, pattern.D.index
    if c_idx >= len(hist) or d_idx >= len(hist) or pd.isna(hist.iloc[c_idx]) or pd.isna(hist.iloc[d_idx]):
        return {"has_divergence": False, "note": "Insufficient data for MACD"}

    hist_c, hist_d = hist.iloc[c_idx], hist.iloc[d_idx]
    price_c, price_d = pattern.C.price, pattern.D.price

    if pattern.direction.value == "bullish":
        divergence = price_d < price_c and hist_d > hist_c
    else:
        divergence = price_d > price_c and hist_d < hist_c

    return {
        "has_divergence": bool(divergence),
        "macd_hist_at_C": round(float(hist_c), 4),
        "macd_hist_at_D": round(float(hist_d), 4),
        "note": "MACD histogram confirms reversal" if divergence else "No MACD divergence"
    }


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([
        high - low, (high - close.shift()).abs(), (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


def check_adx_trend(df: pd.DataFrame, pattern, strong_threshold: float = 30.0) -> dict:
    """
    Harmonic reversals fighting a strongly trending market (ADX > ~30) have
    a materially lower hit rate. Not disqualifying on its own, but a
    warning flag -- treat as a reason to size down or skip counter-trend
    patterns when ADX is high.
    """
    idx = pattern.D.index if pattern.D is not None else pattern.C.index
    a = adx(df)
    if idx >= len(a) or pd.isna(a.iloc[idx]):
        return {"adx": None, "strong_trend": None, "note": "Insufficient data for ADX"}
    val = float(a.iloc[idx])
    strong = val > strong_threshold
    warning = strong  # any strongly trending market is a caution for a reversal trade
    return {
        "adx": round(val, 1),
        "strong_trend": strong,
        "note": (f"ADX {val:.1f} -- market strongly trending, counter-trend reversal risk elevated"
                 if warning else f"ADX {val:.1f} -- no strong trend, favourable for a reversal setup")
    }


def _is_bullish_engulfing(o1, c1, o2, c2) -> bool:
    return c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1


def _is_bearish_engulfing(o1, c1, o2, c2) -> bool:
    return c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1


def _is_hammer(o, h, l, c) -> bool:
    body = abs(c - o)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    return body > 0 and lower_wick >= body * 2 and upper_wick <= body * 0.5


def _is_shooting_star(o, h, l, c) -> bool:
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return body > 0 and upper_wick >= body * 2 and lower_wick <= body * 0.5


def check_candlestick_confirmation(df: pd.DataFrame, pattern, max_bars_after_d: int = 3) -> dict:
    """
    Requires an actual rejection candle at/after D before treating the
    pattern as tradeable -- this is what separates a real reversal from
    price just passing through the PRZ on its way somewhere else. Checked
    across up to `max_bars_after_d` bars following D (or following the most
    recent bar if D hasn't printed yet but price is inside the PRZ).

    Looks for: engulfing candle, hammer/shooting star, or a simple pin bar
    (long wick rejecting the PRZ) in the pattern's favoured direction.
    """
    bullish = pattern.direction.value == "bullish"
    anchor_idx = pattern.D.index if pattern.D is not None else pattern.C.index
    end_idx = min(anchor_idx + max_bars_after_d + 1, len(df))
    if anchor_idx + 1 >= len(df):
        return {"confirmed": False, "note": "Not enough bars yet after D to check for a confirmation candle"}

    o = df['Open'].values
    h = df['High'].values
    l = df['Low'].values
    c = df['Close'].values

    for i in range(anchor_idx + 1, end_idx):
        prev = i - 1
        if bullish:
            if _is_bullish_engulfing(o[prev], c[prev], o[i], c[i]):
                return {"confirmed": True, "type": "Bullish engulfing", "bar_index": i,
                        "note": "Bullish engulfing candle confirms rejection at the PRZ"}
            if _is_hammer(o[i], h[i], l[i], c[i]):
                return {"confirmed": True, "type": "Hammer", "bar_index": i,
                        "note": "Hammer candle confirms rejection at the PRZ"}
        else:
            if _is_bearish_engulfing(o[prev], c[prev], o[i], c[i]):
                return {"confirmed": True, "type": "Bearish engulfing", "bar_index": i,
                        "note": "Bearish engulfing candle confirms rejection at the PRZ"}
            if _is_shooting_star(o[i], h[i], l[i], c[i]):
                return {"confirmed": True, "type": "Shooting star", "bar_index": i,
                        "note": "Shooting star candle confirms rejection at the PRZ"}

    return {"confirmed": False, "type": None, "bar_index": None,
            "note": "No confirmation candle yet -- wait, don't enter on the raw PRZ touch alone"}


def score_confluence(df: pd.DataFrame, pattern, htf_df: pd.DataFrame = None) -> dict:
    """Combine all confluence checks into one summary + adjusted confidence score."""
    rsi_check = check_rsi_divergence(df, pattern)
    macd_check = check_macd_divergence(df, pattern)
    vol_check = check_volume_climax(df, pattern)
    adx_check = check_adx_trend(df, pattern)
    candle_check = check_candlestick_confirmation(df, pattern)
    htf_check = check_htf_trend(htf_df, pattern) if htf_df is not None else {"aligned": None, "note": "No HTF data supplied"}

    bonus = 0
    if rsi_check.get("has_divergence"):
        bonus += 8
    if macd_check.get("has_divergence"):
        bonus += 6
    if vol_check.get("has_climax"):
        bonus += 4
    if htf_check.get("aligned") is True:
        bonus += 6
    elif htf_check.get("aligned") is False:
        bonus -= 6
    if adx_check.get("strong_trend") is True:
        bonus -= 5
    if candle_check.get("confirmed"):
        bonus += 10

    adjusted_score = max(0, min(100, pattern.quality_score + bonus))

    # entry_ready: the gate for an "ENTER NOW" alert. Requires the
    # candlestick confirmation (non-negotiable -- don't enter on a raw PRZ
    # touch) AND at least one momentum confluence (RSI or MACD divergence).
    entry_ready = bool(candle_check.get("confirmed")) and (
        rsi_check.get("has_divergence") or macd_check.get("has_divergence")
    )

    return {
        "base_quality_score": pattern.quality_score,
        "adjusted_score": round(adjusted_score, 1),
        "rsi": rsi_check,
        "macd": macd_check,
        "volume": vol_check,
        "adx": adx_check,
        "candlestick": candle_check,
        "htf_trend": htf_check,
        "entry_ready": entry_ready,
    }
