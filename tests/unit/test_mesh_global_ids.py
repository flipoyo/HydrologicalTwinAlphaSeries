"""Unit tests for global cell indexing (``Cell.id_abs``) in ``domain/Mesh.py``.

Covers the ``mesh-global-cell-indexing`` capability. The mesh GIS id column
already carries the CaWaQS absolute id (``Id_ABS`` for AQ; corresp-mapped for
HYD), and every matrix lookup indexes ``data[cell.id - 1]`` — so ``id_abs`` is
an explicit alias of ``cell.id`` (the absolute, globally-unique matrix id),
NOT a gdf-iteration position. Real meshes are not guaranteed to be
``Id_ABS``-sorted, so these tests deliberately shuffle the gdf order.
"""

import geopandas as gpd
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.config.constants import reversed_module_caw
from HydrologicalTwinAlphaSeries.domain.Mesh import Mesh


class _ConfigStub:
    """Minimal config exposing ``idColCells`` as ``Mesh.buildLayer`` expects."""

    def __init__(self, id_compartment, col_name):
        self.idColCells = {id_compartment: col_name}


def _square(x, y):
    return box(x, y, x + 1, y + 1)


def _layer_gdf(ids, xs):
    """One-row-per-id GeoDataFrame whose ``id_col`` is the absolute CaWaQS id."""
    return gpd.GeoDataFrame(
        {"id_col": ids, "geometry": [_square(x, 0) for x in xs]},
        crs="EPSG:2154",
    )


def _build_synthetic_aq_mesh():
    """Two-layer AQ mesh keyed on globally-unique absolute ids (``Id_ABS``).

    Layer 0 holds absolute ids 1,2,3; layer 1 continues with 4,5 — globally
    unique, exactly like the real ``Id_ABS`` column. The gdf rows are
    deliberately NOT in ``Id_ABS`` order (layer 0 is shuffled to 3,1,2) so the
    test fails if anything keys ``id_abs`` off gdf position instead of the id.
    """
    id_compartment = reversed_module_caw["AQ"]
    layer_gdfs = {
        # gdf rows out of Id_ABS order: ids 3,1,2 at x-positions 2,0,1
        "layer0": _layer_gdf([3, 1, 2], xs=[2, 0, 1]),
        "layer1": _layer_gdf([5, 4], xs=[4, 3]),
    }
    return Mesh(
        id_compartment=id_compartment,
        layers_gis_name=["layer0", "layer1"],
        layer_gdfs=layer_gdfs,
        config=_ConfigStub(id_compartment, "id_col"),
        out_caw_directory="",
    )


def test_id_abs_equals_absolute_cell_id():
    mesh = _build_synthetic_aq_mesh()

    for layer in mesh.mesh.values():
        for cell in layer.layer:
            assert cell.id_abs is not None
            assert cell.id_abs == cell.id  # id_abs is an alias of the absolute id


def test_id_abs_is_unique_across_layers():
    mesh = _build_synthetic_aq_mesh()

    all_id_abs = [
        cell.id_abs for layer in mesh.mesh.values() for cell in layer.layer
    ]

    assert None not in all_id_abs
    assert sorted(all_id_abs) == [1, 2, 3, 4, 5]  # globally unique, no collision


def test_id_abs_independent_of_gdf_row_order():
    mesh = _build_synthetic_aq_mesh()

    # Layer 0's first gdf row carries Id_ABS 3 (not 1): id_abs must follow the
    # id, not the row position, so it is 3 — never the position-based 1.
    first_built_cell = mesh.mesh[0].layer[0]
    assert first_built_cell.id == 3
    assert first_built_cell.id_abs == 3  # NOT 1 (which a position scheme gives)
