"""Known-answer tests for implied prices, origin concentration (HHI) and copper lag correlation."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.db import connect, create_schema
from src.market import lag_correlation


@pytest.fixture
def con():
    con = connect(":memory:")
    create_schema(con)
    con.executemany(
        "INSERT INTO market_monthly VALUES (?, ?, ?, ?, ?, ?)",
        [
            # 2025: harnesses split 50/50 between two origins (USD 600 each) -> HHI 5,000
            (date(2025, 1, 1), "85443000", "Mexico", 500.0, 25.0, 25.0),
            (date(2025, 1, 1), "85443000", "China", 500.0, 25.0, 25.0),
            (date(2025, 2, 1), "85443000", "China", 100.0, 5.0, 5.0),
            (date(2025, 2, 1), "85443000", "Mexico", 100.0, 5.0, 5.0),
            # 2025: connectors from one origin only -> HHI 10,000
            (date(2025, 1, 1), "85366990", "Germany", 900.0, 3.0, 300.0),
        ],
    )
    yield con
    con.close()


def test_implied_prices_pool_all_origins(con):
    rows = con.execute(
        "SELECT month, ncm, usd_per_kg, usd_per_unit FROM v_market_implied ORDER BY ncm, month"
    ).fetchall()
    assert rows == [
        (date(2025, 1, 1), "85366990", 300.0, 3.0),
        (date(2025, 1, 1), "85443000", 20.0, 20.0),
        (date(2025, 2, 1), "85443000", 20.0, 20.0),
    ]


def test_hhi_by_ncm_and_year(con):
    rows = dict(
        (ncm, (hhi, top))
        for ncm, hhi, top in con.execute(
            "SELECT ncm, hhi, top_country FROM v_market_hhi WHERE year = 2025"
        ).fetchall()
    )
    assert rows["85443000"][0] == pytest.approx(5000.0)
    assert rows["85366990"] == (pytest.approx(10000.0), "Germany")


def test_origin_shares_add_to_one(con):
    totals = con.execute(
        "SELECT ncm, year, sum(share) FROM v_market_origin_share GROUP BY ncm, year"
    ).fetchall()
    assert all(total == pytest.approx(1.0) for _, _, total in totals)


def test_lag_correlation_finds_the_true_lag():
    rng = np.random.default_rng(0)
    months = pd.date_range("2019-01-01", periods=96, freq="MS")
    copper = pd.Series(9000 * np.exp(np.cumsum(rng.normal(0, 0.05, 96))), index=months)
    price = 0.004 * copper.shift(3) * np.exp(rng.normal(0, 0.005, 96))
    result = lag_correlation(price.dropna(), copper, max_lag=6)
    assert list(result["lag"]) == list(range(7))
    assert result.loc[result["corr"].idxmax(), "lag"] == 3
    assert result.loc[result["lag"] == 3, "corr"].item() > 0.9


def test_lag_correlation_on_levels_option():
    months = pd.date_range("2020-01-01", periods=24, freq="MS")
    copper = pd.Series(np.arange(24, dtype=float) + 100, index=months)
    result = lag_correlation(copper * 2, copper, max_lag=2, method="level")
    assert result["corr"].tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_lag_correlation_rejects_unknown_method():
    s = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2020-01-01", periods=3, freq="MS"))
    with pytest.raises(ValueError):
        lag_correlation(s, s, method="spearman")
