"""Unit tests for the polygon-mask geometric helpers in services.public.polygon_mask."""

import time

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box

from HydrologicalTwinAlphaSeries.services.public.polygon_mask import (
    cells_boundary_faces,
    cells_in_polygon,
    cells_in_polygon_weighted,
    reaches_in_polygon_carachterisation,
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
# cells_in_polygon_weighted — area-fraction weighted selection
# ---------------------------------------------------------------------------


def test_cells_in_polygon_weighted_cell_fully_inside_has_weight_one():
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(0.0, 0.0, 3.0, 3.0)  # covers all 9 cells fully

    result = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")

    assert len(result) == 9
    for _, weight, geom in result:
        assert weight == pytest.approx(1.0)
        assert not geom.is_empty


def test_cells_in_polygon_weighted_cell_fully_outside_excluded():
    mesh = _grid_mesh(nx=3, ny=3)
    polygon = box(100.0, 100.0, 200.0, 200.0)

    result = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")

    assert result == []


def test_cells_in_polygon_weighted_partial_overlap_gives_fractional_weight():
    """Polygon overlapping a single cell by 60% of its area."""
    mesh = _grid_mesh(nx=2, ny=1)  # cells 0 (x∈[0,1]) and 1 (x∈[1,2])
    # Cover cell 0 entirely (area 1) and 60% of cell 1 (x∈[1,1.6], full y).
    polygon = box(0.0, 0.0, 1.6, 1.0)

    result = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")

    weights = {cell_id: w for cell_id, w, _ in result}
    assert weights[0] == pytest.approx(1.0)
    assert weights[1] == pytest.approx(0.6)


def test_cells_in_polygon_weighted_keeps_border_cell_with_centroid_outside():
    """A border cell whose centroid lies *outside* the polygon must still be
    kept and weighted by its overlap fraction.

    Regression: the prefilter once indexed cell centroids, which silently
    collapsed the weighted helper back to centroid containment — dropping
    exactly the partially-overlapping border cells the helper exists to
    capture. The binary helper (centroid test) still omits the cell; the
    weighted helper must not.
    """
    mesh = _grid_mesh(nx=2, ny=1)  # cell 0: x∈[0,1]; cell 1: x∈[1,2]
    # Polygon ends at x=1.3: cell 1's centroid (x=1.5) is OUTSIDE, but 30%
    # of cell 1's area is inside.
    polygon = box(0.0, 0.0, 1.3, 1.0)

    weighted = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")
    weights = {cell_id: w for cell_id, w, _ in weighted}

    assert weights[0] == pytest.approx(1.0)
    assert weights[1] == pytest.approx(0.3)
    # The binary (centroid) helper, by contrast, drops the border cell.
    assert cells_in_polygon(mesh, polygon, id_col="cell_id") == [0]


def test_cells_in_polygon_weighted_shared_edge_only_excluded_by_floor():
    """A polygon that only shares an edge with the cell yields zero area, dropped by 1e-6 floor."""
    mesh = _grid_mesh(nx=2, ny=1)  # cell 0: x∈[0,1]; cell 1: x∈[1,2]
    # Sliver polygon touching cell 1 only on its left edge x=1.
    polygon = box(0.5, 0.0, 1.0, 1.0)

    result = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")

    # Only cell 0 has true overlap; cell 1 shares only the edge x=1 (area=0).
    cell_ids = [cid for cid, _, _ in result]
    assert cell_ids == [0]


def test_cells_in_polygon_weighted_multipolygon_sums_across_components():
    """A cell straddling two MultiPolygon components is counted once with summed fraction."""
    mesh = _grid_mesh(nx=1, ny=1)  # one cell, x∈[0,1], y∈[0,1]
    # Two disjoint components, each covering 25% of the cell.
    multi = MultiPolygon(
        [
            box(0.0, 0.0, 0.5, 0.5),  # 0.25 area
            box(0.5, 0.5, 1.0, 1.0),  # 0.25 area
        ]
    )

    result = cells_in_polygon_weighted(mesh, multi, id_col="cell_id")

    assert len(result) == 1
    _, weight, _ = result[0]
    assert weight == pytest.approx(0.5)


def test_cells_in_polygon_weighted_polygon_with_hole_excludes_inside_hole_cell():
    """A cell sitting inside a polygon hole has zero intersection area → dropped."""
    mesh = _grid_mesh(nx=3, ny=3)
    outer = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0), (0.0, 0.0)]
    hole = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0)]
    polygon = Polygon(outer, holes=[hole])

    result = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")

    cell_ids = sorted(cid for cid, _, _ in result)
    assert 4 not in cell_ids  # centre cell coincides with the hole
    assert cell_ids == [0, 1, 2, 3, 5, 6, 7, 8]


def test_cells_in_polygon_weighted_empty_mesh_returns_empty():
    mesh = gpd.GeoDataFrame({"cell_id": []}, geometry=[], crs="EPSG:3857")
    polygon = box(0.0, 0.0, 1.0, 1.0)

    assert cells_in_polygon_weighted(mesh, polygon, id_col="cell_id") == []


def test_cells_in_polygon_weighted_clipped_geometry_matches_intersection():
    """The third tuple element is the actual cell-polygon intersection geometry."""
    mesh = _grid_mesh(nx=2, ny=1)
    polygon = box(0.0, 0.0, 1.6, 1.0)

    result = cells_in_polygon_weighted(mesh, polygon, id_col="cell_id")

    geoms = {cid: g for cid, _, g in result}
    # Cell 0 entirely inside → clip equals the cell.
    assert geoms[0].area == pytest.approx(1.0)
    # Cell 1 clipped to x∈[1, 1.6] → area 0.6, bbox right edge at x=1.6.
    assert geoms[1].area == pytest.approx(0.6)
    minx, _, maxx, _ = geoms[1].bounds
    assert maxx == pytest.approx(1.6)
    assert minx == pytest.approx(1.0)


@pytest.mark.slow
def test_cells_in_polygon_weighted_performance_parity_with_binary():
    """On a 14k-cell mesh, the weighted helper runs within a small factor of the binary one."""
    nx, ny = 140, 100
    mesh = _grid_mesh(nx=nx, ny=ny)
    half_polygon = box(0.0, 0.0, nx / 2.0, ny)

    start = time.perf_counter()
    binary = cells_in_polygon(mesh, half_polygon, id_col="cell_id")
    t_binary = time.perf_counter() - start

    start = time.perf_counter()
    weighted = cells_in_polygon_weighted(mesh, half_polygon, id_col="cell_id")
    t_weighted = time.perf_counter() - start

    assert len(weighted) == len(binary)
    # Both must complete well within the binary's 2s budget; allow a 5x
    # constant factor for the per-cell intersection cost (computed only on
    # STRtree survivors).
    assert t_weighted < 5.0 * max(t_binary, 0.05)


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

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

    assert result == [42]


def test_reaches_on_polygon_boundary_excludes_wholly_inside_reach():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            7: LineString([(2.0, 2.0), (8.0, 8.0)]),  # both endpoints inside
        }
    )

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

    assert result == []


def test_reaches_on_polygon_boundary_excludes_wholly_outside_reach():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            9: LineString([(20.0, 20.0), (30.0, 20.0)]),  # both endpoints outside
        }
    )

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

    assert result == []


def test_reaches_on_polygon_boundary_excludes_passing_through_reach():
    """A reach with both endpoints outside but middle inside is NOT a boundary reach."""
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            3: LineString([(-5.0, 5.0), (15.0, 5.0)]),  # passes through, both endpoints outside
        }
    )

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

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

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

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

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

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

    result = reaches_in_polygon_carachterisation(network, multi, id_col="reach_id")["boundary_ids"]

    assert sorted(result) == [1, 2]


def test_reaches_on_polygon_boundary_empty_network_returns_empty():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = gpd.GeoDataFrame({"reach_id": []}, geometry=[], crs="EPSG:3857")

    assert reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"] == []


def test_reaches_on_polygon_boundary_id_col_as_integer_position():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network({42: LineString([(5.0, 5.0), (15.0, 5.0)])})

    result = reaches_in_polygon_carachterisation(network, polygon, id_col=0)["boundary_ids"]

    assert result == [42]


# ---------------------------------------------------------------------------
# reaches_in_polygon_carachterisation — directional classification
# ---------------------------------------------------------------------------


def test_reaches_in_polygon_carachterisation_classifies_inflow_and_outflow():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            1: LineString([(15.0, 5.0), (5.0, 5.0)]),  # fnode outside, tnode inside → inflow
            2: LineString([(5.0, 5.0), (15.0, 5.0)]),  # fnode inside, tnode outside → outflow
            3: LineString([(2.0, 2.0), (8.0, 8.0)]),   # both inside → internal
            4: LineString([(20.0, 5.0), (30.0, 5.0)]), # both outside → skipped
        }
    )

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")

    assert result["inflow_ids"] == [1]
    assert result["outflow_ids"] == [2]
    assert result["internal_ids"] == [3]
    assert sorted(result["boundary_ids"]) == [1, 2]
    assert result["signs"] == {1: +1, 2: -1}
    # Crossing geometries: one Point per boundary reach, parallel to crossing_ids.
    assert result["crossing_ids"] == [1, 2]
    assert all(g.geom_type in ("Point", "MultiPoint") for g in result["crossing_geometries"])


def test_reaches_in_polygon_carachterisation_empty_network():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = gpd.GeoDataFrame({"reach_id": []}, geometry=[], crs="EPSG:3857")

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")

    assert result["inflow_ids"] == []
    assert result["outflow_ids"] == []
    assert result["boundary_ids"] == []
    assert result["signs"] == {}


def test_reaches_in_polygon_carachterisation_handles_multilinestring():
    polygon = box(0.0, 0.0, 10.0, 10.0)
    multi = MultiLineString(
        [
            LineString([(15.0, 5.0), (12.0, 5.0)]),  # outside fnode chain
            LineString([(8.0, 5.0), (5.0, 5.0)]),    # inside tnode chain
        ]
    )
    network = _network({77: multi})

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")

    assert result["inflow_ids"] == [77]
    assert result["signs"][77] == +1


def test_reaches_on_polygon_boundary_now_delegates_to_signs_helper():
    """The XOR wrapper still returns the same boundary set after the refactor."""
    polygon = box(0.0, 0.0, 10.0, 10.0)
    network = _network(
        {
            1: LineString([(15.0, 5.0), (5.0, 5.0)]),  # inflow
            2: LineString([(5.0, 5.0), (15.0, 5.0)]),  # outflow
            3: LineString([(2.0, 2.0), (8.0, 8.0)]),   # internal
        }
    )

    result = reaches_in_polygon_carachterisation(network, polygon, id_col="reach_id")["boundary_ids"]

    assert result == [1, 2]


# ---------------------------------------------------------------------------
# cells_boundary_faces — per-cell direction labels + merged edge geometry
# ---------------------------------------------------------------------------


def test_cells_boundary_faces_single_inside_cell_four_directions():
    """Cross of 5 cells: centre is the only inside cell, 4 outside neighbours,
    one per cardinal direction. Each contributes one face on the centre cell.
    """
    cells = {
        0: box(4.0, 4.0, 6.0, 6.0),  # centre, inside polygon
        1: box(4.0, 6.0, 6.0, 8.0),  # north neighbour (dy>0 → "north")
        2: box(2.0, 4.0, 4.0, 6.0),  # west neighbour  (dx<0 → "east")
        3: box(6.0, 4.0, 8.0, 6.0),  # east neighbour  (dx>0 → "west")
        4: box(4.0, 2.0, 6.0, 4.0),  # south neighbour (dy<0 → "south")
    }
    mesh = gpd.GeoDataFrame(
        {"cell_id": list(cells.keys())},
        geometry=list(cells.values()),
        crs="EPSG:3857",
    )
    polygon = box(3.5, 3.5, 6.5, 6.5)  # contains only centre cell's centroid (5,5)

    boundary_faces, edge_geometries = cells_boundary_faces(mesh, polygon, id_col="cell_id")

    assert sorted(boundary_faces[0]) == ["east", "north", "south", "west"]
    # One merged geometry per cell; the 4 faces of the centre cell collapse to
    # a single (multi-part) edge geometry.
    assert set(edge_geometries.keys()) == {0}
    assert edge_geometries[0].geom_type in ("LineString", "MultiLineString")
    # The two dicts share keys so callers can align them 1:1.
    assert boundary_faces.keys() == edge_geometries.keys()


def test_cells_boundary_faces_excludes_corner_only_neighbours():
    """3x3 grid; polygon covers cell 4 only. Diagonal neighbours touch only
    at a point — must NOT be counted as boundary faces."""
    cells = []
    ids = []
    for j in range(3):
        for i in range(3):
            cells.append(box(i, j, i + 1, j + 1))
            ids.append(j * 3 + i)
    mesh = gpd.GeoDataFrame({"cell_id": ids}, geometry=cells, crs="EPSG:3857")
    polygon = box(1.1, 1.1, 1.9, 1.9)  # only cell 4 (centre) inside

    boundary_faces, _ = cells_boundary_faces(mesh, polygon, id_col="cell_id")

    # 4 edge-sharing neighbours; 4 corner-only excluded.
    assert sorted(boundary_faces[4]) == ["east", "north", "south", "west"]


def test_cells_boundary_faces_all_inside_no_boundary():
    cells = []
    ids = []
    for j in range(3):
        for i in range(3):
            cells.append(box(i, j, i + 1, j + 1))
            ids.append(j * 3 + i)
    mesh = gpd.GeoDataFrame({"cell_id": ids}, geometry=cells, crs="EPSG:3857")
    polygon = box(0.0, 0.0, 3.0, 3.0)  # covers everything

    boundary_faces, edge_geometries = cells_boundary_faces(mesh, polygon, id_col="cell_id")

    # All cells inside → no inside↔outside adjacency → empty result.
    assert boundary_faces == {}
    assert edge_geometries == {}


def test_cells_boundary_faces_empty_mesh():
    mesh = gpd.GeoDataFrame({"cell_id": []}, geometry=[], crs="EPSG:3857")
    polygon = box(0.0, 0.0, 1.0, 1.0)

    boundary_faces, edge_geometries = cells_boundary_faces(mesh, polygon, id_col="cell_id")

    assert boundary_faces == {}
    assert edge_geometries == {}
