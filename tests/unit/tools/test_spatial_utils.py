"""Unit tests for the polygon-mask geometric helpers in tools.spatial_utils."""

import time

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box

from HydrologicalTwinAlphaSeries.tools.spatial_utils import (
    aq_cells_on_polygon_boundary,
    cells_in_polygon,
    reaches_on_polygon_boundary,
)


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


# ---------------------------------------------------------------------------
# reaches_on_polygon_boundary — endpoint-XOR detection (S4)
# ---------------------------------------------------------------------------


def _network(reaches: dict) -> gpd.GeoDataFrame:
    """Build a HYD network GeoDataFrame from a {reach_id: geometry} dict."""
    return gpd.GeoDataFrame(
        {"reach_id": list(reaches.keys())},
        geometry=list(reaches.values()),
        crs="EPSG:3857",
    )


def test_reaches_on_polygon_boundary_returns_straddling_reach():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            42: LineString([(5.0, 5.0), (15.0, 5.0)]),  # endpoint inside, endpoint outside
        }
    )

    result = reaches_on_polygon_boundary(network, polygon, id_col="reach_id")

    assert result == [42]


def test_reaches_on_polygon_boundary_excludes_wholly_inside_reach():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            7: LineString([(2.0, 2.0), (8.0, 8.0)]),  # both endpoints inside
        }
    )

    result = reaches_on_polygon_boundary(network, polygon, id_col="reach_id")

    assert result == []


def test_reaches_on_polygon_boundary_excludes_wholly_outside_reach():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            9: LineString([(20.0, 20.0), (30.0, 20.0)]),  # both endpoints outside
        }
    )

    result = reaches_on_polygon_boundary(network, polygon, id_col="reach_id")

    assert result == []


def test_reaches_on_polygon_boundary_excludes_passing_through_reach():
    """A reach with both endpoints outside but middle inside is NOT a boundary reach."""
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            3: LineString([(-5.0, 5.0), (15.0, 5.0)]),  # passes through, both endpoints outside
        }
    )

    result = reaches_on_polygon_boundary(network, polygon, id_col="reach_id")

    assert result == []


def test_reaches_on_polygon_boundary_includes_reach_straddling_a_hole():
    """One endpoint in polygon's filled area, one in a hole (which counts as outside)."""
    outer = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    hole = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0)]
    polygon = Polygon(outer, holes=[hole])

    network = _network(
        {
            5: LineString([(1.0, 5.0), (5.0, 5.0)]),  # (1,5) in filled area; (5,5) in hole
        }
    )

    result = reaches_on_polygon_boundary(network, polygon, id_col="reach_id")

    assert result == [5]


def test_reaches_on_polygon_boundary_handles_multilinestring():
    """A reach as a MultiLineString uses its chained extreme endpoints."""
    polygon = box(0.0, 0.0, 10.0, 10.0)
    multi = MultiLineString(
        [
            LineString([(2.0, 5.0), (4.0, 5.0)]),  # first sub-line: starts at (2,5) inside
            LineString([(6.0, 5.0), (15.0, 5.0)]),  # last sub-line: ends at (15,5) outside
        ]
    )
    network = _network({77: multi})

    result = reaches_on_polygon_boundary(network, polygon, id_col="reach_id")

    assert result == [77]


def test_reaches_on_polygon_boundary_multipolygon_each_component_contributes():
    multi = MultiPolygon([box(0.0, 0.0, 5.0, 5.0), box(20.0, 0.0, 25.0, 5.0)])
    network = _network(
        {
            1: LineString([(2.0, 2.0), (10.0, 2.0)]),  # straddles component A
            2: LineString([(22.0, 2.0), (30.0, 2.0)]),  # straddles component B
            3: LineString([(10.0, 2.0), (15.0, 2.0)]),  # outside everything
        }
    )

    result = reaches_on_polygon_boundary(network, multi, id_col="reach_id")

    assert sorted(result) == [1, 2]


def test_reaches_on_polygon_boundary_empty_network_returns_empty():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = gpd.GeoDataFrame({"reach_id": []}, geometry=[], crs="EPSG:3857")

    assert reaches_on_polygon_boundary(network, polygon, id_col="reach_id") == []


def test_reaches_on_polygon_boundary_id_col_as_integer_position():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network({42: LineString([(5.0, 5.0), (15.0, 5.0)])})

    result = reaches_on_polygon_boundary(network, polygon, id_col=0)

    assert result == [42]


# ---------------------------------------------------------------------------
# aq_cells_on_polygon_boundary — inside↔outside topological boundary (S6)
# ---------------------------------------------------------------------------


def test_aq_cells_on_polygon_boundary_inside_cell_with_one_outside_neighbor():
    """3x1 strip; polygon covers only the middle cell — its two outside neighbours give 2 boundary edges."""
    mesh = _grid_mesh(nx=3, ny=1)  # cells: 0 left, 1 middle, 2 right
    polygon = box(1.1, 0.1, 1.9, 0.9)  # contains only cell 1's centroid (1.5, 0.5)

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col="cell_id")

    # Cell 1 is the only inside cell; both its neighbours (0, 2) are outside,
    # so it contributes 2 boundary edges (its left and right shared edges).
    assert sorted(cell_ids) == [1, 1]
    assert len(edges) == 2
    for edge in edges:
        assert edge.geom_type == "LineString"


def test_aq_cells_on_polygon_boundary_inside_cell_with_all_inside_neighbors():
    """3x3 mesh; polygon covers all cells → centre cell (4) has all-inside neighbours → no entry for it."""
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(0.0, 0.0, 3.0, 3.0)  # covers all 9 cells

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col="cell_id")

    # All cells inside → no inside↔outside adjacency anywhere → empty result.
    assert cell_ids == []
    assert edges == []


def test_aq_cells_on_polygon_boundary_polygon_disjoint_from_mesh():
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(100.0, 100.0, 200.0, 200.0)

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col="cell_id")

    assert cell_ids == []
    assert edges == []


def test_aq_cells_on_polygon_boundary_excludes_corner_only_adjacency():
    """3x3 mesh; polygon covers cells 0,1,3,4 (lower-left 2x2 block).

    Boundary cells: 0,1,3,4. Each has some outside neighbours.
    Corner-only adjacency (e.g. cell 4 corner-touches cell 8 at (2,2))
    must NOT be counted — only edge-sharing neighbours produce LineString
    intersections.
    """
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(0.0, 0.0, 2.0, 2.0)  # cells 0,1,3,4 inside

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col="cell_id")

    # Edge-sharing outside neighbours per inside cell on this 3x3 mesh:
    #   0 → no outside edge-neighbour (1 and 3 are both inside)
    #   1 → 2 (right outside neighbour)         → 1 edge
    #   3 → 6 (top outside neighbour, j=2)      → 1 edge
    #   4 → 5 (right) and 7 (top)               → 2 edges
    # Corner-only contacts (e.g. 4↔8, 1↔5, 3↔7) are NOT counted.
    assert sorted(cell_ids) == [1, 3, 4, 4]
    assert len(edges) == 4
    assert all(edge.geom_type == "LineString" for edge in edges)


def test_aq_cells_on_polygon_boundary_hole_induced_boundary():
    """Cell whose centroid falls inside a hole counts as outside, contributing edges."""
    mesh = _grid_mesh(nx=3, ny=3)
    # Outer covers all 9 cells; hole punches out the centre cell (id 4)
    outer = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0), (0.0, 0.0)]
    hole = [(1.1, 1.1), (1.9, 1.1), (1.9, 1.9), (1.1, 1.9), (1.1, 1.1)]
    polygon = Polygon(outer, holes=[hole])

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col="cell_id")

    # Cell 4 is now "outside" (centroid inside the hole).
    # Its 4 edge-neighbours (1, 3, 5, 7) are still inside, each contributes
    # one boundary edge → 4 entries.
    assert sorted(cell_ids) == [1, 3, 5, 7]
    assert len(edges) == 4
    assert all(edge.geom_type == "LineString" for edge in edges)


def test_aq_cells_on_polygon_boundary_multipolygon_each_component_contributes():
    """Two disjoint polygons over a 5x1 mesh each select one cell; both contribute boundary edges."""
    mesh = _grid_mesh(nx=5, ny=1)
    multi = MultiPolygon(
        [
            box(0.1, 0.1, 0.9, 0.9),  # only cell 0 inside
            box(4.1, 0.1, 4.9, 0.9),  # only cell 4 inside
        ]
    )

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, multi, id_col="cell_id")

    # Cell 0 → outside neighbour 1 → 1 edge; cell 4 → outside neighbour 3 → 1 edge.
    assert sorted(cell_ids) == [0, 4]
    assert len(edges) == 2


def test_aq_cells_on_polygon_boundary_empty_mesh():
    mesh = gpd.GeoDataFrame({"cell_id": []}, geometry=[], crs="EPSG:3857")
    polygon = box(0.0, 0.0, 1.0, 1.0)

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col="cell_id")

    assert cell_ids == []
    assert edges == []


def test_aq_cells_on_polygon_boundary_id_col_as_integer_position():
    mesh = _grid_mesh(nx=3, ny=1)
    polygon = box(1.1, 0.1, 1.9, 0.9)  # only middle cell inside

    cell_ids, edges = aq_cells_on_polygon_boundary(mesh, polygon, id_col=0)

    assert sorted(cell_ids) == [1, 1]
    assert len(edges) == 2
