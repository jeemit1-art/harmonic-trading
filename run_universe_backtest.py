"""
Pooled, honest backtest across a whole watchlist.

    python run_universe_backtest.py --market US --n 0 --period 10y      # n=0 means ALL tickers
    python run_universe_backtest.py --market FOREX --n 0 --period 700d
    python run_universe_backtest.py --market AUS --n 60                   # quick trial

Prints pooled stats, a bootstrap lower bound on expectancy, first-half vs second-half
results, and a GO / NO-GO verdict. Also writes backtest_<market>.csv with every trade.
"""
import argparse, os
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

import config
from data_sources import DEFAULT_SOURCE, WATCHLISTS
from backtest import run_backtest, summarize


def _one(args):
    t, d, market, tf, dev, minq = args
    try:
        r = run_backtest(d, market=market, ticker=t, timeframe=tf, deviation_pct=dev, min_quality=minq)
        return t, r.get("trades", [])
    except Exception as e:
        return t, f"ERR {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=list(WATCHLISTS))
    ap.add_argument("--n", type=int, default=0, help="how many tickers (0 = all)")
    ap.add_argument("--period", default="10y")
    ap.add_argument("--deviation", type=float, default=None)
    ap.add_argument("--min-quality", type=float, default=None)
    a = ap.parse_args()

    tf = config.SCAN_TIMEFRAMES[a.market]
    dev = a.deviation or config.ZIGZAG_DEVIATION[a.market]
    tickers = WATCHLISTS[a.market] if a.n == 0 else WATCHLISTS[a.market][:a.n]
    print(f"Downloading {len(tickers)} {a.market} tickers ({tf}, {a.period}) ...", flush=True)
    data = DEFAULT_SOURCE.fetch_many(tickers, tf, a.period, a.market)
    data = {t: d for t, d in data.items() if len(d) > 150}
    print(f"{len(data)} tickers have enough data. Round-trip cost {config.COST_PCT[a.market]}%, deviation {dev}%.", flush=True)

    jobs = [(t, d, a.market, tf, dev, a.min_quality) for t, d in data.items()]
    allp, errs = [], 0
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for i, (t, res) in enumerate(ex.map(_one, jobs), 1):
            if isinstance(res, str):
                errs += 1
            else:
                allp += res
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} tickers done, {len(allp)} trades so far", flush=True)
    if errs:
        print(f"({errs} tickers errored and were skipped)")

    res = summarize(allp, 10000, config.RISK_PER_TRADE_PCT)
    if not res["n_trades"]:
        raise SystemExit("No trades generated -- nothing to evaluate.")
    allp.sort(key=lambda p: p["closed_at"])
    half = len(allp) // 2
    a1, a2 = summarize(allp[:half], 10000, 1), summarize(allp[half:], 10000, 1)
    pd.DataFrame([{k: v for k, v in p.items() if k not in ("points", "confluence")} for p in allp]).to_csv(f"backtest_{a.market}.csv", index=False)

    print(f"\nPOOLED {a.market}: {res['n_trades']} trades | win {res['win_rate_pct']}% | expectancy {res['expectancy_r']}R | "
          f"5th-percentile {res['expectancy_r_p5']}R | profit factor {res['profit_factor']} | max drawdown {res['max_drawdown_pct']}%")
    print(f"First half {a1.get('expectancy_r')}R ({a1.get('n_trades')} trades)   vs   second half {a2.get('expectancy_r')}R ({a2.get('n_trades')} trades)")
    for k, v in sorted(res["by_pattern"].items(), key=lambda kv: -kv[1]["avg_r"]):
        print(f"  {k:10s} n={v['n']:4d}  avgR={v['avg_r']:+.2f}  win={v['win_rate']}%")
    ok = res["n_trades"] >= 100 and res["expectancy_r_p5"] > 0 and a2.get("expectancy_r", -1) > 0
    print("\nVERDICT:", "GO -> paper trade next (still not proof)" if ok else
          "NO-GO: not enough evidence of an edge. Do not trade real money on these alerts.")


if __name__ == "__main__":
    main()
