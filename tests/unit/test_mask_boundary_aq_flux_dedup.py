"""Flux-dedup test for the ``boundary_aq_flux`` dispatch branch on refined grids
(fix-aq-boundary-refined-grid, task 4.4).

CaWaQS stores exactly one finite-difference flux per cardinal direction per
aquifer cell. On a refined (quadtree) mesh a boundary cell can share one side
with several smaller outside neighbours, which the boundary-face scan would
label with the same cardinal direction repeated (e.g. ``["west","west","west"]``).
The flux mapping must collapse those to ONE net flux series for that direction —
never N, never a silently-dropped direction.

The flux branch reuses a pre-built ``face_orientations`` response and pre-fetched
``face_responses`` and does not touch the twin, so we drive ``dispatch.mask``
directly with ``twin=None``.
"""

from __future__ import annotations

import numpy as np
from types import SimpleNamespace

from shapely.geometry import LineString, Polygon

from HydrologicalTwinAlphaSeries.config.constants import AQ_FACE_DIRECTIONS
from HydrologicalTwinAlphaSeries.ht.developer import dispatch
from HydrologicalTwinAlphaSeries.ht.developer.api_types import (
    BoundaryFluxResponse,
    MaskRequest,
)


def _face_responses(n_cells: int, n_days: int) -> dict:
    """One per-direction (n_cells, n_days) matrix, a distinct constant per
    direction so the picked series is identifiable. Rows indexed by cell_id-1."""
    face_responses = {}
    for k, direction in enumerate(AQ_FACE_DIRECTIONS):
        data = np.full((n_cells, n_days), float(k + 1))
        face_responses[direction] = SimpleNamespace(
            data=data, dates=np.arange(n_days)
        )
    return face_responses


def test_boundary_aq_flux_collapses_same_side_neighbours_to_one_series():
    """A refined cell whose west side abuts three outside cells (face_directions
    == ['west','west','west']) yields EXACTLY one 'west' net-flux series."""
    cell_id = 1
    n_days = 4
    # face_orientations as produced by the boundary_aq pass — but here we feed it
    # the *raw* repeated-direction shape to prove the flux branch deduplicates
    # even if upstream ever regressed.
    face_orientations = BoundaryFluxResponse(
        cell_ids=[cell_id],
        face_directions={cell_id: ["west", "west", "west"]},
        edge_geometries={cell_id: LineString([(0, 0), (0, 3)])},
        fluxes={},
        dates=None,
        meta={"kind": "boundary_aq"},
    )
    request = MaskRequest(
        kind="boundary_aq_flux",
        id_compartment=1,
        polygon=Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        syear=2000,
        eyear=2000,
        face_orientations=face_orientations,
        face_responses=_face_responses(n_cells=1, n_days=n_days),
    )

    resp = dispatch.mask(None, request)

    # Exactly one west entry, no duplicates, no other direction invented.
    assert list(resp.fluxes[cell_id].keys()) == ["west"]
    west_const = float(list(AQ_FACE_DIRECTIONS).index("west") + 1)
    np.testing.assert_array_equal(
        resp.fluxes[cell_id]["west"], np.full(n_days, west_const)
    )
    # face_directions for the cell is the unique direction set.
    assert resp.face_directions[cell_id] == ["west"]


def test_boundary_aq_flux_no_direction_dropped_or_double_counted():
    """A refined corner cell bordering west (×3) and south (×2) yields exactly
    one series per distinct direction — both present, neither duplicated."""
    cell_id = 1
    n_days = 3
    face_orientations = BoundaryFluxResponse(
        cell_ids=[cell_id],
        face_directions={cell_id: ["west", "west", "west", "south", "south"]},
        edge_geometries={cell_id: LineString([(0, 0), (0, 3)])},
        fluxes={},
        dates=None,
        meta={"kind": "boundary_aq"},
    )
    request = MaskRequest(
        kind="boundary_aq_flux",
        id_compartment=1,
        polygon=Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        syear=2000,
        eyear=2000,
        face_orientations=face_orientations,
        face_responses=_face_responses(n_cells=1, n_days=n_days),
    )

    resp = dispatch.mask(None, request)

    keys = list(resp.fluxes[cell_id].keys())
    # Every bordered direction present exactly once; insertion order preserved.
    assert keys == ["west", "south"]
    for direction in ("west", "south"):
        const = float(list(AQ_FACE_DIRECTIONS).index(direction) + 1)
        np.testing.assert_array_equal(
            resp.fluxes[cell_id][direction], np.full(n_days, const)
        )
