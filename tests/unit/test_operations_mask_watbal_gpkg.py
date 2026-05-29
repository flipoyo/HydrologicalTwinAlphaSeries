"""Orchestration tests for ``run_mask_watbal`` with/without GeoPackage export."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, box

from HydrologicalTwinAlphaSeries.ht import (
    CellSelectionResponse,
    ValuesResponse,
)
from HydrologicalTwinAlphaSeries.ht.client import operations


def _fake_twin_and_polygon():
    cell_ids = [10, 20, 30]
    mesh_gdf = gpd.GeoDataFrame(
        {"id_cell": cell_ids},
        geometry=[box(i, 0, i + 1, 1) for i in range(3)],
        crs="EPSG:2154",
    )
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04"])

    def fake_mask(kind, **kwargs):
        if kind == "polygon_cells":
            return CellSelectionResponse(
                cell_ids=list(cell_ids),
                meta={"id_compartment": 1, "kind": "polygon_cells"},
            )
        if kind == "area_values":
            param = kwargs["param"]
            data = np.full((len(cell_ids), len(dates)), float(hash(param) % 1000))
            return ValuesResponse(data=data, dates=dates)
        raise ValueError(f"unexpected mask kind: {kind!r}")

    twin = SimpleNamespace(
        mask=fake_mask,
        out_caw_directory="/tmp/fake_out_caw",
    )
    polygon = Polygon([(0, 0), (3, 0), (3, 1), (0, 1)])
    return twin, polygon, mesh_gdf


def _patch_twin_helpers(monkeypatch, mesh_gdf):
    monkeypatch.setattr(operations, "_resolve_compartment_id", lambda twin, name: 1)
    monkeypatch.setattr(operations, "_mesh_gdf_for", lambda twin, cid, id_layer=0: mesh_gdf)
    monkeypatch.setattr(
        operations, "_cell_id_col_name", lambda twin, cid, gdf: "id_cell"
    )


def _collect_files(*dirs: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for d in dirs:
        for p in sorted(d.iterdir()):
            if p.is_file():
                out[p.name] = p.read_bytes()
    return out


def test_run_mask_watbal_writes_gpkg_when_flag_true(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain", "runoff"],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        write_geopackage=True,
    )

    gpkg_path = output_dir / "basin_A_WATBAL_2000_2000.gpkg"
    assert gpkg_path.exists()
    assert str(gpkg_path) in result.artefacts

    csv_paths = [p for p in result.artefacts if p.endswith(".csv")]
    npy_paths = [p for p in result.artefacts if p.endswith(".npy")]
    assert len(csv_paths) == 2
    assert len(npy_paths) == 2

    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)
    assert len(daily) == 3 * 4 * 2
    assert set(daily["param"].unique()) == {"rain", "runoff"}
    assert prov.iloc[0]["compartment"] == "WATBAL"
    assert prov.iloc[0]["area_name"] == "basin_A"
    assert prov.iloc[0]["source_run"] == "/tmp/fake_out_caw"


def test_run_mask_watbal_no_gpkg_when_flag_false_or_omitted(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain", "runoff"],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
    )

    gpkgs = list(output_dir.glob("*.gpkg"))
    assert gpkgs == []
    assert not any(p.endswith(".gpkg") for p in result.artefacts)

    csv_paths = [p for p in result.artefacts if p.endswith(".csv")]
    npy_paths = [p for p in result.artefacts if p.endswith(".npy")]
    assert len(csv_paths) == 2
    assert len(npy_paths) == 2


def test_run_mask_watbal_csv_npy_parity_with_and_without_gpkg(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    run_a = tmp_path / "A"
    run_b = tmp_path / "B"
    (run_a / "OUTPUTS").mkdir(parents=True)
    (run_a / "TEMP").mkdir(parents=True)
    (run_b / "OUTPUTS").mkdir(parents=True)
    (run_b / "TEMP").mkdir(parents=True)

    operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(run_a / "OUTPUTS"),
        temp_dir=str(run_a / "TEMP"),
        area_name="basin_A",
        write_geopackage=False,
    )

    operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(run_b / "OUTPUTS"),
        temp_dir=str(run_b / "TEMP"),
        area_name="basin_A",
        write_geopackage=True,
    )

    files_a = _collect_files(run_a / "OUTPUTS", run_a / "TEMP")
    files_b = {
        name: data
        for name, data in _collect_files(run_b / "OUTPUTS", run_b / "TEMP").items()
        if not name.endswith(".gpkg")
    }
    assert files_a == files_b


# ---------------------------------------------------------------------------
# weighted=True path
# ---------------------------------------------------------------------------


def _weighted_twin_and_polygon():
    """Fake twin where mask(kind='area_values', weighted=True) returns
    populated weights + clipped geometries + cell_ids meta."""
    cell_ids = [10, 20]
    cell_geoms = [box(i, 0, i + 1, 1) for i in range(2)]
    mesh_gdf = gpd.GeoDataFrame(
        {"id_cell": cell_ids}, geometry=cell_geoms, crs="EPSG:2154"
    )
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04"])

    def fake_mask(kind, **kwargs):
        if kind == "polygon_cells":
            return CellSelectionResponse(
                cell_ids=list(cell_ids),
                meta={"id_compartment": 1, "kind": "polygon_cells"},
            )
        if kind == "area_values":
            # Weighted=True invariants from the spec:
            #   - data is volumetric (m³/day)
            #   - weights and clipped_geometries are populated
            #   - meta carries cell_ids
            param = kwargs["param"]
            base = float(hash(param) % 1000)
            weights = np.array([1.0, 0.5])
            # data rows shaped like base * weight (mimicking the dispatcher).
            data = np.array(
                [
                    [base * weights[0]] * len(dates),
                    [base * weights[1]] * len(dates),
                ]
            )
            return ValuesResponse(
                data=data,
                dates=dates,
                meta={
                    "cell_ids": list(cell_ids),
                    "weighted": True,
                    "target_unit": kwargs.get("target_unit"),
                },
                weights=weights,
                clipped_geometries=cell_geoms,
            )
        raise ValueError(f"unexpected mask kind: {kind!r}")

    twin = SimpleNamespace(mask=fake_mask, out_caw_directory="/tmp/fake_out_caw")
    polygon = Polygon([(0, 0), (3, 0), (3, 1), (0, 1)])
    return twin, polygon, mesh_gdf


def test_run_mask_watbal_weighted_writes_polygon_total_csv(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        weighted=True,
    )

    # polygon_total_paths populated when weighted=True.
    assert result.polygon_total_paths is not None
    assert "rain" in result.polygon_total_paths
    rain_total_path = result.polygon_total_paths["rain"]
    assert rain_total_path.endswith(
        "basin_A_rain_polygon_total_2000-2000.csv"
    )
    assert Path(rain_total_path).exists()

    # Polygon-total equals the row-sum of the weighted per-cell CSV.
    total_df = pd.read_csv(rain_total_path, index_col="date")
    cell_csv = next(p for p in result.artefacts if p.endswith("WATBAL_rain_MB_2000-2000.csv"))
    cell_df = pd.read_csv(cell_csv, index_col="date")
    np.testing.assert_allclose(
        total_df["polygon_total"].values, cell_df.sum(axis=1).values
    )


def test_run_mask_watbal_unweighted_has_no_polygon_total_paths(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
    )

    assert result.polygon_total_paths is None
    assert not any("polygon_total" in p for p in result.artefacts)


def test_run_mask_watbal_weighted_gdf_carries_weight_column(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=True,
    )

    assert "weight" in result.gdf.columns
    assert list(result.gdf["cell_id"]) == [10, 20]
    np.testing.assert_allclose(result.gdf["weight"].values, [1.0, 0.5])


def test_run_mask_watbal_unweighted_gdf_has_no_weight_column(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
    )

    assert "weight" not in result.gdf.columns


def test_run_mask_watbal_weighted_gpkg_bundles_weighted_artefacts(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_watbal(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        params=["rain"],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=True,
        write_geopackage=True,
    )

    gpkg_path = output_dir / "basin_A_WATBAL_2000_2000.gpkg"
    assert gpkg_path.exists()
    assert str(gpkg_path) in result.artefacts

    with sqlite3.connect(str(gpkg_path)) as con:
        cells = pd.read_sql_query("SELECT * FROM cells", con)
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        polygon_total = pd.read_sql_query("SELECT * FROM polygon_total_rain", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert "weight" in cells.columns
    # daily_values unit overridden to m3/j on the weighted path.
    assert set(daily["unit"].unique()) == {"m3/j"}
    assert sorted(polygon_total.columns) == ["date", "polygon_total"]
    assert int(prov.iloc[0]["weighted"]) == 1
