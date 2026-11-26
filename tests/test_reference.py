from pathlib import Path

import pandas as pd

from src.generate.config import FAMILIES

DUTY = Path(__file__).resolve().parents[1] / "data" / "reference" / "import_duty.csv"


def test_import_duty_covers_every_ncm_in_scope():
    duty = pd.read_csv(DUTY, dtype={"ncm": str})
    assert set(duty["ncm"]) == {f.ncm for f in FAMILIES}
    assert duty["ncm"].is_unique


def test_import_duty_rates_are_reference_values():
    duty = pd.read_csv(DUTY, dtype={"ncm": str}).set_index("ncm")["ii_pct"]
    assert duty.to_dict() == {"85443000": 16.0, "85366910": 14.4, "85366990": 16.0}
