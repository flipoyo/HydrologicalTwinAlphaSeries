"""Orchestration tests for ``run_mask_aq_boundary`` with/without GeoPackage export.

These exercise the L1 ``run_mask_aq_boundary`` orchestration end-to-end against a
fake twin whose ``assemble`` / ``export`` verbs delegate to the *real* L2 dispatch
(hence the real L3 ``build_compartment_bundle`` + ``save_area_geopackage``), so the
"reuse the existing verbs, no backend change" contract is verified for real.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Polygon

from HydrologicalTwinAlphaSeries.ht.client import operations_client as operations
from HydrologicalTwinAlphaSeries.ht.developer import dispatch
from HydrologicalTwinAlphaSeries.ht.developer.api_types import BoundaryFluxResponse


# AQ_FACE_DIRECTIONS drives the per-direction face fetch; mirror its keys here.
from HydrologicalTwinAlphaSeries.config.constants import AQ_FACE_DIRECTIONS


def _fake_twin(boundary_cells, edge_geometries, dates, *, fluxes_empty=False):
    """A fake twin emulating just the surface ``run_mask_aq_boundary`` touches.

    - ``mask(kind="boundary_aq")`` → a face-orientation response carrying
      ``cell_ids`` + per-cell merged ``edge_geometries`` + ``face_directions``.
    - ``fetch(kind="simulation_matrix")`` → a per-direction (n_cells, n_days)
      matrix (rows indexed by ``cell_id - 1``).
    - ``mask(kind="boundary_aq_flux")`` → the ragged ``{cell → {dir → series}}``.
    - ``assemble`` / ``export`` delegate to the REAL L2 dispatch (real L3).
    """
    n_global = max(boundary_cells) if boundary_cells else 0
    directions = list(AQ_FACE_DIRECTIONS.keys())
    # Each boundary cell exchanges across its first available face direction; a
    # second cell also gets a second direction so the "net = sum over faces" path
    # is exercised on at least one corner cell.
    face_directions = {}
    for i, cid in enumerate(boundary_cells):
        face_directions[cid] = directions[: (2 if i == 0 else 1)]

    def fake_mask(kind, **kwargs):
        if kind == "boundary_aq":
            return BoundaryFluxResponse(
                cell_ids=list(boundary_cells),
                face_directions={c: list(d) for c, d in face_directions.items()},
                edge_geometries=dict(edge_geometries),
                fluxes={},
                dates=None,
                meta={"kind": "boundary_aq"},
            )
        if kind == "boundary_aq_flux":
            if fluxes_empty:
                fluxes = {}
            else:
                fluxes = {}
                for k, (cid, dirs) in enumerate(face_directions.items()):
                    fluxes[cid] = {
                        # distinct constant per (cell, dir) so the net sum is
                        # checkable; raw m³/s (×86400 happens in the op).
                        d: np.full(len(dates), float(cid + 10 * j + 1))
                        for j, d in enumerate(dirs)
                    }
            return BoundaryFluxResponse(
                cell_ids=sorted(face_directions.keys()),
                face_directions={c: list(d) for c, d in face_directions.items()},
                fluxes=fluxes,
                dates=dates,
                meta={"kind": "boundary_aq_flux"},
            )
        raise ValueError(f"unexpected mask kind: {kind!r}")

    def fake_fetch(kind, **kwargs):
        if kind == "simulation_matrix":
            data = np.zeros((n_global, len(dates)))
            return SimpleNamespace(data=data, dates=dates)
        raise ValueError(f"unexpected fetch kind: {kind!r}")

    twin = SimpleNamespace(
        out_caw_directory="/tmp/fake_out_caw",
        mask=fake_mask,
        fetch=fake_fetch,
        get_all_layers=lambda aq_id: [SimpleNamespace(id_layer=0)],
    )
    # assemble/export delegate to the REAL dispatch — the twin handle is unused
    # by the compartment_bundle / geopackage L3 paths, so passing the fake is fine.
    twin.assemble = lambda **kw: dispatch.assemble(
        twin, dispatch.AssembleRequest(**kw)
    )
    twin.export = lambda **kw: dispatch.export(twin, dispatch.ExportRequest(**kw))
    return twin


def _patch_resolve(monkeypatch):
    monkeypatch.setattr(operations, "_resolve_compartment_id", lambda twin, name: 1)


def _setup(monkeypatch, *, fluxes_empty=False):
    boundary_cells = [2, 5]
    edge_geometries = {
        2: LineString([(0, 0), (0, 1)]),
        5: LineString([(2, 0), (2, 1)]),
    }
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03"])
    twin = _fake_twin(boundary_cells, edge_geometries, dates, fluxes_empty=fluxes_empty)
    _patch_resolve(monkeypatch)
    polygon = Polygon([(0, 0), (2, 0), (2, 1), (0, 1)])
    return twin, polygon, boundary_cells, dates


# ---------------------------------------------------------------------------
# 5.1 Default mode unchanged
# ---------------------------------------------------------------------------


def test_default_mode_writes_csv_and_no_gpkg(tmp_path: Path, monkeypatch):
    twin, polygon, boundary_cells, _dates = _setup(monkeypatch)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        area_name="basin_A",
        # write_geopackage omitted → default mode
    )

    # The loose face-flux CSV is written; no .gpkg anywhere.
    csv_paths = [p for p in result.artefacts if p.endswith(".csv")]
    assert len(csv_paths) == 1
    assert Path(csv_paths[0]).exists()
    assert not any(p.endswith(".gpkg") for p in result.artefacts)
    assert list(output_dir.glob("*.gpkg")) == []

    # cells_gdf is the boundary-edges layer (one row per boundary cell).
    assert list(result.cells_gdf["cell_id"]) == boundary_cells


# ---------------------------------------------------------------------------
# 5.2 GeoPackage mode (non-empty)
# ---------------------------------------------------------------------------


def test_geopackage_mode_writes_bundle(tmp_path: Path, monkeypatch):
    twin, polygon, boundary_cells, dates = _setup(monkeypatch)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        write_geopackage=True,
    )

    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    assert gpkg_path.exists()
    assert str(gpkg_path) in result.artefacts
    # Loose CSV still written (additive, not exclusive).
    assert any(p.endswith(".csv") for p in result.artefacts)

    cells = gpd.read_file(str(gpkg_path), layer="cells_AQ")
    assert len(cells) == len(boundary_cells)
    assert set(cells["cell_id"]) == set(boundary_cells)

    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    # Every daily_values row is AQ / boundary_flux with a populated unit.
    assert set(daily["compartment"].unique()) == {"AQ"}
    assert set(daily["param"].unique()) == {"boundary_flux"}
    assert set(daily["unit"].unique()) == {"m3/d"}
    # One net series per boundary cell × n_days.
    assert len(daily) == len(boundary_cells) * len(dates)
    assert set(daily["cell_id"].unique()) == set(boundary_cells)

    # One-row provenance for AQ.
    assert len(prov) == 1
    assert prov.iloc[0]["compartment"] == "AQ"
    assert prov.iloc[0]["area_name"] == "basin_A"


def test_geopackage_net_flux_is_sum_over_faces(tmp_path: Path, monkeypatch):
    """The corner cell (2 faces) row is the m³/d sum of both face series."""
    twin, polygon, boundary_cells, dates = _setup(monkeypatch)
    output_dir = tmp_path / "OUTPUTS"

    operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        area_name="basin_A",
        write_geopackage=True,
    )

    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)

    # cell 2 is the corner cell: faces carry raw (2+1)=3 and (2+10+1)=13 m³/s
    # → net = 16 m³/s → ×86400 = 1382400 m³/d.
    corner = daily[daily["cell_id"] == 2]["value"].unique()
    np.testing.assert_allclose(corner, (3.0 + 13.0) * 86400.0)


# ---------------------------------------------------------------------------
# 5.3 GeoPackage mode (empty boundary)
# ---------------------------------------------------------------------------


def test_geopackage_mode_empty_boundary_writes_no_gpkg(tmp_path: Path, monkeypatch):
    twin, polygon, _cells, _dates = _setup(monkeypatch, fluxes_empty=True)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        area_name="basin_A",
        write_geopackage=True,
    )

    assert list(output_dir.glob("*.gpkg")) == []
    assert not any(p.endswith(".gpkg") for p in result.artefacts)
    # No fluxes → no CSV either (mirrors the existing empty guard).
    assert not any(p.endswith(".csv") for p in result.artefacts)
