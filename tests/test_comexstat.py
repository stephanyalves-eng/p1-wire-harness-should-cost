import json
from datetime import date

import pytest

from src.data import download_comexstat as cx
from src.db import connect, create_schema


def api_row(year, month, ncm, country, fob, kg, stat):
    # Comex Stat returns every value as a string.
    return {
        "year": str(year),
        "monthNumber": str(month),
        "coNcm": ncm,
        "country": country,
        "metricFOB": str(fob),
        "metricKG": str(kg),
        "metricStatistic": str(stat),
    }


def payload(rows):
    return {"data": {"list": rows}, "success": True, "message": None}


def test_request_body_asks_for_monthly_imports_by_country():
    body = cx.request_body(["85443000"], "2019-01", "2019-12")
    assert body["flow"] == "import"
    assert body["monthDetail"] is True
    assert body["period"] == {"from": "2019-01", "to": "2019-12"}
    assert body["filters"] == [{"filter": "ncm", "values": ["85443000"]}]
    assert set(body["details"]) == {"country", "ncm"}
    assert set(body["metrics"]) == {"metricFOB", "metricKG", "metricStatistic"}


def test_year_chunks_cover_the_period_without_gaps():
    chunks = cx.year_chunks("2019-01", "2021-06")
    assert chunks == [("2019-01", "2019-12"), ("2020-01", "2020-12"), ("2021-01", "2021-06")]


def test_parse_converts_strings_and_builds_month():
    frame = cx.parse(payload([api_row(2025, 3, "85366990", "China", "1200.5", "80", "4000")]))
    row = frame.iloc[0]
    assert row["month"] == date(2025, 3, 1)
    assert (row["ncm"], row["country"]) == ("85366990", "China")
    assert (row["usd_fob"], row["kg_net"], row["qty_stat"]) == (1200.5, 80.0, 4000.0)


def test_parse_sums_duplicate_keys():
    rows = [
        api_row(2025, 1, "85443000", "Mexico", 100, 10, 10),
        api_row(2025, 1, "85443000", "Mexico", 50, 5, 5),
    ]
    frame = cx.parse(payload(rows))
    assert len(frame) == 1
    assert frame.iloc[0]["usd_fob"] == 150.0


def test_parse_rejects_unexpected_fields():
    with pytest.raises(cx.ComexStatError, match="metricFOB"):
        cx.parse(
            payload([{"year": "2025", "monthNumber": "1", "coNcm": "85443000", "country": "X"}])
        )


def test_parse_rejects_failed_response():
    with pytest.raises(cx.ComexStatError):
        cx.parse({"data": None, "success": False, "message": "bad request"})


def test_extract_caches_each_chunk_and_reuses_it(tmp_path, monkeypatch):
    calls = []

    def fake_post(body):
        calls.append(body["period"]["from"])
        year = int(body["period"]["from"][:4])
        return payload([api_row(year, 1, "85443000", "Germany", 1000, 50, 50)])

    monkeypatch.setattr(cx, "post", fake_post)
    first = cx.extract(["85443000"], "2019-01", "2020-12", tmp_path)
    second = cx.extract(["85443000"], "2019-01", "2020-12", tmp_path)
    assert calls == ["2019-01", "2020-01"]  # second run read the cache
    assert len(first) == len(second) == 2
    assert json.loads((tmp_path / "comexstat_import_2019-01_2019-12.json").read_text())["success"]


def test_retries_on_service_unavailable(monkeypatch):
    attempts = []

    def flaky(request, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise cx.HTTPError(request.full_url, 503, "Service Unavailable", None, None)
        return FakeResponse(payload([]))

    monkeypatch.setattr(cx, "urlopen", flaky)
    monkeypatch.setattr(cx.time, "sleep", lambda s: None)
    assert cx.post(cx.request_body(["85443000"], "2025-01", "2025-01")) == payload([])
    assert len(attempts) == 3


def test_load_replaces_market_rows():
    con = connect(":memory:")
    create_schema(con)
    frame = cx.parse(payload([api_row(2025, 1, "85443000", "Mexico", 300, 3, 3)]))
    cx.load(con, frame)
    cx.load(con, frame)
    assert con.execute("SELECT count(*), sum(usd_fob) FROM market_monthly").fetchone() == (1, 300.0)


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
