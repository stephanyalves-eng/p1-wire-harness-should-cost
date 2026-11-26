"""Market intelligence: how import prices move with copper.

Implied prices and origin concentration are SQL views (v_market_implied, v_market_hhi in
sql/views.sql). This module adds the lag correlation, which is easier to express in pandas.
"""

import numpy as np
import pandas as pd


def lag_correlation(
    price: pd.Series, copper: pd.Series, max_lag: int = 6, method: str = "log_diff"
) -> pd.DataFrame:
    """Pearson correlation between a monthly price and copper k months earlier, k = 0..max_lag.

    method="log_diff" correlates month-over-month log changes, which avoids the spurious
    correlation two trending series show in levels. method="level" correlates the levels.
    Both series must be indexed by month start.
    """
    if method not in {"log_diff", "level"}:
        raise ValueError(f"unknown method {method!r}; use 'log_diff' or 'level'")
    transform = (lambda s: np.log(s).diff()) if method == "log_diff" else (lambda s: s)
    p, c = transform(price.sort_index()), transform(copper.sort_index())
    rows = []
    for lag in range(max_lag + 1):
        pair = pd.concat([p, c.shift(lag, freq="MS")], axis=1, join="inner").dropna()
        corr = pair.iloc[:, 0].corr(pair.iloc[:, 1]) if len(pair) > 2 else np.nan
        rows.append({"lag": lag, "corr": corr, "n": len(pair)})
    return pd.DataFrame(rows)
