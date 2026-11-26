"""DuckDB connection and schema for the purchasing base."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "sql" / "schema.sql"
VIEWS_SQL = ROOT / "sql" / "views.sql"
DEFAULT_DB = ROOT / "data" / "processed" / "purchasing.duckdb"

TABLES = (
    "suppliers",
    "materials",
    "purchase_orders",
    "quotes",
    "market_monthly",
    "copper_monthly",
    "fx_daily",
)


def connect(path: str | Path = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    """Open the project database; pass ":memory:" for a throwaway one."""
    return duckdb.connect(str(path))


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create every table if it does not exist yet, then (re)create the analytical views."""
    con.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    con.execute(VIEWS_SQL.read_text(encoding="utf-8"))
