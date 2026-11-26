from datetime import date

import openpyxl
import pytest

from src.data import download_pinksheet as ps
from src.db import connect, create_schema

PAGE = """
<a href="https://thedocs.worldbank.org/en/doc/abc-0050012026/related/CMO-Pink-Sheet-November-2026.pdf">PDF</a>
<a href="https://thedocs.worldbank.org/en/doc/abc-0050012026/related/CMO-Historical-Data-Monthly.xlsx">Monthly</a>
<a href="https://thedocs.worldbank.org/en/doc/abc-0050012026/related/CMO-Historical-Data-Annual.xlsx">Annual</a>
"""


def workbook(path):
    """A tiny file with the Pink Sheet layout: titles, header row, unit row, then data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Monthly Prices"
    ws.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    ws.append(["monthly prices in nominal US dollars, 1960 to present"])
    ws.append(["(monthly series are available only in nominal US dollars)"])
    ws.append(["Updated on November 03, 2026"])
    ws.append([None, "Crude oil, average", "Copper"])
    ws.append([None, "($/bbl)", "($/mt)"])
    ws.append(["1960M01", 1.63, "…"])
    ws.append(["2026M09", 70.1, 14474])
    ws.append(["2026M10", 69.8, 14508.5])
    wb.save(path)
    return path


def test_finds_the_monthly_workbook_link():
    assert ps.find_url(PAGE).endswith("/CMO-Historical-Data-Monthly.xlsx")


def test_missing_link_raises():
    with pytest.raises(ps.PinkSheetError):
        ps.find_url("<html>no link here</html>")


def test_parse_reads_copper_and_skips_missing_values(tmp_path):
    frame = ps.parse(workbook(tmp_path / "pink.xlsx"))
    assert frame.to_dict("records") == [
        {"month": date(2026, 9, 1), "copper_usd_t": 14474.0},
        {"month": date(2026, 10, 1), "copper_usd_t": 14508.5},
    ]


def test_parse_reports_the_update_date(tmp_path):
    assert ps.updated_on(workbook(tmp_path / "pink.xlsx")) == "November 03, 2026"


def test_load_replaces_the_series(tmp_path):
    con = connect(":memory:")
    create_schema(con)
    frame = ps.parse(workbook(tmp_path / "pink.xlsx"))
    ps.load(con, frame)
    ps.load(con, frame)
    assert con.execute("SELECT count(*), max(copper_usd_t) FROM copper_monthly").fetchone() == (
        2,
        14508.5,
    )
