"""Orchestration tests for ``run_mask_aq_boundary`` with/without GeoPackage export.

These exercise the L1 ``run_mask_aq_boundary`` orchestration end-to-end against a
fake twin whose ``assemble`` / ``export`` / ``transform`` verbs delegate to the
*real* L2 dispatch (hence the real L3 ``build_compartment_bundle`` +
``save_area_geopackage`` + ``volumetric_rescale``), so both the "reuse the existing
verbs, no backend change" contract and the unit/sign-convention contract are
verified for real.

The boundary response is split **per aquifer layer**: every boundary cell carries
a ``cell_layer_ids`` tag, the GeoPackage emits one ``cells_AQ_layer<id>`` geometry
layer and ``compartment="AQ_layer<id>"`` ``daily_values`` rows per layer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

from HydrologicalTwinAlphaSeries.ht.client import operations_client as operations
from HydrologicalTwinAlphaSeries.ht.developer import dispatch
from HydrologicalTwinAlphaSeries.ht.developer.api_types import BoundaryFluxResponse
from HydrologicalTwinAlphaSeries.services.public.temporal import Temporal


# AQ_FACE_DIRECTIONS drives the per-direction face fetch; mirror its keys here.
from HydrologicalTwinAlphaSeries.config.constants import (
    AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE,
    AQ_BOUNDARY_FLUX_SIGN_CONVENTION,
    AQ_FACE_DIRECTIONS,
    _VOLUMETRIC_UNIT_FACTORS,
)


def _fake_twin(boundary_cells, edge_geometries, dates, *, fluxes_empty=False,
               face_sources=None):
    """A fake twin emulating just the surface ``run_mask_aq_boundary`` touches.

    - ``mask(kind="boundary_aq")`` → a face-orientation response carrying
      ``cell_ids`` + per-cell merged ``edge_geometries`` + ``face_directions`` +
      ``cell_layer_ids`` (all cells on layer 0 here — single-layer aquifer) +
      the optional ``face_sources`` coarse-cell source map (empty by default, so
      the all-INT_cell tests stay byte-identical to pre-change behaviour).
    - ``fetch(kind="simulation_matrix")`` → a per-direction (n_cells, n_days)
      matrix (rows indexed by ``cell_id - 1``).
    - ``mask(kind="boundary_aq_flux")`` → the ragged ``{cell → {dir → series}}``.
    - ``assemble`` / ``export`` / ``transform`` delegate to the REAL L2 dispatch.
    """
    face_sources = face_sources or {}
    n_global = max(boundary_cells) if boundary_cells else 0
    directions = list(AQ_FACE_DIRECTIONS.keys())
    # Each boundary cell exchanges across its first available face direction; a
    # second cell also gets a second direction so the "net = sum over faces" path
    # is exercised on at least one corner cell.
    face_directions = {}
    for i, cid in enumerate(boundary_cells):
        face_directions[cid] = directions[: (2 if i == 0 else 1)]
    # Single-layer aquifer: every boundary cell is tagged with id_layer 0 so the
    # per-layer split groups them into one ``AQ_layer0`` block.
    cell_layer_ids = {cid: 0 for cid in boundary_cells}

    def fake_mask(kind, **kwargs):
        if kind == "boundary_aq":
            return BoundaryFluxResponse(
                cell_ids=list(boundary_cells),
                face_directions={c: list(d) for c, d in face_directions.items()},
                edge_geometries=dict(edge_geometries),
                cell_layer_ids=dict(cell_layer_ids),
                face_sources={c: dict(s) for c, s in face_sources.items()},
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
                        # checkable; raw m³/s (rescale happens in the op).
                        d: np.full(len(dates), float(cid + 10 * j + 1))
                        for j, d in enumerate(dirs)
                    }
            return BoundaryFluxResponse(
                cell_ids=sorted(face_directions.keys()),
                face_directions={c: list(d) for c, d in face_directions.items()},
                cell_layer_ids=dict(cell_layer_ids),
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
        # Real L3 Temporal so the ``m3`` monthly-total path (transform(
        # kind="temporal_aggregate") → twin.temporal.monthly_total_volume) runs
        # against the genuine primitive, matching the assemble/export/transform
        # "delegate to the real dispatch" philosophy of this fixture.
        temporal=Temporal(),
    )
    # assemble/export/transform delegate to the REAL dispatch — the twin handle is
    # unused by the compartment_bundle / geopackage / volumetric_rescale L3 paths,
    # so passing the fake is fine.
    twin.assemble = lambda **kw: dispatch.assemble(
        twin, dispatch.AssembleRequest(**kw)
    )
    twin.export = lambda **kw: dispatch.export(twin, dispatch.ExportRequest(**kw))
    twin.transform = lambda **kw: dispatch.transform(
        twin, dispatch.TransformRequest(data=kw.pop("arr", None), **kw)
    )
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


def _read_csv_cols(csv_path):
    """Read a loose face-flux CSV, skipping the ``#`` sign-convention header."""
    return pd.read_csv(csv_path, comment="#", index_col="date")


# ---------------------------------------------------------------------------
# Default mode unchanged
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

    # entries hold one borders gdf per reached aquifer layer (one layer here).
    all_cell_ids = sorted(
        cid for entry in result.entries for cid in entry.gdf["cell_id"]
    )
    assert all_cell_ids == boundary_cells


# ---------------------------------------------------------------------------
# GeoPackage mode (non-empty)
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

    cells = gpd.read_file(str(gpkg_path), layer="cells_AQ_layer0")
    assert len(cells) == len(boundary_cells)
    assert set(cells["cell_id"]) == set(boundary_cells)

    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    # Every daily_values row is the per-layer AQ block / boundary_flux, default unit.
    assert set(daily["compartment"].unique()) == {"AQ_layer0"}
    assert set(daily["param"].unique()) == {"boundary_flux"}
    assert set(daily["unit"].unique()) == {"m3/j"}
    # One net series per boundary cell × n_days.
    assert len(daily) == len(boundary_cells) * len(dates)
    assert set(daily["cell_id"].unique()) == set(boundary_cells)

    # One-row provenance for the AQ_layer0 block.
    assert len(prov) == 1
    assert prov.iloc[0]["compartment"] == "AQ_layer0"
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
# GeoPackage mode (empty boundary)
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


# ---------------------------------------------------------------------------
# 5.1 Parity: default unit preserves the prior m³/day output
# ---------------------------------------------------------------------------


def test_default_unit_csv_values_and_columns_are_m3_per_day(tmp_path: Path, monkeypatch):
    """Omitting ``unit`` ⇒ m³/day values and ``_m3d`` column suffixes (current behaviour)."""
    twin, polygon, _cells, dates = _setup(monkeypatch)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        area_name="basin_A",
    )

    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    df = _read_csv_cols(csv_path)
    # Every column carries the m³/day suffix; none the monthly one.
    assert all(col.endswith("_m3d") for col in df.columns)
    assert not any(col.endswith("_m3mois") for col in df.columns)
    # cell 2 / first face: raw 3 m³/s → ×86400.
    assert "2_east_m3d" in df.columns
    np.testing.assert_allclose(df["2_east_m3d"].to_numpy(), 3.0 * 86400.0)
    # Same number of data rows as simulated days (no calendar re-binning).
    assert len(df) == len(dates)


def test_default_unit_gpkg_unit_column_is_m3_per_day(tmp_path: Path, monkeypatch):
    twin, polygon, _cells, _dates = _setup(monkeypatch)
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
    assert set(daily["unit"].unique()) == {"m3/j"}


# ---------------------------------------------------------------------------
# 5.2 Monthly rate: rescale by 2_629_800, same time axis, suffix + label follow
# ---------------------------------------------------------------------------


def test_monthly_unit_rescales_values_and_keeps_time_axis(tmp_path: Path, monkeypatch):
    twin, polygon, _cells, dates = _setup(monkeypatch)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        area_name="basin_A",
        unit="m3/mois",
        write_geopackage=True,
    )

    factor = _VOLUMETRIC_UNIT_FACTORS["m3/mois"]
    assert factor == 2_629_800.0

    # CSV: monthly suffix + rescaled values + one row per simulated day.
    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    df = _read_csv_cols(csv_path)
    assert all(col.endswith("_m3mois") for col in df.columns)
    assert "2_east_m3mois" in df.columns
    np.testing.assert_allclose(df["2_east_m3mois"].to_numpy(), 3.0 * factor)
    assert len(df) == len(dates)  # no calendar re-binning

    # GeoPackage: net rescaled by the same factor + unit label stamped.
    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
    assert set(daily["unit"].unique()) == {"m3/mois"}
    corner = daily[daily["cell_id"] == 2]["value"].unique()
    np.testing.assert_allclose(corner, (3.0 + 13.0) * factor)


def test_monthly_total_volume_writes_monthly_values_table(tmp_path: Path, monkeypatch):
    """``unit="m3"`` re-bins daily→calendar-month and persists the totals in a
    ``monthly_values`` table (NOT ``daily_values``), so the table name matches
    what the rows actually hold (one month-total per boundary cell)."""
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
        unit="m3",
        write_geopackage=True,
    )

    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        table_names = set(
            pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type='table'", con
            )["name"]
        )
        monthly = pd.read_sql_query("SELECT * FROM monthly_values", con)

    # The values table is renamed for this mode; the daily name must be absent.
    assert "monthly_values" in table_names
    assert "daily_values" not in table_names

    # All 3 fixture days fall in 2000-01, so the axis re-bins to ONE month row
    # per boundary cell, labelled by its year-month and stamped unit "m3".
    assert len(monthly) == len(boundary_cells)
    assert set(monthly["unit"].unique()) == {"m3"}
    assert set(monthly["date"].astype(str)) == {"2000-01"}

    # Corner cell 2 (two faces, raw net 3+13 m³/s) totals over its 3 simulated
    # days: (3+13) × 86400 × 3.
    corner = monthly[monthly["cell_id"] == 2]["value"].to_numpy()
    np.testing.assert_allclose(corner, (3.0 + 13.0) * 86400.0 * len(dates))


# ---------------------------------------------------------------------------
# 5.3 Agreement: GeoPackage per-cell net == sum of loose-CSV per-direction cols
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["m3/j", "m3/mois"])
def test_gpkg_net_equals_sum_of_csv_directions_per_cell(tmp_path, monkeypatch, unit):
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
        unit=unit,
        write_geopackage=True,
    )

    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    df = _read_csv_cols(csv_path)
    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)

    for cid in boundary_cells:
        csv_net = sum(
            df[col].to_numpy()
            for col in df.columns
            if col.startswith(f"{cid}_")
        )
        gpkg_net = (
            daily[daily["cell_id"] == cid].sort_values("date")["value"].to_numpy()
        )
        np.testing.assert_allclose(gpkg_net, csv_net)


# ---------------------------------------------------------------------------
# 5.4 Sign convention shipped to both surfaces from the shared constant
# ---------------------------------------------------------------------------


def test_sign_convention_in_csv_header_and_gpkg_provenance(tmp_path: Path, monkeypatch):
    twin, polygon, _cells, _dates = _setup(monkeypatch)
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

    # CSV: first line is a commented header carrying the exact constant.
    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    first_line = Path(csv_path).read_text().splitlines()[0]
    assert first_line.startswith("#")
    assert AQ_BOUNDARY_FLUX_SIGN_CONVENTION in first_line

    # GeoPackage provenance: every row carries the same constant.
    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        prov = pd.read_sql_query("SELECT * FROM provenance", con)
    assert "sign_convention" in prov.columns
    assert set(prov["sign_convention"].unique()) == {AQ_BOUNDARY_FLUX_SIGN_CONVENTION}


# ---------------------------------------------------------------------------
# 5.5 Token coverage: every accepted boundary unit resolves a factor + suffix
# ---------------------------------------------------------------------------


def test_every_boundary_unit_resolves_factor_and_csv_suffix():
    from HydrologicalTwinAlphaSeries.config.constants import (
        _VOLUMETRIC_UNIT_CSV_SUFFIX,
        _VOLUMETRIC_UNIT_FACTORS,
    )

    # The AQ boundary path accepts exactly the tokens with a CSV suffix. The RATE
    # tokens are scalar rescales, so each must also resolve a numeric factor
    # (guards spelling drift across the maps). The one AGGREGATING token, ``m3``
    # (calendar-month total volume), is a daily→monthly SUM, not a scalar rescale,
    # so it deliberately carries a suffix but NO factor (design D5); asserting its
    # absence here pins that intentional split so a stray factor is not added.
    for token in _VOLUMETRIC_UNIT_CSV_SUFFIX:
        if token == "m3":
            assert token not in _VOLUMETRIC_UNIT_FACTORS, (
                "m3 aggregates (Σ daily×86400 per month); it must NOT have a "
                "scalar factor in _VOLUMETRIC_UNIT_FACTORS."
            )
        else:
            assert token in _VOLUMETRIC_UNIT_FACTORS, token


def test_unsupported_boundary_unit_raises(tmp_path: Path, monkeypatch):
    twin, polygon, _cells, _dates = _setup(monkeypatch)
    with pytest.raises(ValueError, match="bogus"):
        operations.run_mask_aq_boundary(
            twin,
            polygon=polygon,
            polygon_crs="EPSG:2154",
            syear=2000,
            eyear=2000,
            output_dir=str(tmp_path / "OUTPUTS"),
            area_name="basin_A",
            unit="bogus",
        )


# ---------------------------------------------------------------------------
# 6.5 Coarse-cell provenance: outside_ids column + source note (only when an
# EXT_cell face is present).
# ---------------------------------------------------------------------------


def _setup_coarse(monkeypatch):
    """Same two-cell fixture, but cell 2's east face is EXT_cell (coarse inside),
    sourced from smaller outside neighbour id 5; cell 5 stays all-INT_cell."""
    boundary_cells = [2, 5]
    edge_geometries = {
        2: LineString([(0, 0), (0, 1)]),
        5: LineString([(2, 0), (2, 1)]),
    }
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03"])
    # cell 2 east → EXT_cell (-1) sourced from outside cell 5; its west face and
    # cell 5's faces stay INT_cell (absent → own-face default).
    face_sources = {2: {"east": {"sign": -1, "outside_ids": [5]}}}
    twin = _fake_twin(
        boundary_cells, edge_geometries, dates, face_sources=face_sources
    )
    _patch_resolve(monkeypatch)
    polygon = Polygon([(0, 0), (2, 0), (2, 1), (0, 1)])
    return twin, polygon, boundary_cells, dates


def test_coarse_cell_outside_ids_column_in_gpkg_daily_values(tmp_path, monkeypatch):
    """Task 6.5 — daily_values carries an ``outside_ids`` column: the coarse cell
    (EXT_cell) rows are populated with the outside id(s), fine cells are empty."""
    twin, polygon, _cells, _dates = _setup_coarse(monkeypatch)
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

    assert "outside_ids" in daily.columns
    # Coarse cell 2: every row tagged with its outside neighbour id.
    cell2 = daily[daily["cell_id"] == 2]["outside_ids"].unique()
    assert set(cell2) == {"5"}
    # Fine cell 5: empty provenance.
    cell5 = daily[daily["cell_id"] == 5]["outside_ids"].unique()
    assert set(cell5) == {""}


def test_coarse_cell_source_note_in_gpkg_provenance(tmp_path, monkeypatch):
    """The coarse-cell source note is shipped into the provenance table when an
    EXT_cell face is present (single-constant discipline)."""
    twin, polygon, _cells, _dates = _setup_coarse(monkeypatch)
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
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert "coarse_cell_source" in prov.columns
    assert set(prov["coarse_cell_source"].unique()) == {
        AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE
    }


def test_coarse_cell_source_note_in_loose_csv_header(tmp_path, monkeypatch):
    """The loose face-flux CSV header carries the coarse-cell source note (and the
    per-cell outside_ids mapping) when an EXT_cell face is present."""
    twin, polygon, _cells, _dates = _setup_coarse(monkeypatch)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_aq_boundary(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        area_name="basin_A",
        # default mode → loose CSV
    )

    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    header = "\n".join(
        ln for ln in Path(csv_path).read_text().splitlines() if ln.startswith("#")
    )
    assert AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE in header
    # The per-cell mapping is self-describing for the coarse cell.
    assert "outside_ids: 2 <- 5" in header


def test_no_coarse_source_omits_outside_ids_column_and_note(tmp_path, monkeypatch):
    """Regression (task 6.4/6.5) — with no EXT_cell face the ``outside_ids`` column
    and the coarse-cell note are BOTH absent, keeping the all-INT_cell output
    byte-identical to pre-change (the default ``_setup`` has no face_sources)."""
    twin, polygon, _cells, _dates = _setup(monkeypatch)
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

    gpkg_path = output_dir / "basin_A_AqBoundary_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)
    assert "outside_ids" not in daily.columns
    assert "coarse_cell_source" not in prov.columns

    # Loose CSV header has the sign convention but NOT the coarse-cell note.
    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    header = "\n".join(
        ln for ln in Path(csv_path).read_text().splitlines() if ln.startswith("#")
    )
    assert AQ_BOUNDARY_FLUX_SIGN_CONVENTION in header
    assert AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE not in header
