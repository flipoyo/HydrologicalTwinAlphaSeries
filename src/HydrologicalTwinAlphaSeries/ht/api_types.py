from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

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


@runtime_checkable
class CompartmentProvider(Protocol):
    """Public protocol used by ``load`` to build a compartment lazily."""

    def build_compartment(self, request: "LoadCompartmentRequest", twin: Any) -> Any:
        """Return a fully constructed compartment aggregate."""


@dataclass(frozen=True)
class LoadGeometrySource:
    """Public geometry source descriptor consumed by :meth:`HydrologicalTwin.load`."""

    kind: str
    provider: Optional[CompartmentProvider] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadObservationSource:
    """Serializable observation source descriptor for a compartment load request."""

    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadPeriod:
    """Simulation period attached to a load request."""

    start_year: int
    end_year: int


@dataclass(frozen=True)
class LoadDirectories:
    """Filesystem directories attached to a load request."""

    out_caw_directory: Optional[str] = None
    obs_directory: Optional[str] = None
    temp_directory: Optional[str] = None


@dataclass(frozen=True)
class LoadCompartmentRequest:
    """Public description of a compartment to load."""

    id_compartment: int
    stable_id: str
    geometry_source: LoadGeometrySource
    observation_source: Optional[LoadObservationSource] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadRequest:
    """Typed query for ``HydrologicalTwin.load``."""

    kind: str = "compartments"
    compartments: List[LoadCompartmentRequest] = field(default_factory=list)
    period: Optional[LoadPeriod] = None
    directories: Optional[LoadDirectories] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DescribeRequest:
    """Typed query for ``HydrologicalTwin.describe``."""

    kind: str = "catalog"


@dataclass(frozen=True)
class ExtractRequest:
    """Typed query for ``HydrologicalTwin.extract``."""

    kind: str
    id_compartment: Optional[int] = None
    outtype: Optional[str] = None
    param: Optional[str] = None
    syear: Optional[int] = None
    eyear: Optional[int] = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransformRequest:
    """Typed query for ``HydrologicalTwin.transform``."""

    kind: str
    payload: Any = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderRequest:
    """Typed query for ``HydrologicalTwin.render``."""

    kind: str
    payload: Any = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportRequest:
    """Typed query for ``HydrologicalTwin.export``."""

    kind: str = "pickle"
    path: Optional[str] = None
    payload: Any = None
    options: Dict[str, Any] = field(default_factory=dict)


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
    """Serializable snapshot of compartment metadata.

    ``extract_kinds`` / ``transform_kinds`` / ``render_kinds`` describe the
    compartment-level workflows that can be applied once the compartment is
    loaded. The same categories also appear on :class:`TwinDescription` at the
    twin level to describe the global facade contract.
    """
    id_compartment: int
    stable_id: str
    name: str
    layers_gis_names: List[str]
    resolutions: List[str]
    n_layers: int
    n_cells: int
    cell_ids: np.ndarray
    out_caw_path: str
    regime: str
    observation_layers: List[str] = field(default_factory=list)
    observation_units: Dict[str, str] = field(default_factory=dict)
    supported_outputs: List[str] = field(default_factory=list)
    extract_kinds: List[str] = field(default_factory=list)
    transform_kinds: List[str] = field(default_factory=list)
    render_kinds: List[str] = field(default_factory=list)


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

    kind: str
    state: str
    n_compartments: int
    compartments: List[CompartmentInfo]
    metadata: Dict[str, Any] = field(default_factory=dict)
    supported_outputs: List[str] = field(default_factory=list)
    extract_kinds: List[str] = field(default_factory=list)
    transform_kinds: List[str] = field(default_factory=list)
    render_kinds: List[str] = field(default_factory=list)
    export_kinds: List[str] = field(default_factory=list)
    transitional_methods: List[str] = field(default_factory=list)


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
    transitional_methods: List[FacadeMethod] = field(default_factory=list)


@dataclass
class ExtractResult:
    """Result of :meth:`HydrologicalTwin.extract` when using typed requests."""

    kind: str
    payload: Any
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformResult:
    """Result of :meth:`HydrologicalTwin.transform` when using typed requests."""

    kind: str
    payload: Any
    meta: Dict[str, Any] = field(default_factory=dict)


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
