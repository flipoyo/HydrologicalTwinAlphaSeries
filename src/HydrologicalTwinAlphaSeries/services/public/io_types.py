"""Leaf data DTOs shared by the L3 io service and the L2 developer API.

These are pure, dependency-free dataclasses describing the *shape* of data
that flows out of the L3 reads/resolves in :mod:`twin_io`. They live at L3 so
that ``services/public/twin_io.py`` can import them with a strictly downward
edge (no ``ht.developer`` dependency), while the L2
``ht/developer/api_types.py`` re-exports them so existing L2 import sites keep
their names unchanged.

They carry no L2 logic — only field declarations — which is why they belong at
the leaf of the dependency graph rather than in the developer ``api_types``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


# LAYER REFACTORING - ALL THESE TYPES COULD BE AT THE L2 once all the pipelines are aligned (ex. all the data fetching pass by fetch/simulation_matrix)
@dataclass
class ValuesResponse:
    """Per-cell time-series response shared by ``fetch`` and ``mask`` reads.

    ``weights`` and ``clipped_geometries`` are populated on the weighted
    polygon-mask path (``mask(kind="area_values", weighted=True)``) and on the
    HYD ``resolution="reaches"`` path (where reaches are always boundary-clipped
    and carry a length-fraction weight, even when ``weighted=False``). On every
    other path both fields are ``None`` so the binary-mask response shape is
    unchanged from the parent ``add-mask-macro`` capability.
    """

    data: np.ndarray
    dates: np.ndarray
    meta: Optional[Dict[str, Any]] = None
    csv_path: Optional[str] = None
    weights: Optional[np.ndarray] = None
    clipped_geometries: Optional[List[Any]] = None


@dataclass
class ObservationsResponse:
    data: np.ndarray
    dates: np.ndarray
    meta: Optional[Dict[str, Any]] = None


@dataclass
class CompartmentInfo:
    id_compartment: int
    name: str
    layers_gis_names: List[str]
    n_layers: int
    n_cells: int
    cell_ids: np.ndarray
    out_caw_path: str
    regime: str
    # 1-based global cell index (``Cell.id_abs``) in getCellIdVector order —
    # the simulation-matrix row order. Distinct from ``cell_ids`` (per-layer).
    id_abs: Optional[np.ndarray] = None


@dataclass
class LayerInfo:
    id_layer: int
    n_cells: int
    cell_ids: np.ndarray
    cell_areas: np.ndarray
    cell_geometries: list
    layer_gis_name: str
    crs: Any = None
    # 1-based global cell index (``Cell.id_abs``) for each cell in this layer.
    id_abs: Optional[np.ndarray] = None


@dataclass
class ObservationInfo:
    id_compartment: int
    obs_type: str
    n_points: int
    layer_gis_name: str
    point_names: List[str]
    point_ids: list
    cell_ids: List[int]
    layer_ids: List[int]
    geometries: list
    mesh_ids: List[int]
