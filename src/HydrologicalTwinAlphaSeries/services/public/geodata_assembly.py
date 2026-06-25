import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import geopandas as gpd
import numpy as np
import pandas as pd


def assemble_single_layer_geodataframe(
    agg_df: pd.DataFrame,
    cell_ids: np.ndarray,
    cell_geometries: list,
    crs,
    id_col_name: str = "ID_ELEBU",
) -> gpd.GeoDataFrame:
    """Assemble aggregated data + layer geometry into a GeoDataFrame.

    :param agg_df: DataFrame (index=date_labels, columns=cell_ids) from aggregate_for_map
    :param cell_ids: 1D array of cell IDs for the layer
    :param cell_geometries: list of shapely geometries for the layer
    :param crs: pyproj.CRS or EPSG string
    :param id_col_name: column name for the cell ID column
    :return: GeoDataFrame with [id_col, date_columns..., geometry]
    """
    data = agg_df.T.copy()
    data = data.sort_index()
    cols = data.columns.tolist()
    data[id_col_name] = cell_ids.tolist()
    data["geometry"] = cell_geometries
    data = data.sort_values(by=id_col_name)
    data = data[[id_col_name] + cols + ["geometry"]]
    return gpd.GeoDataFrame(data, crs=crs, geometry="geometry")


def assemble_multi_layer_geodataframe(
    agg_df: pd.DataFrame,
    layers: list,
    crs,
    layer_id_offset: int = 0,
) -> gpd.GeoDataFrame:
    """Assemble aggregated data + multi-layer geometry into a GeoDataFrame.

    :param agg_df: DataFrame (index=date_labels, columns=global ``id_abs``)
        from aggregate_for_map — keyed by the unique global cell index so the
        per-layer row lookup below cannot over-match a colliding per-layer id.
    :param layers: list of LayerInfo objects
    :param crs: pyproj.CRS or EPSG string
    :param layer_id_offset: starting layer ID (0 for MB, 1 for H)
    :return: GeoDataFrame with [ID_ABS, ID_LAY, date_columns..., geometry]
    """
    data = agg_df.T

    # Use the global, unique ``id_abs`` (not the per-layer ``cell.id``) both as
    # the ID_ABS column and as the ``.loc`` selector, so a deeper-layer cell
    # whose per-layer id collides with a layer-0 cell is matched uniquely.
    id_abs = []
    layer_ids = []
    geometries = []
    for n_layer, layer_info in enumerate(layers):
        id_abs.extend(layer_info.id_abs.tolist())
        layer_ids.extend([n_layer + layer_id_offset] * layer_info.n_cells)
        geometries.extend(layer_info.cell_geometries)

    result = data.loc[id_abs].copy()
    cols = result.columns.tolist()
    result["ID_ABS"] = id_abs
    result["ID_LAY"] = layer_ids
    result["geometry"] = geometries
    result = gpd.GeoDataFrame(result, crs=crs, geometry="geometry")
    result = result[["ID_ABS", "ID_LAY"] + cols + ["geometry"]]
    result = result.sort_values(by=["ID_LAY", "ID_ABS"])
    return result


def build_compartment_bundle(
    compartment_blocks: Mapping[Any, tuple],
    output_dir: str,
    area_name: str,
    label: str,
    syear: Any,
    eyear: Any,
    polygon: Any,
    polygon_crs: Any,
    weighted: bool,
    source_run: str,
) -> tuple:
    """Shape a per-key block mapping into a GeoPackage-ready bundle.

    Pure data-assembly: composes the output path, builds one provenance row per
    key, and returns the payload a later ``twin.export(kind="geopackage", ...)``
    writes. It performs **no disk I/O** and imports nothing from ``ht/`` — every
    twin-derived value (e.g. ``source_run``) arrives as a parameter, keeping the
    L3 import edge downward only.

    :param compartment_blocks: generic per-key block mapping shaped as
        ``{key: (rows_gdf, {series_key: ValuesResponse}, totals)}``. For the
        Internal Values case, ``key`` is the compartment, ``rows_gdf`` holds the
        masked cell footprints, the inner mapping is keyed by param, and
        ``totals`` is the per-param polygon-total frames (or ``None`` when not
        weighted). The shape is deliberately generic: ``rows_gdf`` may hold
        cell-edge geometries instead of footprints, and ``series_key`` admits a
        flux-direction token (the AQ-boundary reuse routes ``(cell, direction)``
        fluxes through here unchanged, the direction travelling in the
        ``series_key``/``param`` field) — so no GeoPackage schema change is
        needed to serve that future caller.
    :param output_dir: directory the composed ``gpkg_path`` lives in (not created
        here; the writer/export step owns disk side effects).
    :param area_name: masked-area name, the ``{area_name}`` path token.
    :param label: basename token (e.g. ``"InternalValues"``).
    :param syear, eyear: year stamps for the path and provenance rows.
    :param polygon: shapely geometry of the mask; its ``.wkt`` feeds provenance.
    :param polygon_crs: CRS of the mask polygon (provenance only).
    :param weighted: whether the run used area-fraction weighting (provenance).
    :param source_run: the originating run directory (``twin.out_caw_directory``),
        passed in so L3 needs no twin handle.
    :returns: the plain tuple ``(gpkg_path, compartment_blocks, provenance_rows,
        unit_override)``. The caller (L2) wraps this tuple into its own typed
        result — L3 never names that type, keeping the import edge downward only.
    """
    gpkg_path = os.path.join(
        output_dir, f"{area_name}_{label}_{syear}_{eyear}.gpkg"
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_fields = {
        "source_run": source_run or "",
        "syear": syear,
        "eyear": eyear,
        "polygon_crs": polygon_crs or "",
        "area_name": area_name,
        "polygon_wkt": polygon.wkt,
        "generated_at": generated_at,
    }

    provenance_rows = []
    unit_override: dict = {}
    for key, (_rows_gdf, series, _totals) in compartment_blocks.items():
        series_keys = list(series.keys())
        for series_key, response in series.items():
            unit = (response.meta or {}).get("target_unit") if response is not None else None
            if unit is not None:
                unit_override[series_key] = unit
        provenance_rows.append(
            {
                **run_fields,
                "compartment": key,
                "params": json.dumps(series_keys),
                "weighted": bool(weighted),
            }
        )

    return gpkg_path, compartment_blocks, provenance_rows, unit_override
