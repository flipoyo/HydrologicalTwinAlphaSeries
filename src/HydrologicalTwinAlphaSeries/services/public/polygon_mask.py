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
import shapely
from shapely.ops import unary_union


def _as_linestrings(geom: Any) -> List[Any]:
    """Flatten a ``LineString`` / ``MultiLineString`` into a list of LineStrings.

    A per-side merged edge is normally a single ``LineString``; if a side could
    not be fully fused it stays a ``MultiLineString`` and we keep each part, so
    the cell's collected ``MultiLineString`` carries every sub-line.
    """
    if isinstance(geom, shapely.MultiLineString):
        return list(geom.geoms)
    return [geom]


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
        "clipped_geometries":  clipped_geometries,
        "internal_and_boundary_ids": internal_and_boundary_ids,
    }



# --- Shared-face detection thresholds (see Decision 3/4 of the design) -------
#
# The two thresholds below live at *different scales on purpose*, because they
# guard against two unrelated things:
#
#   * ``_FACE_BUFFER_EPS`` (the LOWER guard) is the buffer half-width used to
#     grow each cell before intersecting. It only has to bridge the sub-metre
#     geometric misalignment of a rotated / off-grid mesh, so it is a small
#     fixed length set by *float/rotation drift* — NOT by cell size. A genuine
#     shared edge of length ``L`` then overlaps in a thin ribbon of area
#     ``≈ 2·ε·L``; a corner-only touch overlaps in a tiny ``≈ (2ε)²`` nub.
#   * the minimum-face-length **floor** (the UPPER guard) is what separates a
#     real face from that corner nub. It must sit *above* the nub yet *below*
#     the smallest real face — and the smallest real face is the smallest cell
#     side, which is set by the *mesh*, not by ε. A single hard-coded constant
#     cannot track it across meshes (3C faces ≈ 2000 m, 8C CRAIE faces ≈ 100 m),
#     so the floor is derived per-mesh in ``_mesh_face_floor`` below.
#
# Keeping the two at separate scales is the whole fix: the predecessor conflated
# them into one 1 mm common-grid snap, which could bridge float drift but could
# not also serve as a real-face threshold on a rotated mesh.
_FACE_BUFFER_EPS = 0.05  # m — buffer half-width; lower guard, set by drift not mesh
_FACE_LENGTH_FRAC = 0.10  # floor as a fraction of the smallest cell side
_FACE_NUB_CLAMP = 10  # floor lower bound as a multiple of ε (keeps floor ≫ nub)

# Snap grid (CRS units) applied ONLY when fusing one side's recovered sub-edges
# into a single line. Clipping the smaller cell's boundary to the ε-buffered
# ribbon over-captures by ≈ 2ε at each end (a tiny backward perpendicular stub),
# so two collinear same-side sub-edges of a refinement T-junction *overlap* and
# branch instead of touching end-to-end — and plain ``line_merge`` cannot fuse
# overlapping/branched lines into one ``LineString``. Snapping the per-side union
# to 2ε collapses those stubs and overlaps so the side fuses cleanly. It is tied
# to the buffer scale (NOT the mesh), unlike the retired ``_FACE_SNAP_GRID``
# which tried — and failed — to also serve as the shared-edge detector.
_FACE_MERGE_SNAP = 2.0 * _FACE_BUFFER_EPS


def _mesh_face_floor(aq_mesh_gdf: gpd.GeoDataFrame) -> float:
    """Derive the minimum-face-length floor once for the whole mesh.

    The floor must lie between two scales set by *different* things: its lower
    bound is the buffer-induced corner nub (``≈ 2ε``, driven by ε), its upper
    bound is the smallest real face (= the smallest cell side, driven by the
    mesh). It is computed as::

        side  = p1( sqrt(cell_area) )            # robust smallest cell side
        floor = max(_FACE_LENGTH_FRAC * side, _FACE_NUB_CLAMP * _FACE_BUFFER_EPS)

    * ``sqrt(area)`` is used as the cell "side", **not** the bounding-box
      extent: on the rotated 3C mesh the bbox width is inflated by the tilt
      (2015 m for a true ~1999 m side), whereas ``sqrt(area)`` is rotation-
      invariant and recovers the real side — which matters precisely because
      rotation is the root cause being fixed.
    * the **1st percentile** (not strict ``min``) is robust to a single sliver
      or degenerate cell in a future shapefile, which would otherwise crater
      ``min(side)`` and pull the floor down toward the nub.
    * the ``max(..., _FACE_NUB_CLAMP * ε)`` clamp guarantees the floor never
      approaches the corner nub even on an arbitrarily fine mesh
      (``floor ≥ 0.5 m ≫ 2ε = 0.1 m`` always).

    Measured floors that validated these constants: 3C ≈ 200 m, 8C ALLUVIONS
    ≈ 20 m, 8C CRAIE ≈ 10 m — each ~100–200× above the nub and ~10× below the
    smallest real face on that mesh, i.e. ~10× headroom both ways. Use those as
    the reference point when tuning ``_FACE_LENGTH_FRAC``.
    """
    areas = aq_mesh_gdf.geometry.area
    side = float(areas.pow(0.5).quantile(0.01))
    return max(_FACE_LENGTH_FRAC * side, _FACE_NUB_CLAMP * _FACE_BUFFER_EPS)


def _shared_face(cell_geom: Any, neigh_geom: Any, eps: float, floor: float) -> Tuple[float, Any]:
    """Detect the shared flux face of two cells and recover its line geometry.

    Robust to rotated / off-grid meshes, where the smaller cell's shared-edge
    endpoints fall mid-edge on the larger cell (not on a shared vertex), so the
    classic ``boundary ∩ boundary`` collapses to points and drops the face.

    Instead each cell is grown outward by ``eps`` (``mitre`` join, so the ribbon
    ends stay square and short faces measure correctly) and the polygons are
    intersected: a genuine shared edge of length ``L`` overlaps in a thin ribbon
    of area ``≈ 2·ε·L``, a corner-only touch in a ``≈ (2ε)²`` nub. Overlaps below
    ``eps * floor`` (i.e. a recovered length below ``≈ floor / 2``) are rejected
    as nubs. The face line is recovered by clipping the **smaller** cell's
    boundary to the ribbon and line-merging — the smaller cell is chosen because
    its edge *is* the full face, whereas the larger cell's edge spans several
    small neighbours and would over-capture.

    :return: ``(length, line)`` — the recovered face length and its merged
        ``LineString`` / ``MultiLineString``, or ``(0.0, None)`` for a nub.
    """
    strip = cell_geom.buffer(eps, join_style="mitre").intersection(
        neigh_geom.buffer(eps, join_style="mitre")
    )
    if strip.is_empty or strip.area < eps * floor:
        return 0.0, None
    smaller = cell_geom if cell_geom.area <= neigh_geom.area else neigh_geom
    line = shapely.line_merge(smaller.boundary.intersection(strip))
    if line.is_empty:
        return 0.0, None
    return line.length, line


def cells_boundary_faces(
    aq_mesh_gdf: gpd.GeoDataFrame,
    polygon: Any,
    id_col: Union[str, int],
) -> Tuple[Dict[Any, List[str]], Dict[Any, Any], Dict[Any, Dict[str, Dict[str, Any]]]]:
    """Identify boundary cells with cardinal-direction face labels.

    A boundary cell is an interior cell (centroid inside the polygon) that
    shares a face with an outside cell. The face direction is determined
    from the centroid offset between the boundary cell and its outside
    neighbour: if ``|dx| ≥ |dy|`` then ``"east" if dx < 0 else "west"``,
    else ``"south" if dy < 0 else "north"``. Direction labelling preserves
    the original feature-branch convention (cf.
    branch_migration/backend_50.patch L327-333).

    **Shared-face detection (robust on rotated / off-grid meshes).** Two cells
    share a flux face IFF, after growing each by a small outward buffer ``ε``,
    their polygons overlap in a thin ribbon (see :func:`_shared_face`). The face
    line is recovered by clipping the *smaller* cell's boundary to that ribbon.
    This does NOT require the shared edge's endpoints to be vertices of both
    cells, so it recovers refinement T-junction faces (where the small cell's
    endpoints fall mid-edge on the large cell) that the old
    ``boundary ∩ boundary`` test dropped as zero-length points.

    Two thresholds at two scales separate a real face from a corner touch:
    ``ε`` (``_FACE_BUFFER_EPS``, the lower guard — only bridges sub-metre
    rotation/coordinate drift) and a minimum-face-length **floor** (the upper
    guard, derived per-mesh by :func:`_mesh_face_floor` from a low percentile of
    ``sqrt(cell_area)``, so it scales with the mesh and stays well above the
    corner nub). A corner-only touch falls below the floor and is rejected; a
    real face of any orientation is kept.

    **Per-face flux source (refined-mesh coarse-cell correction).** CaWaQS stores
    exactly one finite-difference flux per cardinal face per cell, so a coarse
    inside cell's single side-flux is the *blended* net over every neighbour on
    that side. The third return value, ``face_sources``, tells a downstream flux
    read where to source each face: for a side where the inside cell is
    smaller-or-equal to its outside neighbour(s) the inside cell's own face is a
    clean single-sub-face value (``sign=+1``, ``INT_cell``); for a side where the
    inside cell is *strictly coarser* the own face is a blend and must instead be
    read from the smaller outside neighbours' opposing faces (``sign=-1``,
    ``EXT_cell``, ``outside_ids`` = those smaller outside cells). Ties resolve to
    the inside cell (``+1``). The size comparison reuses the same
    ``cell_geom.area`` vs ``neigh_geom.area`` test :func:`_shared_face` already
    performs. Only ``outside_set`` cells (centroid-outside) are candidates here,
    so a smaller *inside* neighbour on the same side never enters ``outside_ids``.

    :param aq_mesh_gdf: GeoDataFrame of aquifer mesh cells (polygon geometries)
    :param polygon: shapely ``Polygon`` or ``MultiPolygon`` defining the mask
    :param id_col: Column name (or integer position) to read cell ids from.
    :return: ``(boundary_faces, edge_geometries, face_sources)`` where
        ``boundary_faces`` is ``{cell_id: ["east"|"west"|"south"|"north", ...]}``
        — one entry per boundary cell, each value the list of flux-face
        directions for that cell (a corner cell can have two faces) —
        ``edge_geometries`` is ``{cell_id: geometry}``, the shared face edge(s)
        for that cell merged into a single geometry, and ``face_sources`` is
        ``{cell_id: {direction: {"sign": +1|-1, "outside_ids": [id, ...]}}}``,
        the per-(cell, direction) flux-source map described above. Collinear
        sub-edges on one side (a refinement T-junction, where several smaller
        outside cells abut one side) fuse into a single continuous
        ``LineString``; a corner cell bordering two perpendicular sides stays a
        ``MultiLineString`` with one line per side. All three dicts share the
        same keys so callers can align them 1:1.
    """
    if aq_mesh_gdf.empty:
        return {}, {}, {}

    col_name = _resolve_id_col(aq_mesh_gdf, id_col)
    geometries = list(aq_mesh_gdf.geometry.values)
    centroids = aq_mesh_gdf.geometry.centroid
    ids = list(aq_mesh_gdf[col_name].values)

    inside_mask = [bool(polygon.contains(centroids.iloc[i])) for i in range(len(geometries))]
    interior_positions = [i for i, x in enumerate(inside_mask) if x]

    if not interior_positions:
        return {}, {}, {}

    outside_set = {ids[i] for i, x in enumerate(inside_mask) if not x}
    tree = shapely.STRtree(geometries)

    # Minimum-face-length floor, derived once from the whole mesh (not per pair):
    # it must scale with the mesh's smallest real face while staying well above
    # the buffer-induced corner nub. See _mesh_face_floor.
    face_floor = _mesh_face_floor(aq_mesh_gdf)

    # Per-cell ordered set of bordered cardinal directions (each direction at
    # most once — a refined cell with several same-side neighbours still borders
    # that side once). Insertion order is preserved so face_directions is stable.
    boundary_faces: Dict[Any, List[str]] = {}
    # Shared sub-edges grouped by (cell_id, direction). Grouping by direction is
    # what keeps the per-side merge correct: all sub-edges of one side are
    # collinear and fuse to one line, while two *perpendicular* sides of a corner
    # cell stay separate (they must NOT fuse, even though they touch at the shared
    # corner vertex — see the merge step below).
    edge_parts: Dict[Tuple[Any, str], List[Any]] = {}
    # Per-(cell_id, direction) flux source. ``sign`` starts +1 (INT_cell: read the
    # inside cell's own face) and flips to -1 the moment a *strictly smaller*
    # outside neighbour is seen on that side (EXT_cell: the inside cell is coarser,
    # so its own face is a blend and must be sourced from the smaller outside
    # neighbours' opposing faces). ``outside_ids`` collects exactly those smaller
    # outside neighbours. All outside sub-cells on a refined side are smaller
    # together, so any one strict-smaller test classifies the side; equal-size or
    # coarser outside neighbours leave the side INT_cell (ties → inside, D1).
    face_source_parts: Dict[Tuple[Any, str], Dict[str, Any]] = {}

    for inside_pos in interior_positions:
        cell_id = ids[inside_pos]
        cell_geom = geometries[inside_pos]
        cell_cx = cell_geom.centroid.x
        cell_cy = cell_geom.centroid.y

        candidate_positions = tree.query(cell_geom, predicate="intersects")
        for cand_pos in candidate_positions:
            cand_int = int(cand_pos)
            if cand_int == inside_pos:
                continue
            neigh_id = ids[cand_int]
            if neigh_id not in outside_set:
                continue
            neigh_geom = geometries[cand_int]

            # The flux face is the segment the two cells share. Detect it by the
            # area overlap of the two cells grown by ε and recover the line from
            # the smaller cell's boundary (see _shared_face): robust to rotation
            # and off-grid coordinates, where the small cell's endpoints fall
            # mid-edge on the large cell. A corner-only touch yields a tiny nub
            # below the floor and is skipped.
            length, shared = _shared_face(
                cell_geom, neigh_geom, _FACE_BUFFER_EPS, face_floor
            )
            if shared is None or length < face_floor:
                continue

            dx = neigh_geom.centroid.x - cell_cx
            dy = neigh_geom.centroid.y - cell_cy
            if abs(dx) >= abs(dy):
                face = "west" if dx < 0 else "east"
            else:
                face = "south" if dy < 0 else "north"

            cell_faces = boundary_faces.setdefault(cell_id, [])
            if face not in cell_faces:
                cell_faces.append(face)
            edge_parts.setdefault((cell_id, face), []).append(shared)

            # Classify this side's flux source. The inside cell is coarser than
            # this outside neighbour IFF its area is strictly larger; equal-size
            # (tie) and larger-neighbour cases keep the side reading the inside
            # cell's own face (sign +1). ``neigh_id`` is in ``outside_set`` by the
            # guard above, so a smaller *inside* neighbour on the same side is
            # never eligible for ``outside_ids`` (task 2.3).
            src = face_source_parts.setdefault(
                (cell_id, face), {"sign": 1, "outside_ids": []}
            )
            if cell_geom.area > neigh_geom.area:
                src["sign"] = -1
                src["outside_ids"].append(neigh_id)

    # Merge each cell's sub-edges into one geometry per cell, fusing *per side*.
    # Same-side (collinear) sub-edges of a refinement T-junction are line-merged
    # into one continuous ``LineString``; the per-side lines of a corner cell are
    # then collected without merging across sides. The cross-side union is kept
    # un-merged on purpose: a plain ``line_merge`` across a corner would chain two
    # perpendicular sides into one L-shaped ``LineString`` (they touch at the
    # shared corner vertex), which would misrepresent a two-faced cell. Grouping
    # by direction first guarantees one merged line per bordered side — matching
    # the one-flux-per-cardinal-direction contract (see dispatch ``boundary_aq``).
    per_cell_lines: Dict[Any, List[Any]] = {}
    for (cell_id, _face), parts in edge_parts.items():
        # Snap to 2ε first so the buffer's ≈2ε over-capture stubs collapse and the
        # collinear sub-edges meet end-to-end, letting line_merge fuse one side's
        # several refinement sub-edges into a single continuous LineString.
        snapped = shapely.set_precision(unary_union(parts), _FACE_MERGE_SNAP)
        merged = shapely.line_merge(snapped)
        per_cell_lines.setdefault(cell_id, []).append(merged)

    edge_geometries: Dict[Any, Any] = {}
    for cell_id, lines in per_cell_lines.items():
        if len(lines) == 1:
            edge_geometries[cell_id] = lines[0]
        else:
            # One bordered side per entry already; collect (do not re-merge) into
            # a MultiLineString so perpendicular sides stay distinct lines.
            edge_geometries[cell_id] = shapely.MultiLineString(
                [g for line in lines for g in _as_linestrings(line)]
            )

    # Nest the per-(cell, direction) source parts into the response shape
    # ``{cell_id: {direction: {"sign": ±1, "outside_ids": [...]}}}``.
    face_sources: Dict[Any, Dict[str, Dict[str, Any]]] = {}
    for (cell_id, face), src in face_source_parts.items():
        face_sources.setdefault(cell_id, {})[face] = src

    return boundary_faces, edge_geometries, face_sources
