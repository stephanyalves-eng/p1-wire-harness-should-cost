"""Known-answer tests for the should-cost tree, landed cost and calibration."""

import pandas as pd
import pytest

from src import should_cost as sc
from src.generate.config import FAMILIES

SIMPLE = sc.FamilyPremise(
    family="test_harness",
    kind="harness",
    ncm="85443000",
    copper_g=1000.0,
    other_material_usd=5.0,
    labor_min=60.0,
)
RATES = sc.Rates(
    copper_scrap=0.05, overhead_on_labor=0.15, sga=0.08, margin=0.08, copper_mass_share=0.60
)


def test_cost_tree_on_round_numbers():
    # copper 1 kg x 1.05 x USD 10/kg = 10.50; labour 1 h x USD 10 = 10.00; overhead 1.50
    # manufacturing 10.50 + 5.00 + 10.00 + 1.50 = 27.00; SG&A 8% = 2.16; margin 8% of 29.16
    tree = sc.cost_tree(SIMPLE, copper_usd_t=10_000, labor_usd_h=10.0, rates=RATES)
    assert tree["copper"] == pytest.approx(10.50)
    assert tree["other_material"] == pytest.approx(5.00)
    assert tree["labor"] == pytest.approx(10.00)
    assert tree["overhead"] == pytest.approx(1.50)
    assert tree["sga"] == pytest.approx(2.16)
    assert tree["margin"] == pytest.approx(29.16 * 0.08)
    assert tree["ex_works"] == pytest.approx(29.16 * 1.08)
    assert tree["ex_works"] == pytest.approx(sum(tree[k] for k in sc.COMPONENTS))


def test_variant_scales_with_its_copper_content():
    base = sc.cost_tree(SIMPLE, 10_000, 10.0, RATES)
    double = sc.cost_tree(SIMPLE, 10_000, 10.0, RATES, copper_g=2000.0)
    assert double["ex_works"] == pytest.approx(base["ex_works"] * 2)


def test_copper_moves_only_the_copper_line_and_its_markups():
    low = sc.cost_tree(SIMPLE, 10_000, 10.0, RATES)
    high = sc.cost_tree(SIMPLE, 20_000, 10.0, RATES)
    assert high["copper"] == pytest.approx(2 * low["copper"])
    assert high["labor"] == low["labor"]
    assert high["ex_works"] - low["ex_works"] == pytest.approx(10.50 * 1.08 * 1.08)


def test_landed_cost_by_origin():
    ex_works = 100.0
    # Domestic: freight only, no import duty.
    assert sc.landed(ex_works, "BR", "85443000") == pytest.approx(100 * (1 + sc.FREIGHT["BR"]))
    # Mercosur origin: freight, duty-free.
    assert sc.landed(ex_works, "PY", "85443000") == pytest.approx(100 * (1 + sc.FREIGHT["PY"]))
    # Extra-zone origin: duty applies on the freight-inclusive value (CIF basis).
    expected = 100 * (1 + sc.FREIGHT["CN"]) * 1.16
    assert sc.landed(ex_works, "CN", "85443000") == pytest.approx(expected)


def test_mass_per_unit_from_copper_share():
    assert sc.mass_kg(SIMPLE, RATES) == pytest.approx(1.0 / 0.60)


def test_every_family_and_supplier_country_has_premises():
    assert {p.family for p in sc.FAMILY_PREMISES} == {f.name for f in FAMILIES}
    for country in ("BR", "CN", "DE", "JP", "KR", "MX", "US"):
        assert country in sc.LABOR_USD_H
        assert country in sc.FREIGHT


def test_import_duty_comes_from_the_reference_table():
    assert sc.import_duty("85443000", "CN") == pytest.approx(0.16)
    assert sc.import_duty("85366910", "CN") == pytest.approx(0.144)
    assert sc.import_duty("85443000", "PY") == 0.0
    assert sc.import_duty("85443000", "BR") == 0.0


def test_material_should_cost_covers_every_material_supplier_pair():
    materials = pd.DataFrame(
        {
            "material_id": ["M1", "M2"],
            "family": ["harness_engine", "connector_signal"],
            "ncm": ["85443000", "85366990"],
            "copper_g_per_unit": [700.0, 3.0],
        }
    )
    pairs = pd.DataFrame({"material_id": ["M1", "M1", "M2"], "supplier_id": ["S1", "S2", "S3"]})
    countries = pd.DataFrame({"supplier_id": ["S1", "S2", "S3"], "country": ["BR", "CN", "MX"]})
    out = sc.material_should_cost(materials, pairs, countries, copper_usd_t=10_000)
    assert len(out) == 3
    assert (out["landed_usd"] >= out["ex_works_usd"]).all()
    br, cn = out.set_index("supplier_id").loc[["S1", "S2"], "ex_works_usd"]
    assert br != cn  # different labour cost by country


def test_calibration_compares_cost_per_kg_with_import_price():
    market = pd.DataFrame(
        {"country": ["Paraguay", "China"], "usd_per_kg": [20.0, 30.0], "usd_fob": [1.0, 1.0]}
    )
    out = sc.calibrate_harness(market, copper_usd_t=10_000)
    assert set(out["origin"]) == {"Paraguay", "China"}
    row = out.set_index("origin").loc["China"]
    assert row["ratio"] == pytest.approx(row["should_cost_usd_kg"] / 30.0)
