"""Regression tests for global/unique ID_ABS in the multi-layer spatial gdf.

Covers the ``aq-outcropping-detection`` capability:
- ``assemble_multi_layer_geodataframe`` populates ID_ABS from the global
  ``id_abs`` (not per-layer ``cell.id``), so an outcropping ``.isin`` filter
  matches each cell uniquely across layers.
- For the full-layer-0 case (the real outcropping set always includes all of
  layer 0) the filtered cells are unchanged from prior behaviour.
"""

import numpy as np
import pandas as pd
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.ht.developer.api_types import LayerInfo
from HydrologicalTwinAlphaSeries.services.public.geodata_assembly import (
    assemble_multi_layer_geodataframe,
)


def _square(x):
    return box(x, 0, x + 1, 1)


def _two_layer_fixture():
    """Two layers with colliding per-layer ids but distinct global id_abs.

    Layer 0: cell.id 1,2,3 -> id_abs 1,2,3
    Layer 1: cell.id 1,2   -> id_abs 4,5   (per-layer ids RESTART, collide)
    """
    layer0 = LayerInfo(
        id_layer=0,
        n_cells=3,
        cell_ids=np.array([1, 2, 3]),
        cell_areas=np.array([1.0, 1.0, 1.0]),
        cell_geometries=[_square(0), _square(1), _square(2)],
        layer_gis_name="layer0",
        id_abs=np.array([1, 2, 3]),
    )
    layer1 = LayerInfo(
        id_layer=1,
        n_cells=2,
        cell_ids=np.array([1, 2]),
        cell_areas=np.array([1.0, 1.0]),
        cell_geometries=[_square(3), _square(4)],
        layer_gis_name="layer1",
        id_abs=np.array([4, 5]),
    )
    # agg_df: one date row, columns keyed by GLOBAL id_abs (1..5), as
    # _build_aq_spatial_gdf now passes comp_info.id_abs to aggregate_for_map.
    agg_df = pd.DataFrame(
        [[10.0, 20.0, 30.0, 40.0, 50.0]],
        index=["2000"],
        columns=[1, 2, 3, 4, 5],
    )
    return agg_df, [layer0, layer1]


def test_id_abs_column_is_global_and_unique():
    agg_df, layers = _two_layer_fixture()

    gdf = assemble_multi_layer_geodataframe(agg_df, layers, crs="EPSG:2154")

    assert gdf["ID_ABS"].tolist() == [1, 2, 3, 4, 5]
    assert gdf["ID_ABS"].is_unique


def test_outcropping_isin_filter_does_not_over_match_across_layers():
    agg_df, layers = _two_layer_fixture()
    gdf = assemble_multi_layer_geodataframe(agg_df, layers, crs="EPSG:2154")

    # Outcropping set: a deeper-layer cell (id_abs 4) but NOT the layer-0 cell
    # with the colliding per-layer id 1 (id_abs 1).
    outcropping_ids = np.array([4])
    filtered = gdf.loc[gdf["ID_ABS"].isin(outcropping_ids)]

    assert filtered["ID_ABS"].tolist() == [4]  # only the deep cell, no over-match


def test_full_layer0_case_selects_same_cells():
    agg_df, layers = _two_layer_fixture()
    gdf = assemble_multi_layer_geodataframe(agg_df, layers, crs="EPSG:2154")

    # buildAqOutcropping always includes all of layer 0; here layer 0 is the
    # whole outcrop (no deeper cell outcrops). Global filter == those cells.
    outcropping_ids = np.array([1, 2, 3])
    filtered = gdf.loc[gdf["ID_ABS"].isin(outcropping_ids)]

    assert filtered["ID_ABS"].tolist() == [1, 2, 3]
