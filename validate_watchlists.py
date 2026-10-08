"""
Finds tickers in watchlists.py that Yahoo no longer serves (delisted / renamed) so you can delete or fix them.

    python validate_watchlists.py            # all markets
    python validate_watchlists.py --market INDIA
Writes dead_tickers.txt. (The scanner also auto-skips them, this just gives you the list.)
"""
import argparse
from data_sources import DEFAULT_SOURCE, WATCHLISTS

ap = argparse.ArgumentParser(); ap.add_argument("--market", choices=list(WATCHLISTS)); a = ap.parse_args()
dead = []
for m in ([a.market] if a.market else WATCHLISTS):
    got = DEFAULT_SOURCE.fetch_many(WATCHLISTS[m], "1d", "1mo", m)
    miss = [t for t in WATCHLISTS[m] if t not in got]
    print(f"{m}: {len(got)}/{len(WATCHLISTS[m])} OK, {len(miss)} missing")
    dead += [f"{m},{t}" for t in miss]
open("dead_tickers.txt", "w").write("\n".join(dead))
print("Missing tickers written to dead_tickers.txt")
