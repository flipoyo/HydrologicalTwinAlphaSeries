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

from HydrologicalTwinAlphaSeries.config.constants import (
    AQ_FACE_DIRECTIONS,
    OPPOSITE_FACE,
)
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


# ---------------------------------------------------------------------------
# Coarse-inside-cell source correction (aq-boundary-coarse-cell-flux).
#
# On a refined mesh a coarse inside cell's own stored face flux is a BLEND over
# every neighbour on that side, so it must NOT be read; the exact single-sub-face
# crossing is the negated sum of the smaller outside neighbours' OPPOSING faces.
# ``face_sources`` carries the per-(cell, direction) switch: +1 (INT_cell, own
# face) or -1 (EXT_cell, negated outside-opposite sum over ``outside_ids``).
# ---------------------------------------------------------------------------


def _indexed_face_responses(n_cells: int, n_days: int) -> dict:
    """Per-direction (n_cells, n_days) matrices with a value UNIQUE per (direction,
    cell) so a picked or summed series is identifiable. Cell ``cid`` (1-based) on
    direction index ``k`` holds the constant ``(k + 1) * 100 + cid`` — so e.g.
    ``face_data["west"][B-1]`` is distinguishable from every other face value."""
    face_responses = {}
    for k, direction in enumerate(AQ_FACE_DIRECTIONS):
        rows = np.array(
            [[float((k + 1) * 100 + (cid + 1)) for _ in range(n_days)]
             for cid in range(n_cells)]
        )
        face_responses[direction] = SimpleNamespace(
            data=rows, dates=np.arange(n_days)
        )
    return face_responses


def _face_value(face_responses: dict, direction: str, cell_id: int) -> np.ndarray:
    """The stored face series for (direction, cell_id), indexed cell_id-1."""
    return face_responses[direction].data[cell_id - 1, :]


def test_boundary_aq_flux_coarse_cell_reads_negated_outside_sum():
    """Task 6.1 — a coarse inside cell A abutting smaller outside cells B2, B3 on
    its east side reads ``-(face_data['west'][B2-1] + face_data['west'][B3-1])``
    and NOT its own ``face_data['east'][A-1]``."""
    A, B2, B3 = 1, 2, 3
    n_days = 4
    face_responses = _indexed_face_responses(n_cells=3, n_days=n_days)
    face_orientations = BoundaryFluxResponse(
        cell_ids=[A],
        face_directions={A: ["east"]},
        edge_geometries={A: LineString([(1, 0), (1, 2)])},
        face_sources={A: {"east": {"sign": -1, "outside_ids": [B2, B3]}}},
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
        face_responses=face_responses,
    )

    resp = dispatch.mask(None, request)

    opp = OPPOSITE_FACE["east"]  # "west"
    expected = -(
        _face_value(face_responses, opp, B2)
        + _face_value(face_responses, opp, B3)
    )
    np.testing.assert_array_equal(resp.fluxes[A]["east"], expected)
    # A's own east face was NOT read.
    assert not np.array_equal(
        resp.fluxes[A]["east"], _face_value(face_responses, "east", A)
    )


def test_boundary_aq_flux_excludes_inside_smaller_neighbour():
    """Task 6.2 — a coarse inside cell whose east side abuts a smaller INSIDE
    neighbour B1 and smaller OUTSIDE B2, B3: only B2, B3 are in ``outside_ids``
    (B1 is not), so the summed flux never includes the A<->B1 internal exchange."""
    A, B1, B2, B3 = 1, 2, 3, 4
    n_days = 3
    face_responses = _indexed_face_responses(n_cells=4, n_days=n_days)
    # The geometry pass only puts OUTSIDE cells in outside_ids; B1 (inside) is
    # absent by construction. We assert the flux read honours that.
    face_orientations = BoundaryFluxResponse(
        cell_ids=[A],
        face_directions={A: ["east"]},
        edge_geometries={A: LineString([(1, 0), (1, 2)])},
        face_sources={A: {"east": {"sign": -1, "outside_ids": [B2, B3]}}},
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
        face_responses=face_responses,
    )

    resp = dispatch.mask(None, request)

    opp = OPPOSITE_FACE["east"]
    expected = -(
        _face_value(face_responses, opp, B2)
        + _face_value(face_responses, opp, B3)
    )
    np.testing.assert_array_equal(resp.fluxes[A]["east"], expected)
    # B1's opposing face must contribute nothing to the summed flux.
    b1_contrib = -_face_value(face_responses, opp, B1)
    assert not np.array_equal(resp.fluxes[A]["east"], expected + b1_contrib)


def test_boundary_aq_flux_per_cell_mixed_sources():
    """Task 6.3 — a cell EXT_cell on its south side (sourced from smaller outside
    neighbours, sign -1) and INT_cell on its west side (own face, +1). Each face
    is read from its own source; nothing is cross-contaminated."""
    A, B_south = 1, 2
    n_days = 3
    face_responses = _indexed_face_responses(n_cells=2, n_days=n_days)
    face_orientations = BoundaryFluxResponse(
        cell_ids=[A],
        face_directions={A: ["west", "south"]},
        edge_geometries={A: LineString([(0, 0), (0, 1)])},
        face_sources={
            A: {
                "west": {"sign": 1, "outside_ids": []},
                "south": {"sign": -1, "outside_ids": [B_south]},
            }
        },
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
        face_responses=face_responses,
    )

    resp = dispatch.mask(None, request)

    # west: own face (INT_cell).
    np.testing.assert_array_equal(
        resp.fluxes[A]["west"], _face_value(face_responses, "west", A)
    )
    # south: negated opposing (north) face of the single outside neighbour.
    opp_south = OPPOSITE_FACE["south"]  # "north"
    np.testing.assert_array_equal(
        resp.fluxes[A]["south"],
        -_face_value(face_responses, opp_south, B_south),
    )
    # The per-cell NET the L1 loop would build = own-west + negated-outside-south.
    net = resp.fluxes[A]["west"] + resp.fluxes[A]["south"]
    expected_net = (
        _face_value(face_responses, "west", A)
        - _face_value(face_responses, opp_south, B_south)
    )
    np.testing.assert_array_equal(net, expected_net)


def test_boundary_aq_flux_empty_face_sources_reads_own_face():
    """Task 6.4 — with no ``face_sources`` (equal-resolution / fine-inside mesh)
    every face reduces to the pre-change own-face read, byte-identical."""
    A = 1
    n_days = 3
    face_responses = _indexed_face_responses(n_cells=1, n_days=n_days)
    face_orientations = BoundaryFluxResponse(
        cell_ids=[A],
        face_directions={A: ["west", "north"]},
        edge_geometries={A: LineString([(0, 0), (0, 1)])},
        # face_sources left at its empty default → all INT_cell.
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
        face_responses=face_responses,
    )

    resp = dispatch.mask(None, request)

    for direction in ("west", "north"):
        np.testing.assert_array_equal(
            resp.fluxes[A][direction],
            _face_value(face_responses, direction, A),
        )
