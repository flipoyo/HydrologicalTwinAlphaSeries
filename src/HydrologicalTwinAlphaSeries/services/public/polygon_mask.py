"""Polygon-mask geometric helpers — the geometric core of ``HydrologicalTwin.mask()``.

Pure functions consumed by ``HydrologicalTwin.mask()`` and reusable
standalone (no twin instance required). They encode CaWaQS spatial
conventions (centroid-containment cell selection, area/length-fraction
weights, and flow-direction fnode/tnode reach classification), which is why
they live in ``services/`` as a domain capability rather than in ``tools/``
as generic plumbing.

These are class-free by design: each function is ``(gdf, polygon, id_col) ->
result`` with no state held between calls, so there is nothing for a class to
carry. See the ``polygon-geometry-ops`` capability spec.
"""

from typing import Any, Dict, List, Tuple, Union

import geopandas as gpd
import pandas as pd
import shapely
from shapely.ops import unary_union


def _resolve_id_col(gdf: gpd.GeoDataFrame, id_col: Union[str, int]) -> str:
    """Resolve ``id_col`` (column name or integer position) to a column name."""
    if isinstance(id_col, int):
        return gdf.columns[id_col]
    return id_col


def _polygon_components(polygon: Any) -> List[Any]:
    """Return the constituent Polygons of ``polygon`` (single Polygon or MultiPolygon)."""
    if isinstance(polygon, shapely.MultiPolygon):
        return list(polygon.geoms)
    return [polygon]


def cells_in_polygon(
    mesh_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> List[Any]:
    """Return the ids of mesh cells whose centroid lies inside ``polygon``.

    Containment uses ``polygon.contains(centroid)``, which naturally treats
    interior rings (holes) as outside — so a cell whose centroid falls inside
    a hole is excluded. ``MultiPolygon`` inputs are handled by iterating
    their components and unioning the matches.

    A Shapely STRtree on cell centroids prefilters candidates by the
    polygon's bounding box, keeping the helper fast on large meshes
    (tested up to ~14 000 cells).

    For area-fraction weighted selection (per-cell weights + clipped
    intersection geometries), see :func:`cells_in_polygon_weighted`.

    :param mesh_gdf: GeoDataFrame of mesh cells (polygon geometries)
    :param polygon: shapely ``Polygon`` or ``MultiPolygon`` defining the mask
    :param id_col: Column name (or integer position) to read cell ids from.
    :return: List of cell ids inside the polygon, in mesh-row order.
    """
    if mesh_gdf.empty:
        return []

    centroids = mesh_gdf.geometry.centroid
    tree = shapely.STRtree(list(centroids.values))

    matched_positions: set = set()
    for component in _polygon_components(polygon):
        candidate_positions = tree.query(component, predicate="intersects")
        for pos in candidate_positions:
            if component.contains(centroids.iloc[int(pos)]):
                matched_positions.add(int(pos))

    sorted_positions = sorted(matched_positions)
    col_name = _resolve_id_col(mesh_gdf, id_col)
    return [mesh_gdf.iloc[p][col_name] for p in sorted_positions]


# Hardcoded floor (dimensionless area ratio): cells with weight below this
# are considered to share only a boundary edge / vertex with the polygon
# and are dropped as floating-point grit. A meaningful contribution of
# 0.01% is weight = 1e-4, four orders of magnitude above this floor.
_WEIGHTED_MIN_WEIGHT = 1e-6


def cells_in_polygon_weighted(
    mesh_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> List[Tuple[Any, float, Any]]:
    """Return mesh cells with their area-fraction weight inside ``polygon``.

    For each cell whose *footprint* survives the polygon STRtree prefilter
    (i.e. any part of the cell overlaps the polygon — not a centroid test),
    computes ``intersection = polygon.intersection(cell)`` once and derives
    ``weight = clip(intersection.area / cell.area, 0.0, 1.0)``. Cells with
    ``weight < 1e-6`` (floor that absorbs floating-point drift from
    shared-edge / vertex-only touches) are dropped.

    ``MultiPolygon`` inputs are handled by shapely's intersection directly,
    so a cell straddling two components is counted once with the summed
    fraction. Interior rings (holes) are treated as outside, matching
    :func:`cells_in_polygon`.

    A Shapely STRtree on cell footprints prefilters candidates by the
    polygon's bounding box (unlike ``cells_in_polygon``, which indexes
    centroids because it is a centroid test). Intersection geometry is
    computed only on the small subset of survivors, so performance stays
    comparable to the binary helper on large meshes.

    The ``1e-6`` floor is intentionally not exposed as a parameter — it
    represents pure floating-point noise, not a user-tunable knob.

    :param mesh_gdf: GeoDataFrame of mesh cells (polygon geometries)
    :param polygon: shapely ``Polygon`` or ``MultiPolygon`` defining the mask
    :param id_col: Column name (or integer position) to read cell ids from.
    :return: List of ``(cell_id, weight, clipped_geometry)`` triples in
        mesh-row order. ``weight`` is in ``(0, 1]`` after the floor cut and
        clip; ``clipped_geometry`` is ``polygon.intersection(cell)``.
    """
    if mesh_gdf.empty:
        return []

    geometries = list(mesh_gdf.geometry.values)
    # Prefilter on the cell *footprints*, not their centroids: a border cell
    # is in scope if any part of it overlaps the polygon, even when its
    # centroid falls outside. (The binary `cells_in_polygon` indexes
    # centroids on purpose — it *is* a centroid test; the weighted helper
    # must not, or it silently collapses back to centroid containment.)
    tree = shapely.STRtree(geometries)

    candidate_positions: set = set()
    for component in _polygon_components(polygon):
        for pos in tree.query(component, predicate="intersects"):
            candidate_positions.add(int(pos))

    col_name = _resolve_id_col(mesh_gdf, id_col)
    results: List[Tuple[Any, float, Any]] = []
    for pos in sorted(candidate_positions):
        cell_geom = geometries[pos]
        cell_area = cell_geom.area
        if cell_area <= 0.0:
            continue
        intersection = polygon.intersection(cell_geom)
        if intersection.is_empty:
            continue
        raw_weight = intersection.area / cell_area
        weight = float(min(1.0, max(0.0, raw_weight)))
        if weight < _WEIGHTED_MIN_WEIGHT:
            continue
        results.append((mesh_gdf.iloc[pos][col_name], weight, intersection))

    return results


def _reach_endpoints(geom: Any) -> tuple:
    """Return the two extreme endpoints (start, end) of a reach geometry.

    For a ``LineString`` these are the first and last coordinates. For a
    ``MultiLineString`` we take the start of the first sub-line and the end
    of the last sub-line — i.e. the chained reach's two extreme endpoints.
    Caller-side: this is intentional for the boundary-XOR test, where what
    matters is whether the reach as a whole straddles the polygon, not
    whether each segment does.
    """
    if isinstance(geom, shapely.MultiLineString):
        sublines = list(geom.geoms)
        start = shapely.Point(sublines[0].coords[0])
        end = shapely.Point(sublines[-1].coords[-1])
        return start, end
    coords = list(geom.coords)
    return shapely.Point(coords[0]), shapely.Point(coords[-1])


def reaches_in_polygon_carachterisation(
    network_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> Dict[str, Any]:
    """Classify HYD reaches by flow direction relative to ``polygon``.

    CaWaQS digitises reaches in flow direction, so endpoint order encodes
    direction: ``geom.coords[0]`` is the upstream node (fnode), ``coords[-1]``
    is the downstream node (tnode). For ``MultiLineString``, we use the
    chained reach's two extreme nodes (start of first sub-line, end of
    last sub-line).

    Classification:
        * inflow:    fnode outside, tnode inside  → water enters sub-area  (+1)
        * outflow:   fnode inside,  tnode outside → water exits sub-area   (-1)
        * internal:  both nodes inside            → fully internal reach
        * (both outside) → silently skipped

    For each boundary reach, ``geom.intersection(polygon.boundary)`` gives
    the crossing geometry (typically a Point; MultiPoint for re-entrant
    polygons). The XOR-only :func:`reaches_in_polygon_carachterisation["boundary_ids"]` is now a
    thin wrapper over this richer helper.

    Returns a dict with keys ``inflow_ids``, ``outflow_ids``, ``internal_ids``,
    ``boundary_ids`` (= inflow + outflow), ``crossing_geometries``,
    ``crossing_ids`` (parallel to crossing_geometries), and
    ``signs`` ({cell_id: +1 or -1}).
    """
    empty: Dict[str, Any] = {
        "inflow_ids":          [],
        "outflow_ids":         [],
        "internal_ids":        [],
        "boundary_ids":        [],
        "crossing_geometries": [],
        "crossing_ids":        [],
        "signs":               {},
        "weights":             {},
        "clipped_geometries":  {},
        "internal_and_boundary_ids": [],
    }
    if network_gdf.empty:
        return empty

    col_name = _resolve_id_col(network_gdf, id_col)
    poly_boundary = polygon.boundary

    inflow_ids: List[Any] = []
    outflow_ids: List[Any] = []
    internal_ids: List[Any] = []
    crossing_geometries: List[Any] = []
    crossing_ids: List[Any] = []
    signs: Dict[Any, int] = {}
    weights: Dict[Any, float] = {}
    # Per-reach geometry clipped to the polygon — for a fully-internal reach
    # this is the whole reach; for a boundary reach it is the inside segment.
    # We always clip (nicer to display, and it is the same intersection used
    # for the length-fraction weight below).
    clipped_geometries: Dict[Any, Any] = {}

    geometries = list(network_gdf.geometry.values)
    ids = list(network_gdf[col_name].values)

    for geom, cell_id in zip(geometries, ids):
        fnode, tnode = _reach_endpoints(geom)
        f_in = polygon.contains(fnode)
        t_in = polygon.contains(tnode)

        if not (f_in or t_in):
            continue  # both outside → reach not in the masked area

        # The inside portion of the reach: polygon ∩ reach. Computed once and
        # reused for the clipped geometry AND the length-fraction weight
        # (= inside length / total length), mirroring the area-fraction logic
        # in cells_in_polygon_weighted.
        inside_part = polygon.intersection(geom)
        total_length = geom.length
        weights[cell_id] = (
            inside_part.length / total_length if total_length > 0 else 0.0
        )
        clipped_geometries[cell_id] = inside_part

        if f_in and t_in:
            internal_ids.append(cell_id)
        elif (not f_in) and t_in:
            inflow_ids.append(cell_id)
            crossing_geometries.append(geom.intersection(poly_boundary))
            crossing_ids.append(cell_id)
            signs[cell_id] = +1
        else:  # f_in and not t_in
            outflow_ids.append(cell_id)
            crossing_geometries.append(geom.intersection(poly_boundary))
            crossing_ids.append(cell_id)
            signs[cell_id] = -1

    boundary_ids = sorted(inflow_ids + outflow_ids)
    internal_and_boundary_ids = sorted(internal_ids + boundary_ids)

    return {
        "inflow_ids":          inflow_ids,
        "outflow_ids":         outflow_ids,
        "internal_ids":        internal_ids,
        "boundary_ids":        boundary_ids,
        "crossing_geometries": crossing_geometries,
        "crossing_ids":        crossing_ids,
        "signs":               signs,
        "weights":             weights,
        "clipped_geometries":  clipped_geometries,
        "internal_and_boundary_ids": internal_and_boundary_ids,
    }


def aq_cells_on_polygon_boundary(
    aq_mesh_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> tuple:
    """Return AQ-mesh boundary edges separating inside-polygon cells from outside.

    A boundary edge is a cell edge that connects a cell INSIDE the polygon to
    a cell OUTSIDE the polygon (topological boundary of the masked AQ region —
    NOT the geometric intersection with ``polygon.exterior``). "Inside" is
    determined by centroid containment, same convention as
    :func:`cells_in_polygon`; ``polygon.contains(centroid)`` treats interior
    rings as outside, so cells in holes count as outside neighbours and
    contribute boundary edges as expected.

    Returns a tuple ``(cell_ids, edge_geometries)`` aligned per boundary edge:
    for each (inside cell, outside cell) adjacency, one entry is appended
    where ``cell_ids[i]`` is the inside-polygon cell's id and
    ``edge_geometries[i]`` is the shared-edge geometry. An inside cell with
    N outside neighbours contributes N entries.

    Adjacency is computed from shared geometry edges via Shapely's
    ``predicate="touches"`` STRtree query, then filtered to keep only
    intersections that are LineString / MultiLineString (true edge-sharing,
    excluding corner-only adjacency).

    :param aq_mesh_gdf: GeoDataFrame of aquifer cells (polygon geometries)
    :param polygon: shapely ``Polygon`` or ``MultiPolygon`` defining the mask
    :param id_col: Column name (or integer position) to read cell ids from.
    :return: ``(cell_ids, edge_geometries)`` aligned per boundary edge.
    """
    if aq_mesh_gdf.empty:
        return [], []

    geometries = list(aq_mesh_gdf.geometry.values)
    centroids = aq_mesh_gdf.geometry.centroid
    inside_mask = [bool(polygon.contains(centroids.iloc[i])) for i in range(len(geometries))]
    inside_positions = {i for i, inside in enumerate(inside_mask) if inside}

    if not inside_positions:
        return [], []

    tree = shapely.STRtree(geometries)
    col_name = _resolve_id_col(aq_mesh_gdf, id_col)

    cell_ids_out: List[Any] = []
    edge_geometries_out: List[Any] = []
    for inside_pos in sorted(inside_positions):
        cell_geom = geometries[inside_pos]
        candidate_positions = tree.query(cell_geom, predicate="touches")
        for cand_pos in candidate_positions:
            cand_int = int(cand_pos)
            if cand_int == inside_pos or cand_int in inside_positions:
                continue
            shared = cell_geom.intersection(geometries[cand_int])
            if shared.geom_type in ("LineString", "MultiLineString"):
                cell_ids_out.append(aq_mesh_gdf.iloc[inside_pos][col_name])
                edge_geometries_out.append(shared)

    return cell_ids_out, edge_geometries_out


def aq_cells_boundary_faces(
    aq_mesh_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> Dict[str, Any]:
    """Identify boundary AQ cells with cardinal-direction face labels.

    A boundary cell is an interior cell (centroid inside the polygon) that
    shares a face with an outside cell. The face direction is determined
    from the centroid offset between the boundary cell and its outside
    neighbour: if ``|dx| ≥ |dy|`` then ``"east" if dx < 0 else "west"``,
    else ``"south" if dy < 0 else "north"``. Corner-touching neighbours
    (intersection is a Point) are filtered out — only true edge-sharing
    counts as a flux face. Direction labelling preserves the original
    feature-branch convention (cf. branch_migration/backend_50.patch L327-333).

    Returns a dict with keys:
        * ``interior_ids``:    sorted list of all cells with centroid inside
        * ``boundary_ids``:    sorted list of cell ids touching ≥1 outside cell
        * ``boundary_faces``:  ``{cell_id: ["east"|"west"|"south"|"north", ...]}``
        * ``edges_by_face``:   ``{cell_id: {direction: shapely.Geometry}}``
                               (per-face union of shared boundary parts)
    """
    empty: Dict[str, Any] = {
        "interior_ids":   [],
        "boundary_ids":   [],
        "boundary_faces": {},
        "edges_by_face":  {},
    }
    if aq_mesh_gdf.empty:
        return empty

    col_name = _resolve_id_col(aq_mesh_gdf, id_col)
    geometries = list(aq_mesh_gdf.geometry.values)
    centroids = aq_mesh_gdf.geometry.centroid
    ids = list(aq_mesh_gdf[col_name].values)

    inside_mask = [bool(polygon.contains(centroids.iloc[i])) for i in range(len(geometries))]
    interior_positions = [i for i, x in enumerate(inside_mask) if x]
    interior_ids = sorted([ids[i] for i in interior_positions])

    if not interior_ids:
        return empty

    outside_set = {ids[i] for i, x in enumerate(inside_mask) if not x}
    tree = shapely.STRtree(geometries)

    boundary_faces: Dict[Any, List[str]] = {}
    edges_by_face_parts: Dict[Any, Dict[str, List[Any]]] = {}

    for inside_pos in interior_positions:
        cell_id = ids[inside_pos]
        cell_geom = geometries[inside_pos]
        cell_cx = cell_geom.centroid.x
        cell_cy = cell_geom.centroid.y

        candidate_positions = tree.query(cell_geom, predicate="touches")
        for cand_pos in candidate_positions:
            cand_int = int(cand_pos)
            if cand_int == inside_pos:
                continue
            neigh_id = ids[cand_int]
            if neigh_id not in outside_set:
                continue
            neigh_geom = geometries[cand_int]

            shared = cell_geom.boundary.intersection(neigh_geom.boundary)
            if shared.is_empty or shared.geom_type == "Point":
                continue

            dx = neigh_geom.centroid.x - cell_cx
            dy = neigh_geom.centroid.y - cell_cy
            if abs(dx) >= abs(dy):
                face = "east" if dx < 0 else "west"
            else:
                face = "south" if dy < 0 else "north"

            boundary_faces.setdefault(cell_id, []).append(face)
            edges_by_face_parts.setdefault(cell_id, {}).setdefault(face, []).append(shared)

    boundary_ids = sorted(boundary_faces.keys())
    edges_by_face = {
        cell_id: {face: unary_union(parts) for face, parts in dir_parts.items()}
        for cell_id, dir_parts in edges_by_face_parts.items()
    }

    return {
        "interior_ids":   interior_ids,
        "boundary_ids":   boundary_ids,
        "boundary_faces": boundary_faces,
        "edges_by_face":  edges_by_face,
    }
