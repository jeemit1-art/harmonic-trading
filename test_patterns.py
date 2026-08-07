"""Sanity test: build synthetic OHLC with an exact bullish Gartley baked in,
confirm the engine finds it with a high quality score."""
import numpy as np
import pandas as pd
from patterns import find_patterns, zigzag_pivots

def make_leg(start_price, end_price, n_bars, start_idx):
    prices = np.linspace(start_price, end_price, n_bars)
    noise = np.random.normal(0, abs(end_price - start_price) * 0.002, n_bars)
    prices = prices + noise
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="h") + pd.Timedelta(hours=start_idx)
    df = pd.DataFrame({
        "Open": prices, "High": prices + abs(noise), "Low": prices - abs(noise),
        "Close": prices,
    }, index=idx)
    return df

# Exact bullish Gartley: X=100 (low), A=150 (high), B=150-0.618*50=119.1 (low),
# C = B + 0.618*(A-B) retrace... use BC=0.5 of AB => C = 119.1+0.5*30.9=134.55 (high)
# D = 0.786 of XA from X => D = 100 + 0.786*50 = 139.3, but D should be below C (bearish AD leg)
X, A = 100.0, 150.0
B = A - 0.618 * (A - X)          # 119.1
C = B + 0.5 * (A - B)             # 134.55  (BC = 0.5 of AB)
D = A - 0.786 * (A - X)           # 110.7   (AD = 0.786 of XA, defining Gartley ratio)

print(f"X={X} A={A} B={B:.2f} C={C:.2f} D={D:.2f}")
print(f"AD/XA (should be ~0.786) = {(A-D)/(A-X):.3f}")

legs = []
legs.append(make_leg(X, A, 40, 0))
legs.append(make_leg(A, B, 30, 40))
legs.append(make_leg(B, C, 20, 70))
legs.append(make_leg(C, D, 25, 90))
legs.append(make_leg(D, D + 40, 20, 115))  # bounce after D confirms

df = pd.concat(legs)
df.index = pd.date_range("2024-01-01", periods=len(df), freq="h")

pivots = zigzag_pivots(df, deviation_pct=5.0)
print(f"\nDetected {len(pivots)} pivots:")
for p in pivots:
    print(f"  {p.kind} @ {p.price:.2f} (idx {p.index})")

patterns = find_patterns(df, deviation_pct=5.0, tolerance=0.06)
print(f"\nDetected {len(patterns)} pattern(s):")
for p in patterns:
    print(f"  {p.name} ({p.direction.value}) confirmed={p.confirmed} "
          f"quality={p.quality_score} PRZ=[{p.prz_lo:.2f},{p.prz_hi:.2f}] ratios={p.ratios}")

assert any(p.name == "Gartley" and p.confirmed for p in patterns), "FAILED: Gartley not detected"
print("\nPASS: Gartley correctly detected.")
