import numpy as np, pandas as pd
def random_walk(n=1500, seed=1, vol=0.015, start=100.0, freq="B"):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0, vol, n)))
    open_ = np.r_[start, close[:-1]] * (1 + rng.normal(0, vol * 0.3, n))
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.5, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.5, n)))
    idx = pd.date_range("2018-01-01", periods=n, freq=freq)
    return pd.DataFrame({"Open": open_, "High": hi, "Low": lo, "Close": close, "Volume": rng.integers(1e5, 1e6, n)}, index=idx)
