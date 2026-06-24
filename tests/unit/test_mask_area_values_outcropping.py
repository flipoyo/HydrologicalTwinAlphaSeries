"""Tests for the AQ outcropping resolution selector on the area_values mask path.

Covers the ``htas-mask-operations`` capability:
- AQ internal-values specs (``resolution="outcropping"``) resolve cells against
  the cross-layer outcropping mesh keyed on global ``id_abs`` and index the
  matrix by ``data[id_abs - 1]`` — correct for a deeper-layer cell.
- WATBAL specs (default ``resolution="single_layer"``) keep the single-layer
  path keyed on the per-layer GIS id, byte-identical to prior behaviour.
"""

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.ht import (
    HydrologicalTwin,
    TwinState,
    ValuesResponse,
)


def _twin_in_loaded_state() -> HydrologicalTwin:
    twin = HydrologicalTwin()
    twin._state = TwinState.LOADED
    return twin


def _full_mesh_response(n_cells: int, n_timesteps: int = 4) -> ValuesResponse:
    """Row i carries the constant value (i+1) so a caller can read off which
    matrix row (global id_abs - 1) each selected cell mapped to."""
    data = np.ones((n_cells, n_timesteps)) * np.arange(1, n_cells + 1).reshape(-1, 1)
    dates = np.arange("2010-08-01", "2010-08-05", dtype="datetime64[D]")
    return ValuesResponse(data=data, dates=dates)


def _area_values_kwargs(**overrides):
    base = {
        "kind": "area_values",
        "id_compartment": 1,
        "outtype": "MB",
        "param": "recharge",
        "syear": 2010,
        "eyear": 2011,
        "target_unit": "m3/j",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 5.2 — AQ correctness: deeper-layer outcropping cell selected & indexed
# ---------------------------------------------------------------------------


def _outcropping_gdf():
    """Cross-layer outcropping mesh.

    Two layer-0 cells (id_abs 1,2) and one deeper-layer outcropping cell whose
    per-layer cell.id would be 1 but whose GLOBAL id_abs is 6 (it lives in a
    later matrix block). Geometry places the deep cell at x in [2,3).
    """
    return gpd.GeoDataFrame(
        {
            "id_abs": [1, 2, 6],
            "area": [1.0, 1.0, 1.0],
            "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)],
        },
        crs="EPSG:3857",
        geometry="geometry",
    )


def test_outcropping_resolution_selects_deeper_cell_and_indexes_its_row(monkeypatch):
    twin = _twin_in_loaded_state()
    monkeypatch.setattr(
        twin, "_build_outcropping_mesh_gdf", lambda *_a, **_k: _outcropping_gdf()
    )
    # 6 matrix rows: row i carries value i+1, so id_abs 6 → value 6.
    monkeypatch.setattr(
        twin, "read_watbal_converted", lambda **_k: _full_mesh_response(n_cells=6)
    )

    # Polygon covers only the deeper-layer outcropping cell (x in [2,3)).
    polygon = box(2.1, 0.1, 2.9, 0.9)

    response = twin.mask(**_area_values_kwargs(polygon=polygon, resolution="outcropping"))

    # The deep cell's global id_abs (6) is the selected label, and the value is
    # read from data[id_abs - 1] = data[5] = 6.0 — NOT data[0] (the colliding
    # per-layer id 1's row, which would wrongly yield 1.0).
    assert response.meta["cell_ids"] == [6]
    np.testing.assert_array_equal(response.data[:, 0], [6.0])


def test_outcropping_resolution_includes_layer0_and_deep_cells(monkeypatch):
    twin = _twin_in_loaded_state()
    monkeypatch.setattr(
        twin, "_build_outcropping_mesh_gdf", lambda *_a, **_k: _outcropping_gdf()
    )
    monkeypatch.setattr(
        twin, "read_watbal_converted", lambda **_k: _full_mesh_response(n_cells=6)
    )

    # Polygon spans layer-0 cells (x in [0,2)) AND the deep cell (x in [2,3)).
    polygon = box(0.1, 0.1, 2.9, 0.9)

    response = twin.mask(**_area_values_kwargs(polygon=polygon, resolution="outcropping"))

    assert sorted(response.meta["cell_ids"]) == [1, 2, 6]
    # Values map by id_abs - 1 → rows 0,1,5 → 1.0, 2.0, 6.0.
    np.testing.assert_array_equal(sorted(response.data[:, 0].tolist()), [1.0, 2.0, 6.0])


# ---------------------------------------------------------------------------
# 5.1 — WATBAL parity: default single-layer path unchanged
# ---------------------------------------------------------------------------


def _grid_mesh(nx=3, ny=3, crs="EPSG:3857"):
    geometries, ids = [], []
    for j in range(ny):
        for i in range(nx):
            geometries.append(box(i, j, i + 1, j + 1))
            ids.append(j * nx + i + 1)  # 1-based per-layer GIS ids
    return gpd.GeoDataFrame({"cell_id": ids}, geometry=geometries, crs=crs)


def test_watbal_default_resolution_uses_single_layer_path(monkeypatch):
    twin = _twin_in_loaded_state()
    mesh = _grid_mesh()  # 9 cells, ids 1..9
    monkeypatch.setattr(twin, "_resolve_mesh_gdf", lambda *_a, **_k: mesh)
    import HydrologicalTwinAlphaSeries.ht.developer.dispatch as _dispatch
    monkeypatch.setattr(_dispatch, "_resolve_cell_id_col", lambda *_a, **_k: "cell_id")

    def _outcropping_must_not_be_called(*_a, **_k):
        raise AssertionError(
            "WATBAL (single_layer) must NOT touch the outcropping resolver"
        )

    monkeypatch.setattr(twin, "_build_outcropping_mesh_gdf", _outcropping_must_not_be_called)
    monkeypatch.setattr(
        twin, "read_watbal_converted", lambda **_k: _full_mesh_response(n_cells=9)
    )

    polygon = box(0.1, 0.1, 1.9, 1.9)  # cells 1,2,4,5

    # No resolution kwarg → defaults to "single_layer".
    response = twin.mask(**_area_values_kwargs(polygon=polygon))

    assert sorted(response.meta["cell_ids"]) == [1, 2, 4, 5]
    # id - 1 → rows 0,1,3,4 → values 1,2,4,5 (unchanged from prior behaviour).
    np.testing.assert_array_equal(sorted(response.data[:, 0].tolist()), [1.0, 2.0, 4.0, 5.0])
