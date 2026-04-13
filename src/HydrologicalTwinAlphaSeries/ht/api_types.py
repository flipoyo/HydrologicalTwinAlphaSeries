from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Internal state model
# ---------------------------------------------------------------------------

class TwinState(enum.Enum):
    """Lifecycle states for :class:`HydrologicalTwin`.

    Allowed transitions::

        EMPTY → CONFIGURED → LOADED → READY
    """

    EMPTY = "EMPTY"
    CONFIGURED = "CONFIGURED"
    LOADED = "LOADED"
    READY = "READY"


#: Allowed forward transitions: *from_state* → set of *to_states*.
ALLOWED_TRANSITIONS: Dict[TwinState, frozenset] = {
    TwinState.EMPTY: frozenset({TwinState.CONFIGURED}),
    TwinState.CONFIGURED: frozenset({TwinState.LOADED}),
    TwinState.LOADED: frozenset({TwinState.READY}),
    TwinState.READY: frozenset(),  # terminal
}

#: Minimum state required for each macro-method.
MINIMUM_STATE: Dict[str, TwinState] = {
    "configure": TwinState.EMPTY,
    "load": TwinState.CONFIGURED,
    "register_compartment": TwinState.LOADED,
    "describe": TwinState.LOADED,
    "extract": TwinState.LOADED,
    "transform": TwinState.LOADED,
    "render": TwinState.LOADED,
    "export": TwinState.LOADED,
}


class InvalidStateError(Exception):
    """Raised when a macro-method is called in an invalid lifecycle state."""


@dataclass
class ExtractValuesResponse:
    """Response of HydrologicalTwin.extract_values.

    Attributes
    ----------
    data : np.ndarray
        Extracted data as a NumPy array.
    dates : np.ndarray
        Corresponding dates as a NumPy array.
    meta : Optional[Dict[str, Any]]
        Additional metadata about the extraction.
    """
    data: np.ndarray  # Changed from pd.DataFrame
    dates: np.ndarray  # Add dates array
    meta: Optional[Dict[str, Any]] = None


@dataclass
class TemporalOpResponse:
    data: np.ndarray
    date_labels: np.ndarray
    meta: Optional[Dict[str, Any]] = None

@dataclass
class SpatialAverageResponse:
    """Response from spatial averaging operation."""
    data: np.ndarray  # 1D array (n_timesteps,)
    meta: dict

@dataclass
class ObservationsResponse:
    """Response from reading observation data.

    Attributes
    ----------
    data : np.ndarray
        Observation measurements, shape (n_points, n_timesteps).
        May contain NaN for missing observations.
    dates : np.ndarray
        Datetime64 array (n_timesteps,).
    meta : Optional[Dict[str, Any]]
        Additional metadata (e.g., id_compartment, obs_point_ids, period).
    """
    data: np.ndarray
    dates: np.ndarray
    meta: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Model Layer responses
# ---------------------------------------------------------------------------

@dataclass
class CompartmentInfo:
    """Serializable snapshot of compartment metadata."""
    id_compartment: int
    name: str
    layers_gis_names: List[str]
    n_layers: int
    n_cells: int
    cell_ids: np.ndarray
    out_caw_path: str
    regime: str


@dataclass
class LayerInfo:
    """Serializable snapshot of a single mesh layer."""
    id_layer: int
    n_cells: int
    cell_ids: np.ndarray
    cell_areas: np.ndarray
    cell_geometries: list
    layer_gis_name: str
    crs: Any = None  # pyproj.CRS or None


# ---------------------------------------------------------------------------
# Data Layer responses
# ---------------------------------------------------------------------------

@dataclass
class ObservationInfo:
    """Serializable snapshot of observation metadata for a compartment."""
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


# ---------------------------------------------------------------------------
# Macro-method result types
# ---------------------------------------------------------------------------

@dataclass
class TwinDescription:
    """Result of :meth:`HydrologicalTwin.describe`.

    Aggregates all metadata about the twin's current state.
    """

    state: str
    n_compartments: int
    compartments: List[CompartmentInfo]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FacadeMethod:
    """Description of a public HydrologicalTwin facade method."""

    name: str
    level: str
    purpose: str
    delegates_to: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FacadeDescription:
    """Explicit description of the HydrologicalTwin facade for frontend consumers."""

    entrypoint: str
    primary_consumer: str
    lifecycle: List[str]
    macro_methods: List[FacadeMethod] = field(default_factory=list)
    frontend_methods: List[FacadeMethod] = field(default_factory=list)


@dataclass
class RenderResult:
    """Result of :meth:`HydrologicalTwin.render`.

    Carries paths to rendered artefacts produced by the rendering services.
    """

    artefacts: List[str] = field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None


@dataclass
class ExportResult:
    """Result of :meth:`HydrologicalTwin.export`.

    Carries paths or bytes of exported data.
    """

    path: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
