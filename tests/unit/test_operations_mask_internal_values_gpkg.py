"""Orchestration tests for ``run_mask_internal_values`` with/without GeoPackage export."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Polygon, box

from HydrologicalTwinAlphaSeries.ht import (
    CellSelectionResponse,
    ValuesResponse,
)
from HydrologicalTwinAlphaSeries.ht.client import operations_client as operations
from HydrologicalTwinAlphaSeries.ht.developer import dispatch
from HydrologicalTwinAlphaSeries.ht.developer.api_types import (
    AssembleRequest,
    ExportRequest,
)


def _attach_assemble_export(twin):
    """Give a fake twin the L2 ``assemble`` / ``export`` verbs.

    ``run_mask_internal_values`` routes its shaping/disk writes through these
    verbs. The dispatch functions ignore ``twin`` entirely (they only read the
    request and call pure L3 writers), so the fakes delegate to them via the
    same kwargs→request coercion the real facade uses — exercising the real L3
    shaping/writing without a full twin.
    """
    twin.assemble = lambda kind, **kwargs: dispatch.assemble(
        twin, AssembleRequest(kind=kind, **kwargs)
    )
    twin.export = lambda kind, **kwargs: dispatch.export(
        twin, ExportRequest(kind=kind, **kwargs)
    )
    return twin


def _watbal_entry(result):
    """Return the single WATBAL per-compartment entry from a result."""
    return next(e for e in result.entries if e.compartment == "WATBAL")


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
            # meta["cell_ids"] carries the (global, for AQ outcropping) ids the
            # unweighted cells-gdf join now reads back.
            return ValuesResponse(
                data=data, dates=dates, meta={"cell_ids": list(cell_ids)}
            )
        raise ValueError(f"unexpected mask kind: {kind!r}")

    # The AQ outcropping resolver returns a cross-layer gdf keyed on id_abs;
    # here it mirrors the single mesh (cell_ids double as global id_abs).
    outcropping_gdf = mesh_gdf.rename(columns={"id_cell": "id_abs"})

    twin = _attach_assemble_export(
        SimpleNamespace(
            mask=fake_mask,
            out_caw_directory="/tmp/fake_out_caw",
            _build_outcropping_mesh_gdf=lambda *_a, **_k: outcropping_gdf,
        )
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


def test_run_mask_internal_values_writes_gpkg_when_flag_true(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j"), ("WATBAL", "MB", "runoff", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        write_geopackage=True,
        weighted=False,
    )

    gpkg_path = output_dir / "basin_A_InternalValues_2000_2000.gpkg"
    assert gpkg_path.exists()

    # Exclusive mode (design.md D10): the .gpkg is the SOLE artefact —
    # no per-param CSV / .npy in the result or on disk.
    assert result.artefacts == [str(gpkg_path)]
    assert not any(p.endswith(".csv") for p in result.artefacts)
    assert not any(p.endswith(".npy") for p in result.artefacts)
    assert list(output_dir.glob("*.csv")) == []
    assert list(temp_dir.glob("*.npy")) == []

    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)
    assert len(daily) == 3 * 4 * 2
    assert set(daily["param"].unique()) == {"rain", "runoff"}
    assert set(daily["compartment"].unique()) == {"WATBAL"}
    assert prov.iloc[0]["compartment"] == "WATBAL"
    assert prov.iloc[0]["area_name"] == "basin_A"
    assert prov.iloc[0]["source_run"] == "/tmp/fake_out_caw"


def test_run_mask_internal_values_no_gpkg_when_flag_false_or_omitted(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j"), ("WATBAL", "MB", "runoff", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        weighted=False,
    )

    gpkgs = list(output_dir.glob("*.gpkg"))
    assert gpkgs == []
    assert not any(p.endswith(".gpkg") for p in result.artefacts)

    csv_paths = [p for p in result.artefacts if p.endswith(".csv")]
    npy_paths = [p for p in result.artefacts if p.endswith(".npy")]
    assert len(csv_paths) == 2
    assert len(npy_paths) == 2


def test_run_mask_internal_values_modes_are_mutually_exclusive(tmp_path: Path, monkeypatch):
    """Exclusive mode (design.md D10): default-mode writes CSV+.npy and no
    .gpkg; GeoPackage-mode writes only the .gpkg and no CSV/.npy. No run
    produces both."""
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    run_a = tmp_path / "A"   # default mode
    run_b = tmp_path / "B"   # GeoPackage mode
    for run in (run_a, run_b):
        (run / "OUTPUTS").mkdir(parents=True)
        (run / "TEMP").mkdir(parents=True)

    operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(run_a / "OUTPUTS"),
        temp_dir=str(run_a / "TEMP"),
        area_name="basin_A",
        write_geopackage=False,
        weighted=False,
    )

    operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(run_b / "OUTPUTS"),
        temp_dir=str(run_b / "TEMP"),
        area_name="basin_A",
        write_geopackage=True,
        weighted=False,
    )

    files_a = _collect_files(run_a / "OUTPUTS", run_a / "TEMP")
    files_b = _collect_files(run_b / "OUTPUTS", run_b / "TEMP")

    # Default mode: CSV + .npy, no .gpkg.
    assert any(n.endswith(".csv") for n in files_a)
    assert any(n.endswith(".npy") for n in files_a)
    assert not any(n.endswith(".gpkg") for n in files_a)

    # GeoPackage mode: exactly the .gpkg, nothing else.
    assert [n for n in files_b if n.endswith(".gpkg")] == [
        "basin_A_InternalValues_2000_2000.gpkg"
    ]
    assert not any(n.endswith(".csv") for n in files_b)
    assert not any(n.endswith(".npy") for n in files_b)


def test_run_mask_internal_values_gpkg_bundles_watbal_and_aq(tmp_path: Path, monkeypatch):
    """A mixed WATBAL + AQ GeoPackage request now produces one multi-layer
    Internal Values bundle: a cells_<compartment> layer per mesh, a
    compartment-keyed daily_values, and one provenance row per compartment."""
    twin, polygon, mesh_gdf = _fake_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j"), ("AQ", "MB", "recharge", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        write_geopackage=True,
        weighted=False,
    )

    gpkg_path = output_dir / "basin_A_InternalValues_2000_2000.gpkg"
    assert gpkg_path.exists()
    assert result.artefacts == [str(gpkg_path)]

    cells_watbal = gpd.read_file(str(gpkg_path), layer="cells_WATBAL")
    cells_aq = gpd.read_file(str(gpkg_path), layer="cells_AQ")
    assert len(cells_watbal) == 3
    assert len(cells_aq) == 3

    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert set(daily["compartment"].unique()) == {"WATBAL", "AQ"}
    # Every (compartment, cell_id) resolves to a geometry in the matching mesh.
    watbal_ids = set(cells_watbal["cell_id"])
    aq_ids = set(cells_aq["cell_id"])
    for _, row in daily.iterrows():
        target = watbal_ids if row["compartment"] == "WATBAL" else aq_ids
        assert row["cell_id"] in target

    assert len(prov) == 2
    assert set(prov["compartment"]) == {"WATBAL", "AQ"}


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

    twin = _attach_assemble_export(
        SimpleNamespace(mask=fake_mask, out_caw_directory="/tmp/fake_out_caw")
    )
    polygon = Polygon([(0, 0), (3, 0), (3, 1), (0, 1)])
    return twin, polygon, mesh_gdf


def test_run_mask_internal_values_weighted_writes_polygon_total_csv(tmp_path: Path, monkeypatch):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        weighted=True,
    )

    # polygon_total_paths populated when weighted=True, keyed per (comp, param).
    assert result.polygon_total_paths is not None
    assert ("WATBAL", "rain") in result.polygon_total_paths
    rain_total_path = result.polygon_total_paths[("WATBAL", "rain")]
    # Default unit is m3/j, so the CSV filename carries the _m3j token.
    assert rain_total_path.endswith(
        "basin_A_WATBAL_rain_polygon_total_2000-2000_m3j.csv"
    )
    assert Path(rain_total_path).exists()

    # Polygon-total equals the row-sum of the weighted per-cell CSV.
    total_df = pd.read_csv(rain_total_path, index_col="date")
    cell_csv = next(p for p in result.artefacts if p.endswith("WATBAL_rain_MB_2000-2000_m3j.csv"))
    cell_df = pd.read_csv(cell_csv, index_col="date")
    np.testing.assert_allclose(
        total_df["polygon_total"].values, cell_df.sum(axis=1).values
    )


def test_run_mask_internal_values_unweighted_has_no_polygon_total_paths(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        weighted=False,
    )

    assert result.polygon_total_paths is None
    assert not any("polygon_total" in p for p in result.artefacts)


def test_run_mask_internal_values_weighted_gdf_carries_weight_column(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=True,
    )

    gdf = _watbal_entry(result).gdf
    assert "weight" in gdf.columns
    assert list(gdf["cell_id"]) == [10, 20]
    np.testing.assert_allclose(gdf["weight"].values, [1.0, 0.5])


def test_run_mask_internal_values_unweighted_gdf_has_no_weight_column(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=False,
    )

    assert "weight" not in _watbal_entry(result).gdf.columns


def test_run_mask_internal_values_weighted_gpkg_bundles_weighted_artefacts(
    tmp_path: Path, monkeypatch
):
    twin, polygon, mesh_gdf = _weighted_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/j")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=True,
        write_geopackage=True,
    )

    gpkg_path = output_dir / "basin_A_InternalValues_2000_2000.gpkg"
    assert gpkg_path.exists()
    # Exclusive mode: the .gpkg is the sole artefact even on the weighted path —
    # the polygon totals live inside it (polygon_total_WATBAL_rain), not a CSV.
    assert result.artefacts == [str(gpkg_path)]
    assert result.polygon_total_paths in (None, {})
    assert list(output_dir.glob("*.csv")) == []

    with sqlite3.connect(str(gpkg_path)) as con:
        cells = pd.read_sql_query("SELECT * FROM cells_WATBAL", con)
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
        polygon_total = pd.read_sql_query(
            "SELECT * FROM polygon_total_WATBAL_rain", con
        )
        prov = pd.read_sql_query("SELECT * FROM provenance", con)

    assert "weight" in cells.columns
    # daily_values unit overridden to m3/j on the weighted path.
    assert set(daily["unit"].unique()) == {"m3/j"}
    assert sorted(polygon_total.columns) == ["date", "polygon_total"]
    assert int(prov.iloc[0]["weighted"]) == 1


# ---------------------------------------------------------------------------
# HYD internal values — reaches resolution + per-spec length / volumetric units
# ---------------------------------------------------------------------------


def _hyd_twin_and_polygon():
    """Fake twin emulating the HYD reaches path: area_values returns a response
    already carrying the dispatcher's reaches output (row-aligned cell_ids meta,
    weights, and boundary-clipped reach geometries)."""
    reach_ids = [101, 202]
    # Two reaches; the polygon clips them to these segments.
    clipped = [LineString([(0, 0), (1, 0)]), LineString([(1, 0), (1.5, 0)])]
    mesh_gdf = gpd.GeoDataFrame(
        {"reach_id": reach_ids},
        geometry=[LineString([(0, 0), (2, 0)]), LineString([(1, 0), (3, 0)])],
        crs="EPSG:2154",
    )
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04"])

    def fake_mask(kind, **kwargs):
        if kind == "area_values":
            param = kwargs["param"]
            target_unit = kwargs.get("target_unit")
            # Mirror the dispatch volumetric guard so a length spec wrongly
            # routed with weighted=True would blow up here, exactly as the
            # real backend does.
            if kwargs.get("weighted") and target_unit not in ("m3/s", "m3/j"):
                raise ValueError(
                    "mask(kind='area_values', weighted=True) requires a "
                    f"volumetric target_unit; got target_unit={target_unit!r}."
                )
            data = np.full((len(reach_ids), len(dates)), float(hash(param) % 1000))
            return ValuesResponse(
                data=data,
                dates=dates,
                meta={
                    "cell_ids": list(reach_ids),
                    "target_unit": target_unit,
                    "resolution": kwargs.get("resolution"),
                },
                weights=np.array([0.5, 0.25]),
                clipped_geometries=list(clipped),
            )
        raise ValueError(f"unexpected mask kind: {kind!r}")

    twin = _attach_assemble_export(
        SimpleNamespace(mask=fake_mask, out_caw_directory="/tmp/fake_out_caw")
    )
    polygon = Polygon([(0, 0), (3, 0), (3, 1), (0, 1)])
    return twin, polygon, mesh_gdf


def test_run_mask_internal_values_hyd_reaches_per_spec_units(tmp_path: Path, monkeypatch):
    """A HYD spec list mixing a volumetric Flow (m3/s) and a length Water Height
    (m) returns a HYD entry whose cells gdf is built from the reach geometries,
    and stamps each spec's own unit into the GeoPackage daily_values."""
    twin, polygon, mesh_gdf = _hyd_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[
            ("HYD", "Q", "discharge", "m3/s"),
            ("HYD", "H", "water_level", "m"),
        ],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        write_geopackage=True,
        weighted=False,
    )

    gpkg_path = output_dir / "basin_A_InternalValues_2000_2000.gpkg"
    assert gpkg_path.exists()

    hyd_entry = next(e for e in result.entries if e.compartment == "HYD")
    # The cells gdf comes from the clipped reach geometries, not a centroid
    # re-selection: two reaches, line geometries, reach ids preserved.
    assert list(hyd_entry.gdf["cell_id"]) == [101, 202]
    assert hyd_entry.gdf.geometry.geom_type.unique().tolist() == ["LineString"]

    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
    # Each spec keeps its own unit token in daily_values.
    units_by_param = daily.groupby("param")["unit"].unique()
    assert units_by_param["discharge"].tolist() == ["m3/s"]
    assert units_by_param["water_level"].tolist() == ["m"]


def test_run_mask_internal_values_weighted_true_does_not_push_length_spec_into_guard(
    tmp_path: Path, monkeypatch
):
    """Regression: a dialog-wide weighted=True must NOT reach a length spec —
    Water Height (m) can never be area-weighted. The per-spec weighting is
    forced off for length units, so the volumetric guard never fires even when
    the same call also weights a volumetric discharge spec."""
    twin, polygon, mesh_gdf = _hyd_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    # weighted=True at the call level; the length spec must still go through.
    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[
            ("HYD", "Q", "discharge", "m3/s"),     # volumetric → may be weighted
            ("HYD", "H", "water_level", "m"),      # length → must be unweighted
        ],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        write_geopackage=True,
        weighted=True,
    )

    # No ValueError raised → the length spec was forced unweighted. Both specs
    # still land in the HYD entry.
    hyd_entry = next(e for e in result.entries if e.compartment == "HYD")
    assert list(hyd_entry.gdf["cell_id"]) == [101, 202]


# ---------------------------------------------------------------------------
# HYD ID_ABS → ID_GIS relabel (change: mask-hyd-id-gis-relabel)
# ---------------------------------------------------------------------------


def _hyd_relabel_twin_and_polygon(with_gis_ids: bool):
    """Fake twin emulating the HYD reaches path with the relabel wired in.

    ``area_values`` returns the same shape the real dispatch now returns for a
    HYD reaches mask: ``meta["cell_ids"]`` are the internal ABS ids (used to
    slice the matrix), and ``meta["cell_gis_ids"]`` are the row-aligned
    user-facing GIS ids. When ``with_gis_ids`` is False the response omits
    ``cell_gis_ids`` entirely — the missing-corresp fallback, where the ids in
    play are already GIS ids and no relabel key is threaded.
    """
    abs_ids = [5, 6]              # internal ABS ids (matrix row labels)
    gis_ids = [101, 202]         # user's reach ids (GIS)
    clipped = [LineString([(0, 0), (1, 0)]), LineString([(1, 0), (1.5, 0)])]
    mesh_gdf = gpd.GeoDataFrame(
        {"reach_id": abs_ids},
        geometry=[LineString([(0, 0), (2, 0)]), LineString([(1, 0), (3, 0)])],
        crs="EPSG:2154",
    )
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04"])

    def fake_mask(kind, **kwargs):
        if kind == "area_values":
            param = kwargs["param"]
            data = np.full((len(abs_ids), len(dates)), float(hash(param) % 1000))
            meta = {
                "cell_ids": list(abs_ids),
                "target_unit": kwargs.get("target_unit"),
                "resolution": kwargs.get("resolution"),
            }
            if with_gis_ids:
                meta["cell_gis_ids"] = list(gis_ids)
            return ValuesResponse(
                data=data,
                dates=dates,
                meta=meta,
                clipped_geometries=list(clipped),
            )
        raise ValueError(f"unexpected mask kind: {kind!r}")

    twin = _attach_assemble_export(
        SimpleNamespace(mask=fake_mask, out_caw_directory="/tmp/fake_out_caw")
    )
    polygon = Polygon([(0, 0), (3, 0), (3, 1), (0, 1)])
    return twin, polygon, mesh_gdf, abs_ids, gis_ids


def test_hyd_mask_emits_gis_id_as_cell_id(tmp_path: Path, monkeypatch):
    """The registered HYD cells gdf's cell_id is the user's GIS reach id, NOT
    the internal ABS id (spec: HYD internal-values cell_id shows the GIS id)."""
    twin, polygon, mesh_gdf, abs_ids, gis_ids = _hyd_relabel_twin_and_polygon(
        with_gis_ids=True
    )
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("HYD", "Q", "discharge", "m3/s")],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=False,
    )

    hyd_entry = next(e for e in result.entries if e.compartment == "HYD")
    # cell_id is the GIS id (101, 202), not the ABS id (5, 6).
    assert list(hyd_entry.gdf["cell_id"]) == gis_ids
    assert list(hyd_entry.gdf["cell_id"]) != abs_ids


def test_hyd_gpkg_geometry_and_daily_values_join_survives_relabel(
    tmp_path: Path, monkeypatch
):
    """The single most important correctness check (design D5): inside the
    written .gpkg, the cells_HYD geometry layer's cell_id and the
    daily_values rows tagged compartment=='HYD' both carry the GIS id, and the
    join on (compartment, cell_id) is non-empty and row-complete."""
    twin, polygon, mesh_gdf, _abs_ids, gis_ids = _hyd_relabel_twin_and_polygon(
        with_gis_ids=True
    )
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"

    operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("HYD", "Q", "discharge", "m3/s")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        write_geopackage=True,
        weighted=False,
    )

    gpkg_path = output_dir / "basin_A_InternalValues_2000_2000.gpkg"
    cells_hyd = gpd.read_file(str(gpkg_path), layer="cells_HYD")
    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)

    hyd_daily = daily[daily["compartment"] == "HYD"]

    # Both surfaces carry the GIS id.
    assert set(cells_hyd["cell_id"]) == set(gis_ids)
    assert set(hyd_daily["cell_id"]) == set(gis_ids)

    # The (compartment, cell_id) join is non-empty and row-complete: every HYD
    # daily_values cell_id resolves to a geometry, and no cell is orphaned.
    geom_ids = set(cells_hyd["cell_id"])
    assert set(hyd_daily["cell_id"]) <= geom_ids
    assert set(hyd_daily["cell_id"]) == geom_ids  # no reach dropped by the relabel
    assert len(hyd_daily) == len(gis_ids) * 4    # 2 reaches × 4 days


def test_hyd_mask_relabel_is_noop_without_gis_ids_in_meta(
    tmp_path: Path, monkeypatch
):
    """Fallback (missing corresp / no cell_gis_ids in meta): _build_cells_gdf
    falls back to cell_ids, so the emitted cell_id equals the ABS id — which in
    the real fallback IS the GIS id (id_gis == id_abs). Output is unchanged
    from the pre-relabel behaviour."""
    twin, polygon, mesh_gdf, abs_ids, _gis_ids = _hyd_relabel_twin_and_polygon(
        with_gis_ids=False
    )
    _patch_twin_helpers(monkeypatch, mesh_gdf)

    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("HYD", "Q", "discharge", "m3/s")],
        syear=2000,
        eyear=2000,
        output_dir=str(tmp_path / "OUTPUTS"),
        temp_dir=str(tmp_path / "TEMP"),
        area_name="basin_A",
        weighted=False,
    )

    hyd_entry = next(e for e in result.entries if e.compartment == "HYD")
    # No cell_gis_ids → falls back to cell_ids (the raw ids, == GIS in fallback).
    assert list(hyd_entry.gdf["cell_id"]) == abs_ids


# ---------------------------------------------------------------------------
# unit selector (caller-selectable m3/s | m3/j)
# ---------------------------------------------------------------------------


def _unit_capturing_twin_and_polygon():
    """Fake twin whose area_values response echoes the ``target_unit`` it was
    called with, so a test can assert the threaded ``unit`` reaches the
    conversion call. The native ``m3/s`` path returns the raw array; ``m3/j``
    mimics the backend's 86400 multiply so the two units differ on disk."""
    cell_ids = [10, 20, 30]
    mesh_gdf = gpd.GeoDataFrame(
        {"id_cell": cell_ids},
        geometry=[box(i, 0, i + 1, 1) for i in range(3)],
        crs="EPSG:2154",
    )
    dates = np.array(["2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04"])
    raw = 2.5  # native m3/s per-cell value

    def fake_mask(kind, **kwargs):
        if kind == "polygon_cells":
            return CellSelectionResponse(
                cell_ids=list(cell_ids),
                meta={"id_compartment": 1, "kind": "polygon_cells"},
            )
        if kind == "area_values":
            target_unit = kwargs.get("target_unit")
            # m3/s is native (no conversion); m3/j scales by 86400.
            value = raw if target_unit == "m3/s" else raw * 86400.0
            data = np.full((len(cell_ids), len(dates)), value)
            return ValuesResponse(
                data=data, dates=dates, meta={"target_unit": target_unit}
            )
        raise ValueError(f"unexpected mask kind: {kind!r}")

    twin = _attach_assemble_export(
        SimpleNamespace(mask=fake_mask, out_caw_directory="/tmp/fake_out_caw")
    )
    polygon = Polygon([(0, 0), (3, 0), (3, 1), (0, 1)])
    return twin, polygon, mesh_gdf, raw


def test_unit_m3s_skips_86400_and_stamps_gpkg_unit(tmp_path: Path, monkeypatch):
    """unit='m3/s' threads through to the conversion (raw native values, no
    86400 multiply) and the GeoPackage daily_values.unit matches the choice."""
    twin, polygon, mesh_gdf, raw = _unit_capturing_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    # Default-mode CSV check: values equal the raw m3/s array.
    result = operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/s")],
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        weighted=False,
    )
    csv_path = next(p for p in result.artefacts if p.endswith(".csv"))
    df = pd.read_csv(csv_path, index_col="date")
    np.testing.assert_allclose(df.values, raw)

    # GeoPackage-mode check: daily_values.unit stamped with the chosen unit.
    gpkg_dir = tmp_path / "GPKG"
    gpkg_dir.mkdir()
    operations.run_mask_internal_values(
        twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        specs=[("WATBAL", "MB", "rain", "m3/s")],
        syear=2000,
        eyear=2000,
        output_dir=str(gpkg_dir),
        temp_dir=str(tmp_path / "GTEMP"),
        area_name="basin_A",
        weighted=False,
        write_geopackage=True,
    )
    gpkg_path = gpkg_dir / "basin_A_InternalValues_2000_2000.gpkg"
    with sqlite3.connect(str(gpkg_path)) as con:
        daily = pd.read_sql_query("SELECT * FROM daily_values", con)
    assert set(daily["unit"].unique()) == {"m3/s"}


def test_csv_filename_carries_unit_token_and_runs_do_not_collide(
    tmp_path: Path, monkeypatch
):
    """An m3/s run and an m3/j run of the same spec write two non-colliding
    CSVs, each carrying its unit token in the filename."""
    twin, polygon, mesh_gdf, _raw = _unit_capturing_twin_and_polygon()
    _patch_twin_helpers(monkeypatch, mesh_gdf)
    output_dir = tmp_path / "OUTPUTS"
    temp_dir = tmp_path / "TEMP"

    common = dict(
        twin=twin,
        polygon=polygon,
        polygon_crs="EPSG:2154",
        syear=2000,
        eyear=2000,
        output_dir=str(output_dir),
        temp_dir=str(temp_dir),
        area_name="basin_A",
        weighted=False,
    )
    # The output unit now rides on the spec tuple's 4th element.
    res_s = operations.run_mask_internal_values(
        **common, specs=[("WATBAL", "MB", "rain", "m3/s")]
    )
    res_j = operations.run_mask_internal_values(
        **common, specs=[("WATBAL", "MB", "rain", "m3/j")]
    )

    csv_s = next(p for p in res_s.artefacts if p.endswith(".csv"))
    csv_j = next(p for p in res_j.artefacts if p.endswith(".csv"))

    assert csv_s.endswith("WATBAL_rain_MB_2000-2000_m3s.csv")
    assert csv_j.endswith("WATBAL_rain_MB_2000-2000_m3j.csv")
    # Distinct paths → no silent overwrite; both survive on disk.
    assert csv_s != csv_j
    assert Path(csv_s).exists()
    assert Path(csv_j).exists()
    assert len(list(output_dir.glob("WATBAL_rain_MB_2000-2000_*.csv"))) == 2
