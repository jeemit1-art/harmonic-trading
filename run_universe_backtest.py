"""
Pooled, honest backtest -- run this on YOUR machine (needs Yahoo access) BEFORE trusting any alert.

    python run_universe_backtest.py --market US --n 40 --period 10y
    python run_universe_backtest.py --market FOREX --n 28 --period 700d

Prints pooled stats, the bootstrap lower bound, an in/out-of-sample split by date, and a GO/NO-GO verdict.
"""
import argparse
import numpy as np
import config
from data_sources import DEFAULT_SOURCE, WATCHLISTS
from backtest import run_backtest, summarize

ap = argparse.ArgumentParser()
ap.add_argument("--market", required=True, choices=list(WATCHLISTS))
ap.add_argument("--n", type=int, default=40)
ap.add_argument("--period", default="10y")
ap.add_argument("--deviation", type=float, default=None)
ap.add_argument("--min-quality", type=float, default=None)
a = ap.parse_args()

tf = config.SCAN_TIMEFRAMES[a.market]
dev = a.deviation or config.ZIGZAG_DEVIATION[a.market]
data = DEFAULT_SOURCE.fetch_many(WATCHLISTS[a.market][:a.n], tf, a.period, a.market)
print(f"{len(data)} tickers loaded ({tf}, {a.period}), deviation {dev}%, cost {config.COST_PCT[a.market]}% round trip")
allp = []
for t, d in data.items():
    r = run_backtest(d, market=a.market, ticker=t, timeframe=tf, deviation_pct=dev, min_quality=a.min_quality)
    allp += r.get("trades", [])
    print(f"  {t:12s} {r.get('n_trades', 0):3d} trades")
res = summarize(allp, 10000, config.RISK_PER_TRADE_PCT)
if not res["n_trades"]:
    raise SystemExit("No trades generated.")
allp.sort(key=lambda p: p["closed_at"])
half = len(allp) // 2
a1, a2 = summarize(allp[:half], 10000, 1), summarize(allp[half:], 10000, 1)
print(f"\nPOOLED: {res['n_trades']} trades | win {res['win_rate_pct']}% | expectancy {res['expectancy_r']}R | "
      f"5th pct {res['expectancy_r_p5']}R | PF {res['profit_factor']} | maxDD {res['max_drawdown_pct']}%")
print(f"first half {a1.get('expectancy_r')}R ({a1.get('n_trades')})  vs  second half {a2.get('expectancy_r')}R ({a2.get('n_trades')})")
for k, v in res["by_pattern"].items():
    print(f"  {k:10s} n={v['n']:3d} avgR={v['avg_r']:+.2f} win={v['win_rate']}%")
ok = res["n_trades"] >= 100 and res["expectancy_r_p5"] > 0 and a2.get("expectancy_r", -1) > 0
print("\nVERDICT:", "GO (paper trade next)" if ok else "NO-GO: not enough evidence of an edge -- do not trade real money on these alerts")
