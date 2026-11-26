from datetime import date

import pandas as pd
import pytest

from src.db import connect, create_schema
from src.figures import FIGURES, render_all
from src.generate.config import DEFAULT
from src.generate.purchasing import generate, load, synthetic_copper


@pytest.fixture(scope="module")
def con():
    con = connect(":memory:")
    create_schema(con)
    load(con, generate(DEFAULT))
    months = [date(2024, m, 1) for m in range(1, 13)]
    con.executemany(
        "INSERT INTO market_monthly VALUES (?, ?, ?, ?, ?, ?)",
        [
            (m, "85443000", c, 1000.0 + i, 40.0, 40.0)
            for i, m in enumerate(months)
            for c in ("Paraguay", "China")
        ]
        + [(m, "85366990", "China", 500.0, 10.0, 900.0) for m in months],
    )
    # Copper for the market charts (2023 to mid-2024), then the generator's synthetic series,
    # which covers the purchase orders and their 3-month lag.
    early = pd.date_range("2023-01-01", "2024-07-01", freq="MS")
    con.executemany(
        "INSERT INTO copper_monthly VALUES (?, ?)",
        [(m.date(), 8000.0 + 20 * i) for i, m in enumerate(early)],
    )
    synthetic = synthetic_copper(DEFAULT)
    con.executemany(
        "INSERT INTO copper_monthly VALUES (?, ?)",
        [(m.date(), float(v)) for m, v in synthetic.items()],
    )
    yield con
    con.close()


def test_every_figure_is_written_as_a_png(con, tmp_path):
    paths = render_all(con, tmp_path)
    assert {p.name for p in paths} == {f"{name}.png" for name in FIGURES}
    for p in paths:
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert p.stat().st_size > 10_000


def test_rendering_twice_overwrites_the_same_files(con, tmp_path):
    first = render_all(con, tmp_path)
    second = render_all(con, tmp_path)
    assert first == second
    assert len(list(tmp_path.iterdir())) == len(FIGURES)
