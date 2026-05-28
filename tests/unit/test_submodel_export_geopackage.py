"""Unit tests for the Tier-1 GeoPackage writer ``save_area_geopackage``."""

from __future__ import annotations

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


def _make_fixture(n_cells: int = 3, n_days: int = 5, params=("rain", "runoff")):
    geoms = [box(i, 0, i + 1, 1) for i in range(n_cells)]
    cell_ids = list(range(10, 10 + n_cells))
    cells_gdf = gpd.GeoDataFrame(
        {"cell_id": cell_ids},
        geometry=geoms,
        crs="EPSG:2154",
    )
    dates = np.array([f"2000-01-0{i + 1}" for i in range(n_days)])
    values_responses = {}
    for k, param in enumerate(params):
        data = (np.arange(n_cells * n_days, dtype=float) + k * 100).reshape(
            n_cells, n_days
        )
        values_responses[param] = ValuesResponse(data=data, dates=dates)
    provenance = {
        "source_run": "/tmp/out_caw",
        "syear": 2000,
        "eyear": 2000,
        "polygon_crs": "EPSG:2154",
        "area_name": "basin_test",
        "polygon_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "generated_at": "2026-05-28T12:00:00+00:00",
        "htas_ver": "000.alpha.test",
        "compartment": "WATBAL",
        "params": '["rain", "runoff"]',
    }
    return cells_gdf, values_responses, provenance


def test_save_area_geopackage_writes_three_datasets(tmp_path: Path):
    cells_gdf, values_responses, provenance = _make_fixture()
    gpkg_path = str(tmp_path / "basin_test_WATBAL_2000_2000.gpkg")

    save_area_geopackage(gpkg_path, cells_gdf, values_responses, provenance)

    assert Path(gpkg_path).exists()

    cells_back = gpd.read_file(gpkg_path, layer="cells")
    assert len(cells_back) == 3
    assert set(cells_back.columns) >= {"cell_id", "geometry"}
    assert cells_back.crs is not None
    assert cells_back.crs.to_string() == "EPSG:2154"

    with sqlite3.connect(gpkg_path) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert len(daily) == 3 * 5 * 2
    assert set(daily.columns) == {"cell_id", "date", "param", "value", "unit"}
    assert set(daily["param"].unique()) == {"rain", "runoff"}
    assert (daily["unit"] == "mm/j").all()

    assert len(prov) == 1
    prov_row = prov.iloc[0].to_dict()
    assert prov_row["compartment"] == "WATBAL"
    assert prov_row["area_name"] == "basin_test"
    assert prov_row["polygon_crs"] == "EPSG:2154"
    assert prov_row["htas_ver"] == "000.alpha.test"


def test_save_area_geopackage_silently_overwrites_existing_file(tmp_path: Path):
    cells_gdf, values_responses, provenance = _make_fixture()
    gpkg_path = str(tmp_path / "basin_test_WATBAL_2000_2000.gpkg")

    save_area_geopackage(gpkg_path, cells_gdf, values_responses, provenance)

    cells_gdf2, values_responses2, provenance2 = _make_fixture(
        n_cells=2, n_days=3, params=("rain",)
    )
    provenance2["area_name"] = "basin_other"

    # Second call must not raise and must reflect the new content.
    save_area_geopackage(gpkg_path, cells_gdf2, values_responses2, provenance2)

    cells_back = gpd.read_file(gpkg_path, layer="cells")
    assert len(cells_back) == 2

    with sqlite3.connect(gpkg_path) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert len(daily) == 2 * 3 * 1
    assert set(daily["param"].unique()) == {"rain"}
    assert prov.iloc[0]["area_name"] == "basin_other"
