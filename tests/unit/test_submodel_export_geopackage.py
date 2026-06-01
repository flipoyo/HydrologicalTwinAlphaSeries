"""Unit tests for the Tier-1 GeoPackage writer ``save_area_geopackage``."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.ht import ValuesResponse
from HydrologicalTwinAlphaSeries.services.private.submodel_export import (
    save_area_geopackage,
)


def _make_cells(compartment: str, n_cells: int, base_cell_id: int):
    geoms = [box(i, 0, i + 1, 1) for i in range(n_cells)]
    cell_ids = list(range(base_cell_id, base_cell_id + n_cells))
    return gpd.GeoDataFrame(
        {"cell_id": cell_ids}, geometry=geoms, crs="EPSG:2154"
    )


def _make_responses(n_cells: int, n_days: int, params, seed: int = 0):
    dates = np.array([f"2000-01-0{i + 1}" for i in range(n_days)])
    responses = {}
    for k, param in enumerate(params):
        data = (
            np.arange(n_cells * n_days, dtype=float) + (k + seed) * 100
        ).reshape(n_cells, n_days)
        responses[param] = ValuesResponse(data=data, dates=dates)
    return responses


def _provenance_row(compartment: str, params, area_name: str = "basin_test"):
    return {
        "source_run": "/tmp/out_caw",
        "syear": 2000,
        "eyear": 2000,
        "polygon_crs": "EPSG:2154",
        "area_name": area_name,
        "polygon_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "generated_at": "2026-05-28T12:00:00+00:00",
        "htas_ver": "000.alpha.test",
        "compartment": compartment,
        "params": json.dumps(list(params)),
        "weighted": False,
    }


def _make_watbal_fixture(n_cells: int = 3, n_days: int = 5, params=("rain", "runoff")):
    """Single-compartment (WATBAL) block, in the generalised shape."""
    cells_gdf = _make_cells("WATBAL", n_cells, base_cell_id=10)
    responses = _make_responses(n_cells, n_days, params)
    blocks = {"WATBAL": (cells_gdf, responses, None)}
    prov_rows = [_provenance_row("WATBAL", params)]
    return blocks, prov_rows


def test_save_area_geopackage_writes_three_datasets(tmp_path: Path):
    blocks, prov_rows = _make_watbal_fixture()
    gpkg_path = str(tmp_path / "basin_test_InternalValues_2000_2000.gpkg")

    save_area_geopackage(gpkg_path, blocks, prov_rows)

    assert Path(gpkg_path).exists()

    cells_back = gpd.read_file(gpkg_path, layer="cells_WATBAL")
    assert len(cells_back) == 3
    assert set(cells_back.columns) >= {"cell_id", "geometry"}
    assert cells_back.crs is not None
    assert cells_back.crs.to_string() == "EPSG:2154"

    with sqlite3.connect(gpkg_path) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert len(daily) == 3 * 5 * 2
    assert set(daily.columns) == {
        "compartment", "cell_id", "date", "param", "value", "unit",
    }
    assert set(daily["compartment"].unique()) == {"WATBAL"}
    assert set(daily["param"].unique()) == {"rain", "runoff"}
    assert (daily["unit"] == "mm/j").all()

    assert len(prov) == 1
    prov_row = prov.iloc[0].to_dict()
    assert prov_row["compartment"] == "WATBAL"
    assert prov_row["area_name"] == "basin_test"
    assert prov_row["polygon_crs"] == "EPSG:2154"
    assert prov_row["htas_ver"] == "000.alpha.test"


def test_save_area_geopackage_multi_compartment_bundle(tmp_path: Path):
    """WATBAL + AQ in one bundle: a cells_<compartment> layer per mesh, a
    compartment-keyed daily_values, and one provenance row per compartment."""
    watbal_cells = _make_cells("WATBAL", n_cells=3, base_cell_id=10)
    aq_cells = _make_cells("AQ", n_cells=2, base_cell_id=10)  # overlapping ids
    blocks = {
        "WATBAL": (
            watbal_cells,
            _make_responses(3, 4, ("rain",)),
            None,
        ),
        "AQ": (
            aq_cells,
            _make_responses(2, 4, ("recharge",), seed=5),
            None,
        ),
    }
    prov_rows = [
        _provenance_row("WATBAL", ("rain",)),
        _provenance_row("AQ", ("recharge",)),
    ]
    gpkg_path = str(tmp_path / "basin_test_InternalValues_2000_2000.gpkg")

    save_area_geopackage(gpkg_path, blocks, prov_rows)

    cells_watbal = gpd.read_file(gpkg_path, layer="cells_WATBAL")
    cells_aq = gpd.read_file(gpkg_path, layer="cells_AQ")
    assert len(cells_watbal) == 3
    assert len(cells_aq) == 2

    with sqlite3.connect(gpkg_path) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert set(daily["compartment"].unique()) == {"WATBAL", "AQ"}
    assert len(daily) == 3 * 4 * 1 + 2 * 4 * 1

    # Every (compartment, cell_id) resolves to a geometry in the matching mesh.
    watbal_ids = set(cells_watbal["cell_id"])
    aq_ids = set(cells_aq["cell_id"])
    for _, row in daily.iterrows():
        if row["compartment"] == "WATBAL":
            assert row["cell_id"] in watbal_ids
        else:
            assert row["cell_id"] in aq_ids

    assert len(prov) == 2
    assert set(prov["compartment"]) == {"WATBAL", "AQ"}


def test_daily_values_matches_cell_major_reference_expansion(tmp_path: Path):
    """Guard against a repeat/tile transposition in the vectorised
    daily_values build (design.md D11): the written table must equal an
    independent cell-major long-form expansion of the same data."""
    blocks, prov_rows = _make_watbal_fixture(
        n_cells=4, n_days=3, params=("rain", "runoff")
    )
    gpkg_path = str(tmp_path / "basin_test_InternalValues_2000_2000.gpkg")

    save_area_geopackage(gpkg_path, blocks, prov_rows)

    with sqlite3.connect(gpkg_path) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)

    # Independent reference: explicit triple loop, cell-major within each param.
    cells_gdf, values_responses, _ = blocks["WATBAL"]
    cell_ids = list(cells_gdf["cell_id"])
    expected_rows = []
    for param, response in values_responses.items():
        data = np.asarray(response.data, dtype=float)
        dates = list(response.dates)
        for i, cid in enumerate(cell_ids):
            for j, date in enumerate(dates):
                expected_rows.append((cid, date, param, float(data[i, j])))
    expected = pd.DataFrame(
        expected_rows, columns=["cell_id", "date", "param", "value"]
    )

    got = daily[["cell_id", "date", "param", "value"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        got, expected, check_dtype=False, check_like=False
    )


def test_save_area_geopackage_silently_overwrites_existing_file(tmp_path: Path):
    blocks, prov_rows = _make_watbal_fixture()
    gpkg_path = str(tmp_path / "basin_test_InternalValues_2000_2000.gpkg")

    save_area_geopackage(gpkg_path, blocks, prov_rows)

    cells_gdf2 = _make_cells("WATBAL", n_cells=2, base_cell_id=10)
    blocks2 = {"WATBAL": (cells_gdf2, _make_responses(2, 3, ("rain",)), None)}
    prov_rows2 = [_provenance_row("WATBAL", ("rain",), area_name="basin_other")]

    # Second call must not raise and must reflect the new content.
    save_area_geopackage(gpkg_path, blocks2, prov_rows2)

    cells_back = gpd.read_file(gpkg_path, layer="cells_WATBAL")
    assert len(cells_back) == 2

    with sqlite3.connect(gpkg_path) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert len(daily) == 2 * 3 * 1
    assert set(daily["param"].unique()) == {"rain"}
    assert prov.iloc[0]["area_name"] == "basin_other"
