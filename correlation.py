"""
Correlation and risk-cap enforcement. Being long three different
resource-sector ASX stocks via three different patterns simultaneously
isn't three independent bets -- it's one bet on commodities wearing three
costumes. This module tags each ticker with a rough asset-class/sector
bucket and blocks a new ENTER NOW if it would push correlated exposure or
overall open-risk past the configured caps.

This is a coarse, config-driven classification, not a real correlation
matrix -- good enough to stop the obvious cases (stacking multiple trades
in the same sector or same currency) without needing a market-data
subscription for real covariance.
"""
import config

# Rough bucket per ticker. Edit freely -- this only needs to be directionally
# right (group things that actually move together), not perfectly precise.
TICKER_BUCKETS = {
    # AUS
    "BHP.AX": "commodities", "RIO.AX": "commodities", "FMG.AX": "commodities", "STO.AX": "energy",
    "CBA.AX": "aus_banks", "NAB.AX": "aus_banks", "WBC.AX": "aus_banks", "ANZ.AX": "aus_banks",
    "CSL.AX": "healthcare", "WES.AX": "consumer", "WOW.AX": "consumer", "MQG.AX": "aus_banks",
    # US
    "AAPL": "us_tech", "MSFT": "us_tech", "NVDA": "us_tech", "GOOGL": "us_tech", "META": "us_tech",
    "AMZN": "us_consumer", "TSLA": "us_consumer_disc", "SPY": "us_broad", "QQQ": "us_tech",
    "JPM": "us_banks", "XOM": "energy", "AMD": "us_tech",
    # India
    "RELIANCE.NS": "india_conglomerate", "TCS.NS": "india_tech", "INFY.NS": "india_tech",
    "HDFCBANK.NS": "india_banks", "ICICIBANK.NS": "india_banks", "SBIN.NS": "india_banks",
    "BHARTIARTL.NS": "india_telecom", "ITC.NS": "india_consumer", "LT.NS": "india_industrial",
    "TATAMOTORS.NS": "india_auto",
    # Forex -- bucket by base currency exposure, the dominant driver of correlation
    "AUDUSD=X": "aud", "AUDJPY=X": "aud", "NZDUSD=X": "nzd",
    "EURUSD=X": "eur", "EURJPY=X": "eur", "GBPUSD=X": "gbp",
    "USDJPY=X": "jpy_usd", "USDCAD=X": "cad_usd",
}


def get_bucket(ticker: str) -> str:
    return TICKER_BUCKETS.get(ticker, f"unclassified:{ticker}")


def check_risk_caps(state: dict, market: str, ticker: str, pattern_name: str,
                     direction: str, risk_pct: float = None) -> dict:
    """
    Check whether opening a new trade in (market, ticker, pattern) would
    breach any configured cap, given the currently OPEN/PARTIAL setups in
    trade_state. Returns {"allowed": bool, "reason": str}.
    """
    risk_pct = risk_pct if risk_pct is not None else config.RISK_PER_TRADE_PCT
    open_setups = [s for s in state.values() if s["status"] in ("OPEN", "PARTIAL_T1", "PARTIAL_T2")]

    # 1. overall concurrent-trade cap
    if len(open_setups) >= config.MAX_CONCURRENT_TRADES:
        return {"allowed": False,
                "reason": f"Already {len(open_setups)} concurrent open trades "
                          f"(cap: {config.MAX_CONCURRENT_TRADES}). Skipping new entry until one closes."}

    # 2. daily risk cap -- approximate open risk as risk_pct per open trade
    #    that hasn't reached breakeven yet (post-T1 trades risk ~0 on the stop)
    at_risk_pct = sum(risk_pct if s["status"] == "OPEN" else 0 for s in open_setups)
    if at_risk_pct + risk_pct > config.MAX_DAILY_RISK_PCT:
        return {"allowed": False,
                "reason": f"Adding this trade would put ~{at_risk_pct + risk_pct:.1f}% of equity at risk "
                          f"simultaneously (cap: {config.MAX_DAILY_RISK_PCT}%). Skipping."}

    # 3. correlation cap -- same bucket AND same directional bias already open
    new_bucket = get_bucket(ticker)
    same_bucket_same_dir = [
        s for s in open_setups
        if get_bucket(s["ticker"]) == new_bucket and s["direction"] == direction
        and s["ticker"] != ticker
    ]
    max_correlated = getattr(config, "MAX_CORRELATED_TRADES", 2)
    if len(same_bucket_same_dir) >= max_correlated:
        others = ", ".join(s["ticker"] for s in same_bucket_same_dir)
        return {"allowed": False,
                "reason": f"Already {len(same_bucket_same_dir)} open {direction} trade(s) correlated with "
                          f"{ticker} (bucket: {new_bucket}) via {others}. This isn't independent risk -- skipping."}

    return {"allowed": True, "reason": "Within risk and correlation caps."}
