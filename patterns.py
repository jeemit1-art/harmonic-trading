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
    confirmed_at: int = -1   # bar index at which this pivot became KNOWABLE (reversal >= deviation)


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
                pivots.append(Pivot(min_idx, df.index[min_idx], min_price, 'L', confirmed_at=i))
                trend = 1
                extreme_price, extreme_idx = max_price, max_idx
            elif down_move >= deviation_pct and min_idx > max_idx:
                pivots.append(Pivot(max_idx, df.index[max_idx], max_price, 'H', confirmed_at=i))
                trend = -1
                extreme_price, extreme_idx = min_price, min_idx

        elif trend == 1:
            # tracking a running high; look for a pullback of deviation_pct to confirm it as a pivot H
            if high > extreme_price:
                extreme_price, extreme_idx = high, i
            else:
                pullback = (extreme_price - low) / extreme_price * 100
                if pullback >= deviation_pct:
                    pivots.append(Pivot(extreme_idx, df.index[extreme_idx], extreme_price, 'H', confirmed_at=i))
                    trend = -1
                    extreme_price, extreme_idx = low, i

        elif trend == -1:
            # tracking a running low; look for a bounce of deviation_pct to confirm it as a pivot L
            if low < extreme_price:
                extreme_price, extreme_idx = low, i
            else:
                bounce = (high - extreme_price) / extreme_price * 100
                if bounce >= deviation_pct:
                    pivots.append(Pivot(extreme_idx, df.index[extreme_idx], extreme_price, 'L', confirmed_at=i))
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
    also_matches: list = field(default_factory=list)  # other rule names this same structure satisfied
    tentative: bool = False   # D is the running extreme (not yet a confirmed zigzag pivot)


def _ratio(p1: Pivot, p2: Pivot, p3: Pivot, p4: Pivot) -> float:
    """abs(p3->p4 move) / abs(p1->p2 move)"""
    leg1 = abs(p2.price - p1.price)
    leg2 = abs(p4.price - p3.price)
    if leg1 == 0:
        return np.nan
    return leg2 / leg1


def _quality_score(rule: PatternRule, ab_xa, bc_ab, cd_leg, ad_xa=None) -> float:
    """How close are the actual ratios to the IDEAL (midpoint) numbers for this rule."""
    def closeness(val, rng: RatioRange) -> float:
        mid = (rng.lo + rng.hi) / 2
        span = max(rng.hi - rng.lo, 0.05)
        return max(0.0, 1 - abs(val - mid) / (span * 2))

    scores = [closeness(ab_xa, rule.ab_xa), closeness(bc_ab, rule.bc_ab)]
    scores.append(closeness(cd_leg, rule.cd_xc if rule.measured_from_xc else rule.cd_bc))
    if ad_xa is not None and not (rule.ad_xa.lo == 0.0 and rule.ad_xa.hi == 0.0):
        scores.append(closeness(ad_xa, rule.ad_xa))
    return round(float(np.mean(scores)) * 100, 1)


# Where D should sit relative to X for each family. 'inside' = D between X and A
# (Gartley/Bat/Cypher retrace), 'beyond' = D past X (Alt Bat/Butterfly/Crab extend),
# 'any' = either side (Shark's 0.886-1.13 zone straddles X).
D_VS_X = {"Gartley": "inside", "Bat": "inside", "Cypher": "inside", "Alt Bat": "beyond",
          "Butterfly": "beyond", "Crab": "beyond", "Deep Crab": "beyond", "Shark": "any"}


def _geometry_ok(name: str, direction: Direction, X, A, B, C, D) -> bool:
    """Reject structures whose swing geometry is impossible for the named pattern."""
    s = 1.0 if direction == Direction.BULLISH else -1.0
    x, a, b, c = (s * p.price for p in (X, A, B, C))
    if not (a > x and x < b < a):
        return False
    if name in ("Cypher", "Shark"):
        if not c > a:
            return False
    elif not c < a:
        return False
    if D is not None:
        d = s * D.price
        if not d < c:
            return False
        rel = D_VS_X.get(name, "any")
        if rel == "inside" and not d > x:
            return False
        if rel == "beyond" and not d < x:
            return False
    return True


def _structure_matches(direction, X, A, B, C, D, tolerance):
    """All rules a concrete X-A-B-C-D structure satisfies -> [(quality, name, prz_lo, prz_hi)], best first."""
    ab_xa, bc_ab = _ratio(X, A, A, B), _ratio(A, B, B, C)
    cd_bc, cd_xc, ad_xa = _ratio(B, C, C, D), _ratio(X, C, C, D), _ratio(X, A, A, D)
    if any(np.isnan(v) for v in (ab_xa, bc_ab, cd_bc, cd_xc, ad_xa)):
        return [], {}
    out = []
    for name, rule in PATTERN_RULES.items():
        if not rule.ab_xa.contains(ab_xa, tolerance) or not rule.bc_ab.contains(bc_ab, tolerance):
            continue
        if rule.measured_from_xc:
            if not rule.cd_xc.contains(cd_xc, tolerance):
                continue
            if not (rule.ad_xa.lo == 0.0 and rule.ad_xa.hi == 0.0) and not rule.ad_xa.contains(ad_xa, tolerance):
                continue
        elif not (rule.cd_bc.contains(cd_bc, tolerance) or rule.ad_xa.contains(ad_xa, tolerance)):
            continue
        if not _geometry_ok(name, direction, X, A, B, C, D):
            continue
        bc_len, xc_len = C.price - B.price, C.price - X.price
        if rule.measured_from_xc:
            cands = [C.price - rule.cd_xc.lo * xc_len, C.price - rule.cd_xc.hi * xc_len]
        else:
            cands = [A.price + rule.ad_xa.lo * (X.price - A.price), A.price + rule.ad_xa.hi * (X.price - A.price),
                     C.price - rule.cd_bc.lo * bc_len, C.price - rule.cd_bc.hi * bc_len]
        q = _quality_score(rule, ab_xa, bc_ab, cd_xc if rule.measured_from_xc else cd_bc, ad_xa)
        out.append((q, name, min(cands), max(cands)))
    out.sort(reverse=True)
    ratios = {"AB/XA": round(ab_xa, 3), "BC/AB": round(bc_ab, 3), "CD/BC": round(cd_bc, 3),
              "CD/XC": round(cd_xc, 3), "AD/XA": round(ad_xa, 3)}
    return out, ratios


def _make(direction, X, A, B, C, D, matches, ratios, confirmed, tentative):
    q, name, lo, hi = matches[0]
    return HarmonicPattern(name=name, direction=direction, X=X, A=A, B=B, C=C, D=D, prz_lo=lo, prz_hi=hi,
                           ratios=ratios, confirmed=confirmed, quality_score=q,
                           also_matches=[m[1] for m in matches[1:]], tentative=tentative)


def find_patterns(df: pd.DataFrame, deviation_pct: float = 3.0, tolerance: float = 0.05,
                  include_forming: bool = True, include_tentative: bool = False) -> list[HarmonicPattern]:
    """
    Scan CLOSED bars for harmonic patterns.

    v2 changes vs the original:
      * One result per structure (best rule wins; others in `also_matches`).
        The old code returned one structure as Gartley AND Bat AND ... ->
        duplicate alerts with contradictory plans.
      * Geometry validation (D side of C and of X per family).
      * The old "forming" branch was unreachable (`i == len(pivots)-4` inside
        `range(len(pivots)-4)`). Fixed.
      * include_tentative: treat the running extreme since C as a CANDIDATE D.
        A zigzag pivot only confirms after a full `deviation_pct` reversal, by
        which point most of the move to T1 has already happened -- the root
        cause of "alerts arrive late". A candidate D lets the engine trigger on
        the reversal candle at the PRZ instead. Backtest decides if it pays.
    """
    pivots = zigzag_pivots(df, deviation_pct)
    results: list[HarmonicPattern] = []
    if len(pivots) < 4:
        return results

    for i in range(len(pivots) - 4):
        X, A, B, C, D = pivots[i:i + 5]
        kinds = [p.kind for p in (X, A, B, C, D)]
        if kinds not in (['H', 'L', 'H', 'L', 'H'], ['L', 'H', 'L', 'H', 'L']):
            continue
        direction = Direction.BULLISH if X.kind == 'L' else Direction.BEARISH
        matches, ratios = _structure_matches(direction, X, A, B, C, D, tolerance)
        if matches:
            results.append(_make(direction, X, A, B, C, D, matches, ratios, True, False))

    X, A, B, C = pivots[-4:]
    if [p.kind for p in (X, A, B, C)] not in (['H', 'L', 'H', 'L'], ['L', 'H', 'L', 'H']):
        return results
    direction = Direction.BULLISH if X.kind == 'L' else Direction.BEARISH
    bull = direction == Direction.BULLISH

    if include_tentative and C.index + 2 < len(df):
        after = df.iloc[C.index + 1:]
        j = C.index + 1 + int(np.argmin(after['Low'].values) if bull else np.argmax(after['High'].values))
        if j < len(df) - 1:
            px = float(df['Low'].iloc[j] if bull else df['High'].iloc[j])
            Dt = Pivot(j, df.index[j], px, 'L' if bull else 'H', confirmed_at=j)
            matches, ratios = _structure_matches(direction, X, A, B, C, Dt, tolerance)
            if matches:
                results.append(_make(direction, X, A, B, C, Dt, matches, ratios, False, True))

    if include_forming:
        last_close = float(df['Close'].iloc[-1])
        ab_xa, bc_ab = _ratio(X, A, A, B), _ratio(A, B, B, C)
        if (last_close < C.price if bull else last_close > C.price) and not (np.isnan(ab_xa) or np.isnan(bc_ab)):
            best = None
            for name, rule in PATTERN_RULES.items():
                if not rule.ab_xa.contains(ab_xa, tolerance) or not rule.bc_ab.contains(bc_ab, tolerance):
                    continue
                if not _geometry_ok(name, direction, X, A, B, C, None):
                    continue
                if rule.measured_from_xc:
                    xc = C.price - X.price
                    d1, d2 = C.price - rule.cd_xc.lo * xc, C.price - rule.cd_xc.hi * xc
                else:
                    d1 = A.price + rule.ad_xa.lo * (X.price - A.price)
                    d2 = A.price + rule.ad_xa.hi * (X.price - A.price)
                lo, hi = min(d1, d2), max(d1, d2)
                dist = 0.0 if lo <= last_close <= hi else min(abs(last_close - lo), abs(last_close - hi)) / last_close
                if dist <= 0.015:
                    q = _quality_score(rule, ab_xa, bc_ab, bc_ab, None)
                    if best is None or q > best[0]:
                        best = (q, name, lo, hi)
            if best:
                q, name, lo, hi = best
                results.append(HarmonicPattern(name=name, direction=direction, X=X, A=A, B=B, C=C, D=None,
                                               prz_lo=lo, prz_hi=hi, ratios={"AB/XA": round(ab_xa, 3), "BC/AB": round(bc_ab, 3)},
                                               confirmed=False, quality_score=q))
    return results
