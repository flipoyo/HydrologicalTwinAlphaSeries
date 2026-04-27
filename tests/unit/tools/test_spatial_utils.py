"""Unit tests for the polygon-mask geometric helpers in tools.spatial_utils."""

import time

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from HydrologicalTwinAlphaSeries.tools.spatial_utils import cells_in_polygon


def _grid_mesh(nx: int = 3, ny: int = 3, *, with_id_col: bool = True) -> gpd.GeoDataFrame:
    """Build a regular nx x ny grid of unit-square cells, ids 0..nx*ny-1."""
    geometries = []
    ids = []
    for j in range(ny):
        for i in range(nx):
            geometries.append(box(i, j, i + 1, j + 1))
            ids.append(j * nx + i)
    data = {"cell_id": ids} if with_id_col else {}
    # Use a projected CRS so centroid math is correct (lat/lon would warn).
    return gpd.GeoDataFrame(data, geometry=geometries, crs="EPSG:3857")


def test_cells_in_polygon_returns_known_subset():
    mesh = _grid_mesh(nx=3, ny=3)
    # Polygon covering the lower-left 2x2 block of cells (ids 0,1,3,4)
    polygon = box(0.1, 0.1, 1.9, 1.9)

    result = cells_in_polygon(mesh, polygon, id_col="cell_id")

    assert sorted(result) == [0, 1, 3, 4]


def test_cells_in_polygon_id_col_as_integer_position():
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(0.1, 0.1, 1.9, 1.9)

    # cell_id is column index 0 (only non-geometry column)
    result = cells_in_polygon(mesh, polygon, id_col=0)

    assert sorted(result) == [0, 1, 3, 4]


def test_cells_in_polygon_multipolygon_unions_components():
    mesh = _grid_mesh(nx=3, ny=3)
    # Two disjoint polygons: lower-left cell + upper-right cell
    multi = MultiPolygon([box(0.1, 0.1, 0.9, 0.9), box(2.1, 2.1, 2.9, 2.9)])

    result = cells_in_polygon(mesh, multi, id_col="cell_id")

    assert sorted(result) == [0, 8]


def test_cells_in_polygon_excludes_centroids_inside_hole():
    mesh = _grid_mesh(nx=3, ny=3)
    # Outer covers entire 3x3; hole punches out the centre cell (id 4) at (1.5, 1.5)
    outer = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0), (0.0, 0.0)]
    hole = [(1.1, 1.1), (1.9, 1.1), (1.9, 1.9), (1.1, 1.9), (1.1, 1.1)]
    polygon = Polygon(outer, holes=[hole])

    result = cells_in_polygon(mesh, polygon, id_col="cell_id")

    assert 4 not in result
    assert sorted(result) == [0, 1, 2, 3, 5, 6, 7, 8]


def test_cells_in_polygon_disjoint_returns_empty():
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(10.0, 10.0, 12.0, 12.0)

    result = cells_in_polygon(mesh, polygon, id_col="cell_id")

    assert result == []


def test_cells_in_polygon_empty_mesh_returns_empty():
    mesh = gpd.GeoDataFrame({"cell_id": []}, geometry=[], crs="EPSG:3857")
    polygon = box(0.0, 0.0, 1.0, 1.0)

    result = cells_in_polygon(mesh, polygon, id_col="cell_id")

    assert result == []


@pytest.mark.slow
def test_cells_in_polygon_performance_on_large_mesh():
    """Performance gate: 14k cells, polygon covering half, must run in < 2 s."""
    nx, ny = 140, 100  # 14 000 cells
    mesh = _grid_mesh(nx=nx, ny=ny)
    half_polygon = box(0.0, 0.0, nx / 2.0, ny)

    start = time.perf_counter()
    result = cells_in_polygon(mesh, half_polygon, id_col="cell_id")
    elapsed = time.perf_counter() - start

    expected_count = (nx // 2) * ny
    assert len(result) == expected_count
    assert elapsed < 2.0, f"cells_in_polygon took {elapsed:.2f}s, expected < 2s"


def test_cells_in_polygon_returns_python_ints_not_numpy():
    """Returned ids should be the plain values from the column (not numpy scalars)."""
    mesh = _grid_mesh(nx=2, ny=2)
    polygon = box(0.1, 0.1, 0.9, 0.9)

    result = cells_in_polygon(mesh, polygon, id_col="cell_id")

    assert len(result) == 1
    # Values from the column come back as numpy ints (from int64 column);
    # what matters is they compare equal to plain ints.
    assert result[0] == 0
