"""Integrity checks for the purchasing base.

Run:  python -m src.validate  [--db PATH]
Exits with code 1 if any check fails. When data/processed/generator_truth.json is present,
total spend is also checked against it.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from src.db import DEFAULT_DB, connect
from src.generate.config import DEFAULT, Config

SPEND_TOLERANCE = 0.001  # 0.1%


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _count(con: duckdb.DuckDBPyConnection, sql: str, params=None) -> int:
    return con.execute(sql, params or []).fetchone()[0]


def run_checks(con: duckdb.DuckDBPyConnection, cfg: Config = DEFAULT, truth: dict | None = None):
    start = pd.Timestamp(cfg.start_month).date()
    end = (pd.Timestamp(cfg.start_month) + pd.DateOffset(months=cfg.n_months)).date()
    checks = []

    def add(name, bad, what):
        checks.append(Check(name, bad == 0, f"{bad} {what}" if bad else "ok"))

    add(
        "positive_qty_and_price",
        _count(con, "SELECT count(*) FROM purchase_orders WHERE qty <= 0 OR unit_price_usd <= 0"),
        "PO lines with non-positive quantity or price",
    )
    add(
        "orders_inside_window",
        _count(
            con,
            "SELECT count(*) FROM purchase_orders WHERE order_date < ? OR order_date >= ?",
            [start, end],
        ),
        f"PO lines outside {start} to {end}",
    )
    add(
        "delivery_after_order",
        _count(con, "SELECT count(*) FROM purchase_orders WHERE delivery_date < order_date"),
        "PO lines delivered before they were ordered",
    )
    add(
        "every_material_ordered",
        _count(
            con,
            "SELECT count(*) FROM materials WHERE material_id NOT IN "
            "(SELECT material_id FROM purchase_orders)",
        ),
        "materials without purchase orders",
    )
    add(
        "single_source_has_one_supplier",
        _count(
            con,
            "SELECT count(*) FROM (SELECT material_id FROM v_po_lines WHERE single_source "
            "GROUP BY material_id HAVING count(DISTINCT supplier_id) > 1)",
        ),
        "single-source materials bought from more than one supplier",
    )
    share = con.execute("SELECT material_share FROM v_single_source").fetchone()[0]
    checks.append(
        Check(
            "single_source_share",
            abs(share - cfg.single_source_share) < 1e-9,
            f"{share:.1%} of materials (expected {cfg.single_source_share:.0%})",
        )
    )
    add(
        "quotes_per_rfq",
        _count(
            con,
            "SELECT count(*) FROM (SELECT rfq_id FROM quotes GROUP BY rfq_id "
            "HAVING count(DISTINCT supplier_id) <> ?)",
            [cfg.quotes_per_rfq],
        ),
        f"RFQs without exactly {cfg.quotes_per_rfq} distinct suppliers",
    )
    if truth is not None:
        spend = _count(con, "SELECT sum(spend_usd) FROM v_po_lines")
        expected = truth["total_spend_usd"]
        gap = abs(spend / expected - 1)
        checks.append(
            Check(
                "spend_matches_truth",
                gap <= SPEND_TOLERANCE,
                f"USD {spend:,.0f} vs USD {expected:,.0f} expected ({gap:.3%} apart)",
            )
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    truth_path = args.db.with_name("generator_truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else None
    con = connect(args.db)
    checks = run_checks(con, DEFAULT, truth)
    for c in checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:<32} {c.detail}")
    sys.exit(0 if all(c.passed for c in checks) else 1)


if __name__ == "__main__":
    main()
