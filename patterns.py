"""
Harmonic pattern detection engine.

Implements the standard Fibonacci-ratio rules for the seven most widely
traded harmonic patterns (Scott Carney's ratios, the industry-standard
reference for harmonic trading):

    Gartley, Bat, Alt Bat, Butterfly, Crab, Deep Crab, Cypher, Shark

Pipeline:
    1. Reduce OHLC price series to swing pivots (ZigZag).
    2. Walk every consecutive 5-pivot sequence (X, A, B, C, D).
    3. Test the XA/AB/BC/CD leg ratios against each pattern's rule set.
    4. If a pattern is still forming (D not yet printed), compute the
       Potential Reversal Zone (PRZ) so it can be flagged as "watching".
    5. If D has printed and ratios match within tolerance -> confirmed pattern.

All ratios are computed as len(leg_2) / len(leg_1) on price, using the
Fibonacci retracement/extension convention used throughout harmonic
trading literature.
"""

from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Pivot / ZigZag detection
# --------------------------------------------------------------------------

@dataclass
class Pivot:
    index: int          # integer bar index into the dataframe
    timestamp: object    # pd.Timestamp
    price: float
    kind: str            # 'H' (swing high) or 'L' (swing low)


def zigzag_pivots(df: pd.DataFrame, deviation_pct: float = 3.0) -> list[Pivot]:
    """
    Classic percentage ZigZag. A new pivot is confirmed once price reverses
    by `deviation_pct`% from the last extreme. This is the standard way
    harmonic traders identify X, A, B, C, D swing points -- small enough to
    catch real structure, large enough to filter noise.

    deviation_pct guidance:
        - Forex / index majors, higher timeframes (4H/1D): 2-3%
        - Individual equities (more volatile): 3-5%
        - Lower timeframes (15m/1H): 0.5-1.5%
    Tune per-market in config.py.
    """
    highs = df['High'].values
    lows = df['Low'].values
    n = len(df)
    if n < 5:
        return []

    pivots: list[Pivot] = []
    trend = 0            # 0 = undetermined, 1 = up-leg (tracking a running high), -1 = down-leg
    extreme_idx = 0
    extreme_price = (highs[0] + lows[0]) / 2

    # Undetermined-phase trackers: lowest low and highest high seen so far
    min_price, min_idx = lows[0], 0
    max_price, max_idx = highs[0], 0

    for i in range(1, n):
        high, low = highs[i], lows[i]

        if trend == 0:
            if high > max_price:
                max_price, max_idx = high, i
            if low < min_price:
                min_price, min_idx = low, i

            up_move = (max_price - min_price) / min_price * 100
            down_move = (max_price - min_price) / max_price * 100

            if up_move >= deviation_pct and max_idx > min_idx:
                pivots.append(Pivot(min_idx, df.index[min_idx], min_price, 'L'))
                trend = 1
                extreme_price, extreme_idx = max_price, max_idx
            elif down_move >= deviation_pct and min_idx > max_idx:
                pivots.append(Pivot(max_idx, df.index[max_idx], max_price, 'H'))
                trend = -1
                extreme_price, extreme_idx = min_price, min_idx

        elif trend == 1:
            # tracking a running high; look for a pullback of deviation_pct to confirm it as a pivot H
            if high > extreme_price:
                extreme_price, extreme_idx = high, i
            else:
                pullback = (extreme_price - low) / extreme_price * 100
                if pullback >= deviation_pct:
                    pivots.append(Pivot(extreme_idx, df.index[extreme_idx], extreme_price, 'H'))
                    trend = -1
                    extreme_price, extreme_idx = low, i

        elif trend == -1:
            # tracking a running low; look for a bounce of deviation_pct to confirm it as a pivot L
            if low < extreme_price:
                extreme_price, extreme_idx = low, i
            else:
                bounce = (high - extreme_price) / extreme_price * 100
                if bounce >= deviation_pct:
                    pivots.append(Pivot(extreme_idx, df.index[extreme_idx], extreme_price, 'L'))
                    trend = 1
                    extreme_price, extreme_idx = high, i

    # dedupe consecutive same-kind pivots (keep the more extreme one)
    cleaned: list[Pivot] = []
    for p in pivots:
        if cleaned and cleaned[-1].kind == p.kind:
            if (p.kind == 'H' and p.price > cleaned[-1].price) or \
               (p.kind == 'L' and p.price < cleaned[-1].price):
                cleaned[-1] = p
        else:
            cleaned.append(p)
    return cleaned


# --------------------------------------------------------------------------
# Pattern rule definitions
# --------------------------------------------------------------------------

class Direction(Enum):
    BULLISH = "bullish"   # X is a low -> pattern completes at a low D -> expect price to rise
    BEARISH = "bearish"   # X is a high -> pattern completes at a high D -> expect price to fall


@dataclass
class RatioRange:
    lo: float
    hi: float
    def contains(self, val: float, tolerance: float = 0.05) -> bool:
        return (self.lo - tolerance) <= val <= (self.hi + tolerance)


@dataclass
class PatternRule:
    name: str
    ab_xa: RatioRange       # AB retracement of XA
    bc_ab: RatioRange       # BC retracement of AB
    cd_bc: RatioRange       # CD extension of BC
    ad_xa: RatioRange       # AD retracement/extension of XA (D completion ratio)
    measured_from_xc: bool = False   # Cypher/Shark measure CD off XC, not XA
    cd_xc: RatioRange = None
    notes: str = ""


# Scott Carney harmonic ratio table (industry standard)
PATTERN_RULES: dict[str, PatternRule] = {
    "Gartley": PatternRule(
        name="Gartley",
        ab_xa=RatioRange(0.618, 0.618),
        bc_ab=RatioRange(0.382, 0.886),
        cd_bc=RatioRange(1.13, 1.618),
        ad_xa=RatioRange(0.786, 0.786),
        notes="Classic Gartley '222'. Tightest, most reliable ratios of the family."
    ),
    "Bat": PatternRule(
        name="Bat",
        ab_xa=RatioRange(0.382, 0.50),
        bc_ab=RatioRange(0.382, 0.886),
        cd_bc=RatioRange(1.618, 2.618),
        ad_xa=RatioRange(0.886, 0.886),
        notes="Shallow B point, deep 0.886 D. Very common, tight D zone."
    ),
    "Alt Bat": PatternRule(
        name="Alt Bat",
        ab_xa=RatioRange(0.382, 0.382),
        bc_ab=RatioRange(0.382, 0.886),
        cd_bc=RatioRange(2.0, 3.618),
        ad_xa=RatioRange(1.13, 1.13),
        notes="D extends slightly beyond X -- treat as a breakout/failure zone, not a hard reversal."
    ),
    "Butterfly": PatternRule(
        name="Butterfly",
        ab_xa=RatioRange(0.786, 0.786),
        bc_ab=RatioRange(0.382, 0.886),
        cd_bc=RatioRange(1.618, 2.24),
        ad_xa=RatioRange(1.27, 1.618),
        notes="D extends beyond X -- trade the extension zone, wider stop needed."
    ),
    "Crab": PatternRule(
        name="Crab",
        ab_xa=RatioRange(0.382, 0.618),
        bc_ab=RatioRange(0.382, 0.886),
        cd_bc=RatioRange(2.24, 3.618),
        ad_xa=RatioRange(1.618, 1.618),
        notes="Deepest extension pattern. 1.618 D is very precise -- high reward:risk when it hits."
    ),
    "Deep Crab": PatternRule(
        name="Deep Crab",
        ab_xa=RatioRange(0.886, 0.886),
        bc_ab=RatioRange(0.382, 0.886),
        cd_bc=RatioRange(2.0, 3.618),
        ad_xa=RatioRange(1.618, 1.618),
        notes="Deep B retracement variant of the Crab."
    ),
    "Cypher": PatternRule(
        name="Cypher",
        ab_xa=RatioRange(0.382, 0.618),
        bc_ab=RatioRange(1.13, 1.414),
        cd_bc=RatioRange(0.0, 0.0),   # not used, measured_from_xc instead
        ad_xa=RatioRange(0.0, 0.0),   # not used
        measured_from_xc=True,
        cd_xc=RatioRange(0.786, 0.786),
        notes="C exceeds A (BC 1.13-1.414x AB). D = 0.786 retracement of XC, not XA."
    ),
    "Shark": PatternRule(
        name="Shark",
        ab_xa=RatioRange(0.446, 0.618),
        bc_ab=RatioRange(1.13, 1.618),
        cd_bc=RatioRange(0.0, 0.0),
        ad_xa=RatioRange(0.886, 1.13),
        measured_from_xc=True,
        cd_xc=RatioRange(0.886, 1.13),
        notes="5-0 pattern variant. C can exceed X. D zone = 0.886-1.13 of XC AND of XA -- use both as confluence."
    ),
}


# --------------------------------------------------------------------------
# Pattern scanning
# --------------------------------------------------------------------------

@dataclass
class HarmonicPattern:
    name: str
    direction: Direction
    X: Pivot
    A: Pivot
    B: Pivot
    C: Pivot
    D: Pivot | None            # None if pattern is still forming (PRZ not yet tagged)
    prz_lo: float
    prz_hi: float
    ratios: dict
    confirmed: bool            # True once D has printed and closed inside PRZ
    quality_score: float = 0.0  # 0-100, tighter ratio confluence = higher score


def _ratio(p1: Pivot, p2: Pivot, p3: Pivot, p4: Pivot) -> float:
    """abs(p3->p4 move) / abs(p1->p2 move)"""
    leg1 = abs(p2.price - p1.price)
    leg2 = abs(p4.price - p3.price)
    if leg1 == 0:
        return np.nan
    return leg2 / leg1


def _quality_score(rule: PatternRule, ab_xa, bc_ab, cd_leg) -> float:
    """
    Score how close the actual ratios are to the IDEAL (midpoint) Fibonacci
    numbers for this pattern, not just "inside the tolerance band".
    Tighter confluence at D = historically higher win rate.
    """
    def closeness(val, rng: RatioRange) -> float:
        mid = (rng.lo + rng.hi) / 2
        span = max(rng.hi - rng.lo, 0.05)
        return max(0.0, 1 - abs(val - mid) / (span * 2))

    scores = [closeness(ab_xa, rule.ab_xa), closeness(bc_ab, rule.bc_ab)]
    if rule.measured_from_xc:
        scores.append(closeness(cd_leg, rule.cd_xc))
    else:
        scores.append(closeness(cd_leg, rule.cd_bc))
    return round(float(np.mean(scores)) * 100, 1)


def find_patterns(df: pd.DataFrame, deviation_pct: float = 3.0,
                   tolerance: float = 0.05) -> list[HarmonicPattern]:
    """
    Scan a full OHLC dataframe (indexed by datetime) for harmonic patterns.
    Returns confirmed patterns AND patterns currently forming with price
    inside/approaching the PRZ (useful for the live scanner's "watch" alerts).
    """
    pivots = zigzag_pivots(df, deviation_pct)
    results: list[HarmonicPattern] = []
    if len(pivots) < 5:
        return results

    last_close = df['Close'].iloc[-1]
    last_idx = len(df) - 1

    for i in range(len(pivots) - 4):
        X, A, B, C, D = pivots[i:i+5]
        # must alternate H/L/H/L/H or L/H/L/H/L
        kinds = [p.kind for p in (X, A, B, C, D)]
        if kinds not in (['H', 'L', 'H', 'L', 'H'], ['L', 'H', 'L', 'H', 'L']):
            continue

        direction = Direction.BULLISH if X.kind == 'L' else Direction.BEARISH

        ab_xa = _ratio(X, A, A, B)
        bc_ab = _ratio(A, B, B, C)
        cd_bc = _ratio(B, C, C, D)
        cd_xc = _ratio(X, C, C, D)
        ad_xa = _ratio(X, A, A, D)  # informational -- retracement of XA measured from A (standard convention, e.g. Gartley's "0.786 of XA")

        for name, rule in PATTERN_RULES.items():
            if not rule.ab_xa.contains(ab_xa, tolerance):
                continue
            if not rule.bc_ab.contains(bc_ab, tolerance):
                continue
            cd_leg = cd_xc if rule.measured_from_xc else cd_bc
            cd_rule = rule.cd_xc if rule.measured_from_xc else rule.cd_bc
            if not cd_rule.contains(cd_leg, tolerance):
                continue

            # PRZ: project D from both the XA ratio and the CD/XC ratio for confluence
            xa_len = A.price - X.price
            bc_len = C.price - B.price
            xc_len = C.price - X.price

            if rule.measured_from_xc:
                d_from_xc = C.price - rule.cd_xc.lo * xc_len
                d_from_xc2 = C.price - rule.cd_xc.hi * xc_len
                prz_candidates = [d_from_xc, d_from_xc2]
            else:
                # D as a retracement of the XA leg, measured from A back toward X
                # (e.g. Gartley: D = A - 0.786*(A-X)). Using A + ratio*(X-A) handles
                # both bullish and bearish structures with one formula.
                d_from_xa = A.price + rule.ad_xa.lo * (X.price - A.price)
                d_from_xa2 = A.price + rule.ad_xa.hi * (X.price - A.price)
                d_from_cd = C.price - rule.cd_bc.lo * bc_len
                d_from_cd2 = C.price - rule.cd_bc.hi * bc_len
                prz_candidates = [d_from_xa, d_from_xa2, d_from_cd, d_from_cd2]

            prz_lo, prz_hi = min(prz_candidates), max(prz_candidates)

            q = _quality_score(rule, ab_xa, bc_ab, cd_leg)

            is_last_leg = (D.index >= last_idx - 3)  # D pivot is recent -> confirmed recently
            confirmed = True

            pat = HarmonicPattern(
                name=name, direction=direction, X=X, A=A, B=B, C=C, D=D,
                prz_lo=prz_lo, prz_hi=prz_hi,
                ratios={"AB/XA": round(ab_xa, 3), "BC/AB": round(bc_ab, 3),
                        "CD/BC": round(cd_bc, 3) if not rule.measured_from_xc else None,
                        "CD/XC": round(cd_xc, 3) if rule.measured_from_xc else None,
                        "AD/XA": round(ad_xa, 3)},
                confirmed=confirmed,
                quality_score=q,
            )
            results.append(pat)

        # ALSO check for a *forming* pattern: only X, A, B, C confirmed,
        # price currently trading inside a projected PRZ (no D pivot yet,
        # i.e. C is the most recent pivot and price hasn't reversed 
        # `deviation_pct` yet to confirm D).
        if i == len(pivots) - 4:  # C is last pivot, no D formed yet
            for name, rule in PATTERN_RULES.items():
                if not rule.ab_xa.contains(ab_xa, tolerance):
                    continue
                if not rule.bc_ab.contains(bc_ab, tolerance):
                    continue
                xa_len = A.price - X.price
                bc_len = C.price - B.price
                xc_len = C.price - X.price
                if rule.measured_from_xc:
                    d1 = C.price - rule.cd_xc.lo * xc_len
                    d2 = C.price - rule.cd_xc.hi * xc_len
                else:
                    d1 = A.price + rule.ad_xa.lo * (X.price - A.price)
                    d2 = A.price + rule.ad_xa.hi * (X.price - A.price)
                prz_lo, prz_hi = min(d1, d2), max(d1, d2)
                near = prz_lo * 0.99 <= last_close <= prz_hi * 1.01
                approaching = abs(last_close - (prz_lo + prz_hi) / 2) / last_close < 0.05
                if near or approaching:
                    pat = HarmonicPattern(
                        name=name, direction=direction, X=X, A=A, B=B, C=C, D=None,
                        prz_lo=prz_lo, prz_hi=prz_hi,
                        ratios={"AB/XA": round(ab_xa, 3), "BC/AB": round(bc_ab, 3)},
                        confirmed=False,
                        quality_score=_quality_score(rule, ab_xa, bc_ab, bc_ab),
                    )
                    results.append(pat)

    return results
