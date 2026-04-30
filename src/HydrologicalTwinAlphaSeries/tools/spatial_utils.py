import os
from typing import Any, Dict, List, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from shapely.ops import unary_union

sep = os.sep


class SpatialIndex:
    """
    Cached spatial index for efficient nearest neighbor queries.

    Build the KDTree once and reuse it for multiple queries.
    """

    def __init__(self, gdf: gpd.GeoDataFrame):
        """
        Initialize spatial index from a GeoDataFrame.

        :param gdf: GeoDataFrame to index
        :type gdf: gpd.GeoDataFrame
        """
        self.gdf = gdf
        self._tree = None
        self._centroids = None

        if not gdf.empty:
            self._centroids = np.array([[g.centroid.x, g.centroid.y] for g in gdf.geometry])
            self._tree = cKDTree(self._centroids)

    def get_nearest_idx(self, point_geom: shapely.Point) -> Union[int, None]:
        """
        Get the index of the nearest feature to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :return: Index into the GeoDataFrame of the nearest feature
        :rtype: Union[int, None]
        """
        if self._tree is None:
            return None

        query_point = np.array([[point_geom.centroid.x, point_geom.centroid.y]])
        _, idx = self._tree.query(query_point, k=1)
        return idx[0]

    def get_nearest_cell_id(
        self, point_geom: shapely.Point, id_col: Union[str, int]
    ) -> Union[int, None]:
        """
        Get the cell ID of the nearest feature to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :param id_col: Column name or index for the cell ID
        :type id_col: Union[str, int]
        :return: ID of the nearest cell
        :rtype: Union[int, None]
        """
        idx = self.get_nearest_idx(point_geom)
        if idx is None:
            return None

        # Resolve column name if given as index
        if isinstance(id_col, int):
            id_col = self.gdf.columns[id_col]

        return self.gdf.iloc[idx][id_col]

    def get_nearest_row(self, point_geom: shapely.Point) -> Union[pd.Series, None]:
        """
        Get the full row of the nearest feature to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :return: Row from GeoDataFrame of the nearest feature
        :rtype: Union[pd.Series, None]
        """
        idx = self.get_nearest_idx(point_geom)
        if idx is None:
            return None
        return self.gdf.iloc[idx]

# Cache for spatial indices (key: id(gdf))
_spatial_index_cache: Dict[int, SpatialIndex] = {}


def get_spatial_index(gdf: gpd.GeoDataFrame) -> SpatialIndex:
    """
    Get or create a cached spatial index for a GeoDataFrame.

    :param gdf: GeoDataFrame to index
    :type gdf: gpd.GeoDataFrame
    :return: Cached SpatialIndex for the GeoDataFrame
    :rtype: SpatialIndex
    """
    gdf_id = id(gdf)
    if gdf_id not in _spatial_index_cache:
        _spatial_index_cache[gdf_id] = SpatialIndex(gdf)
    return _spatial_index_cache[gdf_id]


def get_nearest_cell(
    point_geom: shapely.Point,
    mesh_gdf: gpd.GeoDataFrame,
    id_col: Union[str, int]
) -> Union[int, None]:
    """
    Find the nearest cell to a point using cached spatial index.

    :param point_geom: Geometry of the point to search from
    :type point_geom: shapely.Point
    :param mesh_gdf: GeoDataFrame containing mesh cells
    :type mesh_gdf: gpd.GeoDataFrame
    :param id_col: Column name or index for the cell ID
    :type id_col: Union[str, int]
    :return: ID of the nearest cell, or None if mesh is empty
    :rtype: Union[int, None]
    """
    spatial_idx = get_spatial_index(mesh_gdf)
    return spatial_idx.get_nearest_cell_id(point_geom, id_col)


def get_nearest_row(
    point_geom: shapely.Point,
    gdf: gpd.GeoDataFrame
) -> Union[pd.Series, None]:
    """
    Find the nearest feature row to a point using cached spatial index.

    :param point_geom: Geometry of the point to search from
    :type point_geom: shapely.Point
    :param gdf: GeoDataFrame to search
    :type gdf: gpd.GeoDataFrame
    :return: Row of the nearest feature, or None if empty
    :rtype: Union[pd.Series, None]
    """
    spatial_idx = get_spatial_index(gdf)
    return spatial_idx.get_nearest_row(point_geom)


def read_hyd_corresp_file(out_caw_directory: str) -> pd.DataFrame:
    """
    Read the hydraulic correspondence file.

    :param out_caw_directory: Directory where the CaWaQS output files are stored
    :type out_caw_directory: str
    :return: DataFrame containing the correspondence data
    :rtype: pd.DataFrame
    :raises FileNotFoundError: If the correspondence file is not found
    """
    print(f"reading hyd corresp file : {out_caw_directory}")
    corresp_file_path = out_caw_directory + sep + "HYD_corresp_file.txt"
    if not os.path.isfile(corresp_file_path):
        raise FileNotFoundError(
            f"File {corresp_file_path} not found. "
            "Check your CaWaQS command file: either you didn't request any HYDraulic outputs "
            "(nor discharge, nor water depth) or you requested FORMATTED results that "
            "CaWaQS-Viz doesn't handle yet. In the former case, request UNFORMATTED outputs."
        )

    corr = pd.read_csv(corresp_file_path, index_col=2, sep=r"\s+")
    return corr


def combine_geometries(geometries: List[shapely.Geometry]) -> shapely.Geometry:
    """
    Merge multiple geometries into a single geometry.

    This replaces the QGIS-dependent combineGeometries function.

    :param geometries: List of shapely geometries to merge
    :type geometries: List[shapely.Geometry]
    :return: Merged geometry
    :rtype: shapely.Geometry
    """
    return unary_union(geometries)


class CRSMismatchError(ValueError):
    """Raised by verify_crs_match when two defined CRS are incompatible.

    Inherits from ValueError for backwards compatibility, but is a distinct
    type so callers can catch it without accidentally swallowing unrelated
    ValueError exceptions (e.g. from rendering libraries).
    """


def verify_crs_match(crs_a, crs_b, context: str = "") -> None:
    """
    Raise CRSMismatchError if two CRS values are defined and incompatible.

    Passes silently when either CRS is None (undetermined — cannot verify).
    Raises with a descriptive message when both are defined but differ.

    Backend spatial operations that join two datasets MUST call this before
    the join so that CRS mismatches surface as explicit errors rather than
    silently wrong spatial results.

    :param crs_a: First CRS (pyproj.CRS, EPSG string, or None)
    :param crs_b: Second CRS (pyproj.CRS, EPSG string, or None)
    :param context: Operation name included in the error message
    :raises CRSMismatchError: If both CRS are defined and do not match
    """
    if crs_a is None or crs_b is None:
        return   # one side unknown — cannot verify, pass silently
    if crs_a != crs_b:
        ctx = f" in {context}" if context else ""
        raise CRSMismatchError(
            f"CRS mismatch{ctx}: {crs_a} vs {crs_b}. "
            "Reproject one layer to match the other before this operation."
        )


def reproject_to_match(
    gdf: gpd.GeoDataFrame,
    target_crs,
    context: str = "",
) -> gpd.GeoDataFrame:
    """
    Reproject a GeoDataFrame to a target CRS.

    Raises explicitly when the target CRS is None, because silently returning
    an un-reprojected GDF would hide the misconfiguration.

    :param gdf: GeoDataFrame to reproject
    :param target_crs: Target CRS (pyproj.CRS, EPSG string, or None)
    :param context: Operation name included in the error message
    :return: Reprojected GeoDataFrame (new object), or original if already matching
    :rtype: gpd.GeoDataFrame
    :raises ValueError: If target_crs is None
    """
    if target_crs is None:
        ctx = f" for {context}" if context else ""
        raise ValueError(
            f"Cannot reproject{ctx}: target CRS is None. "
            "The reference layer has no CRS defined."
        )
    if gdf.crs == target_crs:
        return gdf
    return gdf.to_crs(target_crs)


# ---------------------------------------------------------------------------
# Polygon-mask geometric helpers
#
# Pure functions consumed by HydrologicalTwin.mask() and reusable
# standalone (no twin instance required). See the
# ``polygon-geometry-ops`` capability spec.
# ---------------------------------------------------------------------------


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


def reaches_inflow_outflow_signs(
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
    polygons). The XOR-only :func:`reaches_on_polygon_boundary` is now a
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

    geometries = list(network_gdf.geometry.values)
    ids = list(network_gdf[col_name].values)

    for geom, cell_id in zip(geometries, ids):
        fnode, tnode = _reach_endpoints(geom)
        f_in = polygon.contains(fnode)
        t_in = polygon.contains(tnode)

        if f_in and t_in:
            internal_ids.append(cell_id)
        elif (not f_in) and t_in:
            inflow_ids.append(cell_id)
            crossing_geometries.append(geom.intersection(poly_boundary))
            crossing_ids.append(cell_id)
            signs[cell_id] = +1
        elif f_in and (not t_in):
            outflow_ids.append(cell_id)
            crossing_geometries.append(geom.intersection(poly_boundary))
            crossing_ids.append(cell_id)
            signs[cell_id] = -1
        # both outside → skip

    return {
        "inflow_ids":          inflow_ids,
        "outflow_ids":         outflow_ids,
        "internal_ids":        internal_ids,
        "boundary_ids":        inflow_ids + outflow_ids,
        "crossing_geometries": crossing_geometries,
        "crossing_ids":        crossing_ids,
        "signs":               signs,
    }


def reaches_on_polygon_boundary(
    network_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> List[Any]:
    """Return reach ids whose two endpoints straddle the polygon (sorted).

    Thin wrapper over :func:`reaches_inflow_outflow_signs`: returns the
    union of inflow + outflow ids, sorted ascending. ``polygon.contains``
    treats interior rings as outside — a reach with one endpoint inside a
    hole still qualifies as a boundary reach.

    :param network_gdf: GeoDataFrame of HYD reaches (LineString / MultiLineString)
    :param polygon: shapely ``Polygon`` or ``MultiPolygon`` defining the mask
    :param id_col: Column name (or integer position) to read reach ids from.
    :return: List of reach ids whose endpoints straddle the polygon (sorted).
    """
    classification = reaches_inflow_outflow_signs(network_gdf, polygon, id_col=id_col)
    return sorted(classification["boundary_ids"])


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
