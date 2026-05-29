"""Privileged artefact writers for area-scoped submodel-grade data.

This module lives in ``services/private/`` because it persists the raw
per-cell simulation array for a user-selected area — a Tier-1 leak surface
under the project security model. See ``services/SECURITY.md`` for the
placement rule and the threat tiers.

Two writers live here today:

- :func:`save_area_values_npy` — the raw ``.npy`` write of the per-cell
  value array for one param of a masked area; the precursor of the
  area-scoped submodel numpy.
- :func:`save_area_geopackage` — bundles the masked cells geometry, the
  long-form per-(cell, date, param) values table, and a one-row provenance
  table into a single transportable GeoPackage. Same Tier-1 leak surface
  (user-supplied geometry + raw per-cell numeric arrays on disk), hosted
  next to ``save_area_values_npy`` so every privileged writer is reachable
  from one auditable import path.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping, Optional

import numpy as np
import pandas as pd
from geopandas import GeoDataFrame

WATBAL_PARAM_UNITS: dict[str, str] = {
    "rain": "mm/j",
    "etp": "mm/j",
    "etr": "mm/j",
    "runoff": "mm/j",
    "inf": "mm/j",
    "effective_rainfall": "mm/j",
}


def save_area_values_npy(npy_path: str, data: np.ndarray) -> None:
    """Persist the raw per-cell value array for a masked area to ``npy_path``.

    :param npy_path: Destination path for the ``.npy`` artefact.
    :param data: Raw per-cell array (shape ``(n_cells, n_timesteps)``) returned
        by a polygon-scoped mask query.
    """
    np.save(npy_path, data)


def save_area_geopackage(
    gpkg_path: str,
    cells_gdf: GeoDataFrame,
    values_responses: Mapping[str, object],
    provenance: dict,
    polygon_totals: Optional[Mapping[str, "pd.DataFrame"]] = None,
    daily_values_unit_override: Optional[str] = None,
) -> None:
    """Persist a transportable GeoPackage for a masked area.

    The produced file contains:

    - a ``cells`` vector layer with columns ``cell_id`` and ``geometry``
      (and, when the caller's ``cells_gdf`` already has a ``weight``
      column, that column is preserved — used by the weighted-mask path);
    - a non-spatial ``daily_values`` table in long form with columns
      ``cell_id``, ``date``, ``param``, ``value``, ``unit``;
    - one optional non-spatial table per requested param (named
      ``polygon_total_<param>``) when ``polygon_totals`` is supplied —
      typically the weighted-mask path;
    - a non-spatial ``provenance`` table holding exactly one row, the
      values of which come straight from the ``provenance`` dict.

    The writer trusts that ``cells_gdf.crs`` is already correct (the caller
    is responsible for the ``verify_crs_match`` step). The function does
    not touch CRS. An existing file at ``gpkg_path`` is silently
    overwritten.

    :param gpkg_path: Destination ``.gpkg`` path.
    :param cells_gdf: GeoDataFrame with a ``cell_id`` column and geometry,
        one row per masked cell. When a ``weight`` column is present it
        is written into the ``cells`` layer alongside the geometry.
    :param values_responses: Mapping ``{param: ValuesResponse}``. Each
        ``ValuesResponse`` must expose ``data`` of shape
        ``(n_cells, n_timesteps)``, ``dates`` of length ``n_timesteps``,
        and the row order of ``data`` must match the row order of
        ``cells_gdf``.
    :param provenance: One-row provenance dict (assembled by the caller).
    :param polygon_totals: Optional ``{param: DataFrame}`` mapping; each
        DataFrame is the daily ``date, polygon_total`` series for that
        param. Written as ``polygon_total_<param>`` tables. ``None`` skips
        the polygon-total layer entirely.
    :param daily_values_unit_override: When set, used as the ``unit``
        column value for every row in ``daily_values`` (used by the
        weighted-mask path where values are ``m³/day`` rather than the
        per-param native unit declared in ``WATBAL_PARAM_UNITS``).
    """
    from pathlib import Path as _Path  # noqa: PLC0415

    # Ensure the "silent overwrite" contract: GeoPandas.to_file with driver=
    # "GPKG" appends layers by default, leaving stale layers from prior runs
    # in place. Removing the file first guarantees a clean bundle.
    _Path(gpkg_path).unlink(missing_ok=True)

    cell_cols = ["cell_id"]
    if "weight" in cells_gdf.columns:
        cell_cols.append("weight")
    cell_cols.append("geometry")
    cells_gdf[cell_cols].to_file(gpkg_path, driver="GPKG", layer="cells")

    # Vectorised long-form build (design.md D11). Equivalent to a
    # ``param × cell × date`` triple loop emitting
    # ``(cell_id, date, param, value, unit)`` rows in cell-major order, but
    # without the per-row Python overhead — at 1500 cells × 25 yr × 3 params
    # (~41 M rows) the loop was the dominant, UI-blocking cost.
    cell_ids = np.asarray(cells_gdf["cell_id"])
    frames = []
    for param, response in values_responses.items():
        unit = daily_values_unit_override or WATBAL_PARAM_UNITS.get(param, "")
        data = np.asarray(response.data, dtype=float)   # (n_cells, n_days)
        dates = np.asarray(response.dates)         # (n_days,)
        n_cells, n_days = data.shape
        if n_cells != cell_ids.shape[0]:
            raise ValueError(
                f"cells_gdf has {cell_ids.shape[0]} cells but param {param!r} "
                f"data has {n_cells} cells — cells_gdf and the per-param "
                "ValuesResponse must be row-aligned."
            )
        frames.append(
            pd.DataFrame(
                {
                    "cell_id": np.repeat(cell_ids, n_days),  # cell-major
                    "date": np.tile(dates, n_cells),
                    "param": param,
                    # row-major ravel == cell-major, matching repeat/tile
                    "value": data.ravel(),
                    "unit": unit,
                }
            )
        )
    daily_values = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["cell_id", "date", "param", "value", "unit"])
    )

    provenance_df = pd.DataFrame([provenance])

    with sqlite3.connect(gpkg_path) as con:
        daily_values.to_sql(
            "daily_values", con, if_exists="replace", index=False
        )
        if polygon_totals:
            for param, df in polygon_totals.items():
                df.to_sql(
                    f"polygon_total_{param}", con, if_exists="replace", index=False
                )
        provenance_df.to_sql(
            "provenance", con, if_exists="replace", index=False
        )
