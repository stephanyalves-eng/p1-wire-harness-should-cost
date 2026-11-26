"""Monthly copper price (USD/t) from the World Bank Pink Sheet.

The workbook link changes with every monthly edition, so it is read from the Commodity
Markets page. The file is saved to data/raw/pinksheet/ and the copper series replaces the
copper_monthly table.

Run:  python -m src.data.download_pinksheet  [--offline]   (--offline reuses the saved file)
Source: https://www.worldbank.org/en/research/commodity-markets (CC BY 4.0)
"""

import argparse
import re
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import duckdb
import openpyxl
import pandas as pd

from src.db import DEFAULT_DB, ROOT, connect, create_schema

PAGE = "https://www.worldbank.org/en/research/commodity-markets"
RAW_FILE = ROOT / "data" / "raw" / "pinksheet" / "CMO-Historical-Data-Monthly.xlsx"
SHEET = "Monthly Prices"
HEADER_ROW = 4  # zero-based: series names; the next row holds units, data follows
SERIES = "Copper"
USER_AGENT = "Mozilla/5.0 (compatible; p1-wire-harness-should-cost data download)"


class PinkSheetError(RuntimeError):
    pass


def find_url(page_html: str) -> str:
    match = re.search(r'https://[^"\s]+/CMO-Historical-Data-Monthly\.xlsx', page_html)
    if not match:
        raise PinkSheetError("monthly workbook link not found on the Commodity Markets page")
    return match.group(0)


def _get(url: str, timeout: int) -> bytes:
    # worldbank.org answers 403 to urllib's default User-Agent.
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def download(path: Path = RAW_FILE) -> Path:
    url = find_url(_get(PAGE, timeout=60).decode("utf-8", "replace"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_get(url, timeout=120))
    return path


def _rows(path: Path) -> list[tuple]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return list(wb[SHEET].iter_rows(values_only=True))
    finally:
        wb.close()


def updated_on(path: Path) -> str | None:
    for row in _rows(path)[:HEADER_ROW]:
        if row and isinstance(row[0], str) and row[0].startswith("Updated on "):
            return row[0].removeprefix("Updated on ")
    return None


def parse(path: Path) -> pd.DataFrame:
    rows = _rows(path)
    header = rows[HEADER_ROW]
    if SERIES not in header:
        raise PinkSheetError(f"no {SERIES!r} column in {SHEET!r}")
    col = header.index(SERIES)
    records = []
    for row in rows[HEADER_ROW + 2 :]:
        label, value = row[0], row[col]
        if not (isinstance(label, str) and re.fullmatch(r"\d{4}M\d{2}", label)):
            continue
        if not isinstance(value, int | float):  # "…" marks a missing value
            continue
        records.append(
            {"month": date(int(label[:4]), int(label[5:]), 1), "copper_usd_t": float(value)}
        )
    return pd.DataFrame(records, columns=["month", "copper_usd_t"])


def load(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> None:
    con.execute("DELETE FROM copper_monthly")
    con.execute("INSERT INTO copper_monthly BY NAME SELECT * FROM frame")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="reuse the saved workbook")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    path = RAW_FILE if args.offline else download()
    frame = parse(path)
    con = connect(args.db)
    create_schema(con)
    load(con, frame)
    last = frame.iloc[-1]
    print(
        f"{len(frame)} months of copper, {frame['month'].min()} to {last['month']} "
        f"(last USD {last['copper_usd_t']:,.0f}/t); Pink Sheet updated on {updated_on(path)}"
    )


if __name__ == "__main__":
    main()
