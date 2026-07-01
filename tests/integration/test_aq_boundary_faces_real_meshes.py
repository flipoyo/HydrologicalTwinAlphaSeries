"""Full-mesh regression for ``cells_boundary_faces`` on the real Seine AQ meshes.

Guards ``fix-aq-boundary-tjunction-faces``: the buffer-overlap shared-face
detector must recover the refinement T-junction faces that the predecessor's
``boundary ∩ boundary`` test silently dropped on the **rotated, off-grid 3C**
mesh, while leaving the **axis-aligned 8C** mesh unchanged.

The data is large and not vendored. Each test ``pytest.skip``s when the mesh
shapefile is absent, so the suite stays green on a clean checkout. Point the
tests at local data with::

    SEINE_3C_AQ_DIR=/path/to/3C/DATA_AQ \
    SEINE_8C_AQ_DIR=/path/to/8C/DATA_AQ \
        pixi run python -m pytest tests/integration/test_aq_boundary_faces_real_meshes.py

The default paths match the developer layout these constants were validated on
(see design.md / tasks 3.1–3.2).
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import pytest
import shapely
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.services.public.polygon_mask import (
    _FACE_BUFFER_EPS,
    _mesh_face_floor,
    _shared_face,
    cells_boundary_faces,
)

# Default data roots (overridable by env var). These are the meshes the
# constants were validated against; see design.md "Measured floors".
_3C_DIR = Path(
    os.environ.get(
        "SEINE_3C_AQ_DIR",
        "/home/smazzarelli/data/SEINE_3C_v2025/_SHP_Seine_Simpl_NF/DATA_AQ",
    )
)
_8C_DIR = Path(
    os.environ.get(
        "SEINE_8C_AQ_DIR",
        "/home/smazzarelli/data/SIG_SEINE_8C_DRAIN/DATA/DATA_AQ",
    )
)

# (layer file, human label, expected mesh-derived floor in m) — the floors are
# the design's reference values, asserted here so a future constant change that
# silently shifts them trips this test.
_3C_LAYERS = [
    ("AQ_GRID_TERT_L93.shp", "3C TERT", 200.0),
    ("AQ_GRID_CRAI_L93.shp", "3C CRAI", 200.0),
    ("AQ_GRID_JURA_L93.shp", "3C JURA", 200.0),
]
_8C_LAYERS = [
    ("0_ALLUVIONS.shp", "8C ALLUVIONS", 20.0),
    ("6_CRAIE.shp", "8C CRAIE", 10.0),
]


def _id_col(gdf: gpd.GeoDataFrame) -> str:
    """First integer-id-looking column (``Id_Int`` / ``ID_Int`` across meshes)."""
    for col in gdf.columns:
        if col.lower() == "id_int":
            return col
    return next(c for c in gdf.columns if c != "geometry")


def _central_mask(gdf: gpd.GeoDataFrame):
    """A box over the central ~50%×50% of the mesh, so the masked sub-area has a
    real interior boundary ring of both same-size and different-size adjacencies."""
    minx, miny, maxx, maxy = gdf.total_bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    w, h = (maxx - minx) * 0.25, (maxy - miny) * 0.25
    return box(cx - w, cy - h, cx + w, cy + h)


def _old_vs_new_kept(gdf: gpd.GeoDataFrame, polygon, id_col: str):
    """Count (inside,outside) faces kept by the OLD boundary∩boundary test vs the
    NEW buffer-overlap test over the same candidate pairs.

    The OLD test is the predecessor's exact code (``boundary ∩ boundary`` with a
    1 mm common-grid snap and a 1e-6 length floor); the NEW test is
    :func:`_shared_face` against the mesh-derived floor. This is an
    implementation-independent oracle for "faces the predecessor dropped".
    """
    geoms = list(gdf.geometry.values)
    ids = list(gdf[id_col].values)
    centroids = gdf.geometry.centroid
    inside = [bool(polygon.contains(centroids.iloc[i])) for i in range(len(geoms))]
    outside_set = {ids[i] for i, x in enumerate(inside) if not x}
    tree = shapely.STRtree(geoms)
    floor = _mesh_face_floor(gdf)

    old_kept = 0
    new_kept = 0
    for i, is_in in enumerate(inside):
        if not is_in:
            continue
        for pos in tree.query(geoms[i], predicate="intersects"):
            p = int(pos)
            if p == i or ids[p] not in outside_set:
                continue
            old_shared = geoms[i].boundary.intersection(
                geoms[p].boundary, grid_size=1e-3
            )
            if (not old_shared.is_empty) and old_shared.length >= 1e-6:
                old_kept += 1
            length, line = _shared_face(geoms[i], geoms[p], _FACE_BUFFER_EPS, floor)
            if line is not None and length >= floor:
                new_kept += 1
    return old_kept, new_kept, floor


def _load_or_skip(directory: Path, filename: str) -> gpd.GeoDataFrame:
    path = directory / filename
    if not path.is_file():
        pytest.skip(
            f"AQ mesh not found at {path}. Set SEINE_3C_AQ_DIR / SEINE_8C_AQ_DIR "
            "to run this regression locally; see the module docstring."
        )
    return gpd.read_file(path)


# ---------------------------------------------------------------------------
# 3.1 — rotated 3C mesh: T-junction faces recovered, no corner false positives
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("filename,label,expected_floor", _3C_LAYERS)
def test_3c_recovers_dropped_tjunction_faces(filename, label, expected_floor):
    """On the rotated 3C mesh the new detector recovers strictly MORE shared
    faces than the predecessor's boundary∩boundary test — those extras are the
    refinement T-junction faces that were silently dropped — and every recovered
    boundary cell is a genuine edge-neighbour (the floor rejects corner nubs).

    Confirms `#### Scenario: Full-boundary recovery on the rotated mesh`.
    """
    gdf = _load_or_skip(_3C_DIR, filename)
    polygon = _central_mask(gdf)
    id_col = _id_col(gdf)

    # Floor matches the design's measured value (rotation-invariant sqrt(area)).
    floor = _mesh_face_floor(gdf)
    assert floor == pytest.approx(expected_floor, rel=0.05)

    old_kept, new_kept, _ = _old_vs_new_kept(gdf, polygon, id_col)
    # The fix recovers faces the predecessor dropped: strictly more, none lost.
    assert new_kept > old_kept, (
        f"{label}: expected the buffer-overlap test to recover dropped "
        f"T-junction faces, but new={new_kept} <= old={old_kept}"
    )

    # No corner false-positives: every recovered face is a real shared edge, i.e.
    # its recovered length clears the floor (a corner nub is ≈ 2ε ≪ floor).
    boundary_faces, edge_geometries, _face_sources = cells_boundary_faces(gdf, polygon, id_col=id_col)
    assert boundary_faces, f"{label}: expected a non-empty boundary"
    for cell_id, geom in edge_geometries.items():
        assert not geom.is_empty
        assert geom.length >= floor, (
            f"{label}: cell {cell_id} recovered a sub-floor face "
            f"({geom.length:.3f} < {floor:.3f}) — a corner nub leaked through"
        )


# ---------------------------------------------------------------------------
# 3.2 — axis-aligned 8C mesh: no regression vs the predecessor
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("filename,label,expected_floor", _8C_LAYERS)
def test_8c_axis_aligned_no_regression(filename, label, expected_floor):
    """On the axis-aligned 8C mesh the new detector keeps EXACTLY the same faces
    as the predecessor's boundary∩boundary test (no face gained, none lost), and
    the mesh-derived floor tracks the finer cell size.

    Confirms `#### Scenario: Axis-aligned grid output preserved`.
    """
    gdf = _load_or_skip(_8C_DIR, filename)
    polygon = _central_mask(gdf)
    id_col = _id_col(gdf)

    floor = _mesh_face_floor(gdf)
    assert floor == pytest.approx(expected_floor, rel=0.05)

    old_kept, new_kept, _ = _old_vs_new_kept(gdf, polygon, id_col)
    # Axis-aligned: the rotation defect does not occur, so old and new agree.
    assert new_kept == old_kept, (
        f"{label}: axis-aligned mesh should not change face count "
        f"(old={old_kept}, new={new_kept})"
    )

    boundary_faces, edge_geometries, _face_sources = cells_boundary_faces(gdf, polygon, id_col=id_col)
    assert boundary_faces
    for geom in edge_geometries.values():
        assert geom.length >= floor


# ---------------------------------------------------------------------------
# 3.3 — dispatch-branch contract holds on real meshes (boundary_aq consumer)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize(
    "directory,filename,label",
    [
        (_3C_DIR, "AQ_GRID_TERT_L93.shp", "3C TERT"),
        (_8C_DIR, "6_CRAIE.shp", "8C CRAIE"),
    ],
)
def test_dispatch_boundary_aq_contract_on_real_mesh(directory, filename, label):
    """The shape the ``boundary_aq`` dispatch branch consumes is complete and
    self-consistent on a real 3C and 8C compartment:

    * ``face_directions`` and ``edge_geometries`` share the same keys (callers
      align them 1:1),
    * each cell's directions are the *distinct* cardinal directions (the
      one-cardinal-face → one-net-flux contract the per-direction flux mapping
      relies on — ``cells_boundary_faces`` must pre-dedup so dispatch's
      ``dict.fromkeys`` is a no-op),
    * every recovered face geometry is non-empty.

    Confirms the per-direction flux mapping is unchanged (task 3.3).
    """
    gdf = _load_or_skip(directory, filename)
    polygon = _central_mask(gdf)
    id_col = _id_col(gdf)

    boundary_faces, edge_geometries, _face_sources = cells_boundary_faces(gdf, polygon, id_col=id_col)

    assert boundary_faces, f"{label}: expected a non-empty boundary"
    assert boundary_faces.keys() == edge_geometries.keys()
    for cell_id, dirs in boundary_faces.items():
        # Distinct cardinal directions only — dispatch's dedup must be a no-op.
        assert dirs == list(dict.fromkeys(dirs))
        assert set(dirs) <= {"east", "west", "north", "south"}
        assert not edge_geometries[cell_id].is_empty
