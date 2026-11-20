"""kinds — the one registry of the dispatching verbs and the kinds each accepts.

Role
----
``KINDS`` lists, for each of the six dispatching verbs, the ``kind`` values its
ladder in ``dispatch.py`` accepts, and ``REQUESTS`` the request dataclass the
verb takes. ``describe`` reads it for its catalog, and the ``htas-dev`` command
line generates its commands from it, so a new kind reaches both in the same
change. ``tests/unit/test_kinds_registry.py`` fails when the registry and the
ladders of ``dispatch.py`` disagree.

Aliases the ladders also accept (``render`` takes ``budget`` for
``budget_barplot`` and ``regime`` for ``hydrological_regime``) are not listed.
"""

from __future__ import annotations

from typing import Dict, Tuple, Type

from .api_types import (
    AssembleRequest,
    ExportRequest,
    FetchRequest,
    MaskRequest,
    RenderRequest,
    TransformRequest,
)

KINDS: Dict[str, Tuple[str, ...]] = {
    "fetch": (
        "simulation_matrix",
        "observations",
        "sim_obs_bundle",
        "spatial_map",
        "catchment_cells",
        "aquifer_outcropping_map",
        "aq_balance_inputs",
    ),
    "mask": (
        "polygon_cells",
        "area_values",
        "boundary_hyd",
        "boundary_hyd_flux",
        "boundary_aq",
        "boundary_aq_flux",
    ),
    "transform": (
        "temporal_aggregation",
        "temporal_aggregate",
        "spatial_average",
        "volumetric_rescale",
        "criteria",
        "budget",
        "hydrological_regime",
        "runoff_ratio",
        "aq_balance",
    ),
    "assemble": ("compartment_bundle", "boundary_aq_layers"),
    "render": (
        "budget_barplot",
        "hydrological_regime",
        "sim_obs_pdf",
        "sim_obs_interactive",
        "aq_flux_diagram",
    ),
    "export": ("npy", "geopackage"),
}

REQUESTS: Dict[str, Type] = {
    "fetch": FetchRequest,
    "mask": MaskRequest,
    "transform": TransformRequest,
    "assemble": AssembleRequest,
    "render": RenderRequest,
    "export": ExportRequest,
}

__all__ = ["KINDS", "REQUESTS"]
