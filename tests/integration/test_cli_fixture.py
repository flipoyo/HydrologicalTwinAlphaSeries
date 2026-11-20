"""htas on the public CaWaQS test case: describe, then one operation, end to end.

Skipped without ``CWAQS_FIXTURE_ROOT`` (``tests/README.md`` has the recipe).
"""

import json
import os
from pathlib import Path

import pytest

from HydrologicalTwinAlphaSeries.cli import main


def test_describe_and_budget_barplot_on_the_fixture(tmp_path, capsys):
    root = os.environ.get("CWAQS_FIXTURE_ROOT")
    if not root or not Path(root).is_dir():
        pytest.skip("CWAQS_FIXTURE_ROOT is not set. See tests/README.md.")
    fixture = Path(root).resolve()
    out = fixture / "cawaqs_simulation" / "OUTPUT"
    config = out / "PostProcessing" / "CONFIG" / "config_geometries_Testcase_4comp.json"
    if not config.is_file():
        pytest.skip(f"geometry config not found at {config}")
    gis = fixture / "gis_data"
    twin = [
        "--out-caw", str(out), "--geometry-config", str(config), "--years", "1970", "1972",
        "--layer", f"GRID_AQ={gis / 'DATA_AQ' / 'GRID_AQ.shp'}",
        "--layer", f"ELEM_MUSK={gis / 'DATA_HYD' / 'ELEM_MUSK.shp'}",
        "--layer", f"GRID_NSAT={gis / 'DATA_NSAT' / 'GRID_NSAT.shp'}",
        "--layer", f"LIEN_BU_METEO={gis / 'DATA_SURF' / 'LIEN_BU_METEO.shp'}",
        "--layer", f"OBS_AQ={gis / 'DATA_OBS' / 'OBS_AQ.shp'}",
        "--layer", f"OBS_HYD={gis / 'DATA_OBS' / 'OBS_HYD.shp'}",
    ]

    assert main(["describe", "--json", *twin]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "LOADED"

    assert main(["budget", "barplot", "--period", "1970-01-01", "1972-12-31", "--frequency", "Y",
                 "--agg", "sum", "--output-dir", str(tmp_path), "--json", *twin]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert Path(result["png_path"]).is_file()
