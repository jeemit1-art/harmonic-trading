"""
Data fetching layer. Uses yfinance (free) as the default source across all
four markets. Swap in a broker feed later by writing another class with the
same `.fetch(ticker, interval, period)` interface -- nothing else in the
system needs to change.
"""
import pandas as pd
import time

try:
    import yfinance as yf
except ImportError:
    yf = None


class YFinanceSource:
    """
    Ticker suffix cheat-sheet (yfinance / Yahoo Finance convention):
        AUS (ASX)  -> 'BHP.AX', 'CBA.AX', 'CSL.AX' ...
        US         -> 'AAPL', 'MSFT', 'SPY' ...
        India      -> 'RELIANCE.NS', 'TCS.NS', 'INFY.NS' (NSE) or '.BO' for BSE
        Forex      -> 'AUDUSD=X', 'EURUSD=X', 'USDJPY=X', 'GBPUSD=X' ...
    """
    name = "yfinance"

    def fetch(self, ticker: str, interval: str = "1h", period: str = "60d",
              retries: int = 3) -> pd.DataFrame:
        if yf is None:
            raise RuntimeError("yfinance not installed. Run: pip install yfinance")

        # yfinance limits how far back intraday intervals go; clamp sensibly
        intraday_caps = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
                          "1h": "730d", "60m": "730d"}
        if interval in intraday_caps:
            max_period = intraday_caps[interval]
            period = max_period if period == "max" else period

        last_err = None
        for attempt in range(retries):
            try:
                df = yf.download(ticker, interval=interval, period=period,
                                  progress=False, auto_adjust=True)
                if df is None or df.empty:
                    raise ValueError(f"No data returned for {ticker}")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                return df
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {ticker} after {retries} attempts: {last_err}")


DEFAULT_SOURCE = YFinanceSource()


# --------------------------------------------------------------------------
# Watchlists -- edit freely. Kept small & liquid by default; liquid names
# form cleaner, more reliable harmonic structures than thin/illiquid ones.
# --------------------------------------------------------------------------

WATCHLISTS = {
    "AUS": [
        "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX",
        "WES.AX", "MQG.AX", "FMG.AX", "WOW.AX", "STO.AX", "RIO.AX",
    ],
    "US": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
        "SPY", "QQQ", "JPM", "XOM", "AMD",
    ],
    "INDIA": [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "TMPV.NS",
    ],
    "FOREX": [
        "AUDUSD=X", "EURUSD=X", "GBPUSD=X", "USDJPY=X",
        "USDCAD=X", "NZDUSD=X", "EURJPY=X", "AUDJPY=X",
    ],
}

# Suggested ZigZag deviation % per market / timeframe (starting points --
# tune per-instrument once you see how it behaves in backtests).
DEFAULT_DEVIATION = {
    "AUS": 3.0, "US": 3.0, "INDIA": 3.0, "FOREX": 0.6,
}
