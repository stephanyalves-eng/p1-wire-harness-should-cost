"""Monthly Brazilian imports by NCM and country of origin from the Comex Stat API (MDIC).

Each year is requested separately and the raw JSON is cached in data/raw/comexstat/, so a
rerun does not call the API again unless --refresh is given. The parsed rows replace the
matching months and NCMs in the market_monthly table.

Run:  python -m src.data.download_comexstat  [--from 2019-01] [--to YYYY-MM] [--refresh]
API documentation: https://api-comexstat.mdic.gov.br/docs
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb
import pandas as pd

from src.db import DEFAULT_DB, ROOT, connect, create_schema
from src.generate.config import FAMILIES

API = "https://api-comexstat.mdic.gov.br"
RAW_DIR = ROOT / "data" / "raw" / "comexstat"
NCMS = sorted({f.ncm for f in FAMILIES})
METRICS = {"metricFOB": "usd_fob", "metricKG": "kg_net", "metricStatistic": "qty_stat"}
RETRY_STATUS = {429, 500, 502, 503, 504}


class ComexStatError(RuntimeError):
    pass


def request_body(ncms: list[str], start: str, end: str) -> dict:
    return {
        "flow": "import",
        "monthDetail": True,
        "period": {"from": start, "to": end},
        "filters": [{"filter": "ncm", "values": list(ncms)}],
        "details": ["country", "ncm"],
        "metrics": list(METRICS),
    }


def year_chunks(start: str, end: str) -> list[tuple[str, str]]:
    """Split a YYYY-MM period into calendar-year requests."""
    first, last = int(start[:4]), int(end[:4])
    chunks = []
    for year in range(first, last + 1):
        lo = start if year == first else f"{year}-01"
        hi = end if year == last else f"{year}-12"
        chunks.append((lo, hi))
    return chunks


def post(body: dict, retries: int = 5, timeout: int = 120) -> dict:
    """POST to /general, retrying with backoff when the service is busy or down."""
    request = Request(
        f"{API}/general?language=en",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as err:
            if err.code not in RETRY_STATUS or attempt == retries:
                raise ComexStatError(f"Comex Stat returned HTTP {err.code}") from err
        except URLError as err:
            if attempt == retries:
                raise ComexStatError(f"Comex Stat unreachable: {err.reason}") from err
        time.sleep(min(60, 5 * 2 ** (attempt - 1)))
    raise ComexStatError("unreachable")  # loop always returns or raises


def parse(payload: dict) -> pd.DataFrame:
    """Turn one API response into market_monthly rows."""
    if not payload.get("success") or not isinstance(payload.get("data"), dict):
        raise ComexStatError(f"request failed: {payload.get('message')!r}")
    rows = payload["data"].get("list") or []
    columns = ["month", "ncm", "country", *METRICS.values()]
    if not rows:
        return pd.DataFrame(columns=columns)

    frame = pd.DataFrame(rows)
    missing = [c for c in ("year", "monthNumber", "coNcm", "country", *METRICS) if c not in frame]
    if missing:
        raise ComexStatError(f"response is missing fields {missing}; got {list(frame.columns)}")

    out = pd.DataFrame(
        {
            "month": [
                date(int(y), int(m), 1)
                for y, m in zip(frame["year"], frame["monthNumber"], strict=True)
            ],
            "ncm": frame["coNcm"].astype(str).str.zfill(8),
            "country": frame["country"].astype(str),
        }
    )
    for field, column in METRICS.items():
        out[column] = pd.to_numeric(frame[field]).astype(float)
    return out.groupby(["month", "ncm", "country"], as_index=False)[list(METRICS.values())].sum()


def extract(
    ncms: list[str], start: str, end: str, raw_dir: Path = RAW_DIR, refresh: bool = False
) -> pd.DataFrame:
    raw_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for lo, hi in year_chunks(start, end):
        cache = raw_dir / f"comexstat_import_{lo}_{hi}.json"
        if cache.exists() and not refresh:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        else:
            payload = post(request_body(ncms, lo, hi))
            cache.write_text(json.dumps(payload), encoding="utf-8")
        frames.append(parse(payload))
    return pd.concat(frames, ignore_index=True)


def load(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> None:
    """Replace the months and NCMs present in `frame`, leaving other rows untouched."""
    if frame.empty:
        return
    con.execute(
        "DELETE FROM market_monthly WHERE (month, ncm) IN (SELECT DISTINCT month, ncm FROM frame)"
    )
    con.execute("INSERT INTO market_monthly BY NAME SELECT * FROM frame")


def latest_month() -> str:
    """Last month published by Comex Stat, or the previous calendar month if unknown."""
    try:
        with urlopen(f"{API}/general/dates/updated", timeout=30) as response:
            updated = json.loads(response.read())["data"]
        return f"{int(updated['year'])}-{int(updated['monthNumber']):02d}"
    except (HTTPError, URLError, KeyError, TypeError, ValueError):
        prev = pd.Timestamp.today().normalize().replace(day=1) - pd.DateOffset(months=1)
        return prev.strftime("%Y-%m")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", default="2019-01")
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--refresh", action="store_true", help="ignore the raw cache")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    end = args.end or latest_month()
    frame = extract(NCMS, args.start, end, refresh=args.refresh)
    con = connect(args.db)
    create_schema(con)
    load(con, frame)
    summary = frame.groupby("ncm")[["usd_fob", "kg_net"]].sum() / 1e6
    print(f"{len(frame)} rows, {args.start} to {end}, extracted {date.today()}")
    print(summary.round(1).rename(columns={"usd_fob": "usd_fob_m", "kg_net": "kg_net_m"}))


if __name__ == "__main__":
    main()
