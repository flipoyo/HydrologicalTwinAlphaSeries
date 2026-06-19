"""Privileged artefact writers for area-scoped submodel-grade data.

This module lives in ``services/private/`` because it persists the raw
per-cell simulation array for a user-selected area — a Tier-1 leak surface
under the project security model. See ``services/SECURITY.md`` for the
placement rule and the threat tiers.

Two writers live here today:

- :func:`save_area_values_npy` — the raw ``.npy`` write of the per-cell
  value array for one param of a masked area; the precursor of the
  area-scoped submodel numpy.
- :func:`save_area_geopackage` — bundles, for every requested compartment,
  the masked cells geometry (one ``cells_<compartment>`` layer per mesh),
  the long-form per-(compartment, cell, date, param) values table, and a
  per-compartment provenance table into a single transportable GeoPackage.
  Same Tier-1 leak surface (user-supplied geometry + raw per-cell numeric
  arrays on disk), hosted next to ``save_area_values_npy`` so every
  privileged writer is reachable from one auditable import path.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from geopandas import GeoDataFrame

# Native per-param units for the internal-values params, used when no
# ``daily_values_unit_override`` is supplied. Covers WATBAL water-balance
# terms and AQ params (e.g. recharge) so a single, compartment-agnostic
# lookup resolves a unit for every internal-values param.
INTERNAL_VALUES_PARAM_UNITS: dict[str, str] = {
    "rain": "mm/j",
    "etp": "mm/j",
    "etr": "mm/j",
    "runoff": "mm/j",
    "inf": "mm/j",
    "effective_rainfall": "mm/j",
    "recharge": "mm/j",
}

# Backwards-compatible alias — the lookup is now compartment-agnostic.
WATBAL_PARAM_UNITS = INTERNAL_VALUES_PARAM_UNITS


def save_area_values_npy(npy_path: str, data: np.ndarray) -> None:
    """Persist the raw per-cell value array for a masked area to ``npy_path``.

    :param npy_path: Destination path for the ``.npy`` artefact.
    :param data: Raw per-cell array (shape ``(n_cells, n_timesteps)``) returned
        by a polygon-scoped mask query.
    """
    np.save(npy_path, data)


# One compartment's contribution to the bundle: its masked cells geometry,
# the per-param value responses to vectorise into ``daily_values``, and the
# optional per-param polygon-total daily series (weighted path only).
CompartmentBlock = Tuple[
    GeoDataFrame,                       # cells_gdf (cell_id + geometry [+ weight])
    Mapping[str, object],              # {param: ValuesResponse}
    Optional[Mapping[str, "pd.DataFrame"]],  # {param: polygon_total DataFrame} or None
]


def save_area_geopackage(
    gpkg_path: str,
    compartment_blocks: Mapping[str, CompartmentBlock],
    provenance_rows: Sequence[dict],
    daily_values_unit_override: Optional[Union[str, Mapping[str, str]]] = None,
) -> None:
    """Persist a transportable multi-compartment GeoPackage for a masked area.

    The produced file is a single Internal Values bundle spanning every
    requested compartment (WATBAL surface cells, AQ aquifer cells, …). It
    contains:

    - one ``cells_<compartment>`` vector layer per mesh (e.g.
      ``cells_WATBAL``, ``cells_AQ``), each with columns ``cell_id`` and
      ``geometry`` (and, when that compartment's ``cells_gdf`` already has a
      ``weight`` column, that column is preserved — the weighted-mask path);
    - a single non-spatial ``daily_values`` table in long form with columns
      ``compartment``, ``cell_id``, ``date``, ``param``, ``value``, ``unit``.
      ``cell_id`` is unique only *within* a compartment, so a consumer joins
      ``daily_values`` to the matching ``cells_<compartment>`` layer on the
      pair ``(compartment, cell_id)``;
    - one optional non-spatial table per (compartment, param) named
      ``polygon_total_<compartment>_<param>`` when that compartment supplies
      polygon totals — typically the weighted-mask path;
    - a non-spatial ``provenance`` table holding one row per compartment.
      Run-level fields are identical across rows; ``compartment``, ``params``
      and ``weighted`` vary.

    The writer trusts that each ``cells_gdf.crs`` is already correct (the
    caller is responsible for the ``verify_crs_match`` step). The function
    does not touch CRS. An existing file at ``gpkg_path`` is silently
    overwritten.

    :param gpkg_path: Destination ``.gpkg`` path.
    :param compartment_blocks: Mapping ``{compartment: (cells_gdf,
        values_responses, polygon_totals)}``. For each compartment:

        * ``cells_gdf`` — GeoDataFrame with a ``cell_id`` column and
          geometry, one row per masked cell of that mesh. A ``weight``
          column, when present, is written into the
          ``cells_<compartment>`` layer.
        * ``values_responses`` — mapping ``{param: ValuesResponse}``. Each
          ``ValuesResponse`` exposes ``data`` of shape
          ``(n_cells, n_timesteps)`` and ``dates`` of length
          ``n_timesteps``; the row order of ``data`` must match the row
          order of *this compartment's* ``cells_gdf``.
        * ``polygon_totals`` — optional ``{param: DataFrame}`` mapping
          (daily ``date, polygon_total`` series), or ``None`` to skip the
          polygon-total tables for that compartment.
    :param provenance_rows: One provenance dict per compartment (assembled
        by the caller). Written as the ``provenance`` table, one row each.
    :param daily_values_unit_override: Selects the ``unit`` column value for
        ``daily_values`` rows. A plain ``str`` is applied to every row
        (legacy single-unit runs). A ``Mapping[param, unit]`` supplies a
        per-param unit so a single bundle can mix units (e.g. HYD Flow in
        ``m3/s`` and Water Height in ``m``); a param absent from the mapping
        falls back to its native unit in ``INTERNAL_VALUES_PARAM_UNITS``.
        ``None`` uses the native lookup for every param.
    """
    from pathlib import Path as _Path  # noqa: PLC0415

    # Ensure the "silent overwrite" contract: GeoPandas.to_file with driver=
    # "GPKG" appends layers by default, leaving stale layers from prior runs
    # in place. Removing the file first guarantees a clean bundle.
    _Path(gpkg_path).unlink(missing_ok=True)

    # One cells_<compartment> vector layer per mesh, plus one daily_values
    # block per compartment (each row-aligned to *its own* cells_gdf), then
    # concatenated into a single long-form table carrying a ``compartment``
    # discriminator. polygon-total tables are namespaced per compartment so
    # cell-id ranges that repeat across meshes never collide.
    frames = []
    polygon_total_tables: dict[str, "pd.DataFrame"] = {}
    for compartment, (cells_gdf, values_responses, polygon_totals) in (
        compartment_blocks.items()
    ):
        cell_cols = ["cell_id"]
        if "weight" in cells_gdf.columns:
            cell_cols.append("weight")
        cell_cols.append("geometry")
        cells_gdf[cell_cols].to_file(
            gpkg_path, driver="GPKG", layer=f"cells_{compartment}"
        )

        # Vectorised long-form build (design.md D11). Equivalent to a
        # ``param × cell × date`` triple loop emitting
        # ``(compartment, cell_id, date, param, value, unit)`` rows in
        # cell-major order, but without the per-row Python overhead — at
        # 1500 cells × 25 yr × 3 params (~41 M rows) the loop was the
        # dominant, UI-blocking cost. The shape assertion is scoped per
        # compartment: each param block must be row-aligned to this
        # compartment's own cells_gdf.
        cell_ids = np.asarray(cells_gdf["cell_id"])
        for param, response in values_responses.items():
            if isinstance(daily_values_unit_override, Mapping):
                # Per-param override (one unit per spec); fall back to the
                # native lookup for any param not present in the mapping.
                unit = daily_values_unit_override.get(
                    param
                ) or INTERNAL_VALUES_PARAM_UNITS.get(param, "")
            else:
                unit = (
                    daily_values_unit_override
                    or INTERNAL_VALUES_PARAM_UNITS.get(param, "")
                )
            data = np.asarray(response.data, dtype=float)   # (n_cells, n_days)
            dates = np.asarray(response.dates)         # (n_days,)
            n_cells, n_days = data.shape
            if n_cells != cell_ids.shape[0]:
                raise ValueError(
                    f"cells_<{compartment}> has {cell_ids.shape[0]} cells but "
                    f"param {param!r} data has {n_cells} cells — cells_gdf and "
                    "the per-param ValuesResponse must be row-aligned."
                )
            frames.append(
                pd.DataFrame(
                    {
                        "compartment": compartment,
                        "cell_id": np.repeat(cell_ids, n_days),  # cell-major
                        "date": np.tile(dates, n_cells),
                        "param": param,
                        # row-major ravel == cell-major, matching repeat/tile
                        "value": data.ravel(),
                        "unit": unit,
                    }
                )
            )

        if polygon_totals:
            for param, df in polygon_totals.items():
                polygon_total_tables[
                    f"polygon_total_{compartment}_{param}"
                ] = df

    daily_values = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=["compartment", "cell_id", "date", "param", "value", "unit"]
        )
    )

    provenance_df = pd.DataFrame(list(provenance_rows))

    with sqlite3.connect(gpkg_path) as con:
        daily_values.to_sql(
            "daily_values", con, if_exists="replace", index=False
        )
        for table_name, df in polygon_total_tables.items():
            df.to_sql(table_name, con, if_exists="replace", index=False)
        provenance_df.to_sql(
            "provenance", con, if_exists="replace", index=False
        )
