from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

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


ALLOWED_TRANSITIONS: Dict[TwinState, frozenset] = {
    TwinState.EMPTY: frozenset({TwinState.CONFIGURED}),
    TwinState.CONFIGURED: frozenset({TwinState.LOADED}),
    TwinState.LOADED: frozenset({TwinState.READY}),
    TwinState.READY: frozenset(),
}

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


# ---------------------------------------------------------------------------
# Public request types
# ---------------------------------------------------------------------------


@dataclass
class ConfigureRequest:
    config_geom: Any
    config_proj: Any
    out_caw_directory: str
    obs_directory: str
    temp_directory: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadRequest:
    ids_compartments: List[int] = field(default_factory=list)
    geo_provider: Any = None
    compartments: Optional[Dict[int, Any]] = None


@dataclass(frozen=True)
class DescribeRequest:
    include_layers: bool = True
    include_observations: bool = True
    include_outputs: bool = True


@dataclass
class ExtractRequest:
    kind: str = "simulation_matrix"
    id_compartment: Optional[int] = None
    outtype: Optional[str] = None
    param: Optional[str] = None
    syear: Optional[int] = None
    eyear: Optional[int] = None
    id_layer: int = 0
    cutsdate: Optional[str] = None
    cutedate: Optional[str] = None
    target_unit: Optional[str] = None
    agg: Optional[Union[str, float]] = None
    frequency: Optional[str] = None
    pluriannual: bool = False
    plotstart: Optional[str] = None
    plotend: Optional[str] = None
    obs_unit: Optional[str] = None
    compute_criteria: bool = False
    criteria_metrics: Optional[List[str]] = None
    crit_start: Optional[str] = None
    crit_end: Optional[str] = None
    layers: Optional[List[Any]] = None
    layer_names: Optional[List[str]] = None
    layer_id_offset: int = 0
    outcropping_cell_ids: Optional[np.ndarray] = None
    save_directory: Optional[str] = None
    obs_geometry: Any = None
    network_gdf: Any = None
    network_col_name_cell: Optional[str] = None
    network_col_name_fnode: Optional[str] = None
    network_col_name_tnode: Optional[str] = None
    output_csv_path: Optional[str] = None
    cell_ids: Optional[List[int]] = None
    variables: List[str] = field(default_factory=list)


@dataclass
class TransformRequest:
    kind: str = "temporal_aggregation"
    data: Any = None
    dates: Optional[np.ndarray] = None
    column_names: Optional[np.ndarray] = None
    agg_dimension: Union[str, float] = "mean"
    frequency: Optional[str] = None
    pluriannual: bool = False
    year_end_month: int = 12
    id_compartment: Optional[int] = None
    outtype: Optional[str] = None
    param: Optional[str] = None
    sdate: Optional[int] = None
    edate: Optional[int] = None
    cutsdate: Optional[str] = None
    cutedate: Optional[str] = None
    bundle: Any = None
    metrics: Optional[List[str]] = None
    catch_surf_area: Optional[List[float]] = None
    surf_area: Optional[List[float]] = None
    id_surf: Optional[List[int]] = None
    simmatrix_runoff: Optional[np.ndarray] = None
    simmatrix_rain: Optional[np.ndarray] = None
    simmatrix_etr: Optional[np.ndarray] = None
    obs_data: Optional[np.ndarray] = None
    operation: Optional[str] = None
    areas: Optional[np.ndarray] = None
    aq_inputs: Any = None
    regime: Optional[str] = None


@dataclass
class RenderRequest:
    kind: str = "budget_barplot"
    data: Any = None
    plot_title: Optional[str] = None
    output_folder: Optional[str] = None
    output_name: Optional[str] = None
    yaxis_unit: str = "mm"
    obs_point_names: List[str] = field(default_factory=list)
    month_labels: Optional[np.ndarray] = None
    var: Optional[str] = None
    units: Optional[str] = None
    savepath: Optional[str] = None
    interactive: bool = False
    staticpng: bool = True
    staticpdf: bool = True
    years: Optional[str] = None
    id_compartment: Optional[int] = None
    outtype: Optional[str] = None
    param: Optional[str] = None
    simsdate: Optional[int] = None
    simedate: Optional[int] = None
    plotstart: Optional[str] = None
    plotend: Optional[str] = None
    plotstartdate: Optional[str] = None
    plotenddate: Optional[str] = None
    id_layer: int = 0
    directory: Optional[str] = None
    name_file: Optional[str] = None
    ylabel: Optional[str] = None
    obs_unit: Optional[str] = None
    crit_start: Optional[str] = None
    crit_end: Optional[str] = None
    aggr: Optional[Union[str, float]] = None
    df_other_variable: Any = None
    other_variable_config: Optional[Dict[str, Any]] = None
    out_file_path: Optional[str] = None
    tables: Optional[Dict[str, Any]] = None
    colors: Optional[Dict[str, str]] = None


@dataclass
class ExportRequest:
    path: Optional[str] = None
    fmt: str = "pickle"
    data: Any = None


# ---------------------------------------------------------------------------
# Extraction and transformation responses
# ---------------------------------------------------------------------------


@dataclass
class ExtractValuesResponse:
    data: np.ndarray
    dates: np.ndarray
    meta: Optional[Dict[str, Any]] = None
    csv_path: Optional[str] = None


@dataclass
class TemporalOpResponse:
    data: np.ndarray
    date_labels: np.ndarray
    meta: Optional[Dict[str, Any]] = None


@dataclass
class SpatialAverageResponse:
    data: np.ndarray
    meta: Dict[str, Any]


@dataclass
class ObservationsResponse:
    data: np.ndarray
    dates: np.ndarray
    meta: Optional[Dict[str, Any]] = None


@dataclass
class SimObsPointData:
    name: str
    id_cell: int
    id_layer: int
    id_point: Optional[Any] = None
    sim: Optional[np.ndarray] = None
    obs: Optional[np.ndarray] = None
    criteria: Optional[Dict[str, Any]] = None


@dataclass
class SimObsBundleResponse:
    sim_dates: np.ndarray
    obs_dates: np.ndarray
    compartment_name: str
    obs_points: List[SimObsPointData] = field(default_factory=list)
    ext_points: List[SimObsPointData] = field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None


@dataclass
class SpatialMapResponse:
    gdf: Any
    meta: Optional[Dict[str, Any]] = None


@dataclass
class CellSelectionResponse:
    cell_ids: List[int] = field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None


@dataclass
class BudgetComputationResponse:
    data: np.ndarray
    date_labels: np.ndarray
    param: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


@dataclass
class HydrologicalRegimeResponse:
    data: np.ndarray
    obs_point_names: List[str]
    month_labels: np.ndarray
    meta: Optional[Dict[str, Any]] = None


@dataclass
class CriteriaResponse:
    per_point: List[Dict[str, Any]] = field(default_factory=list)
    global_metrics: Dict[str, Any] = field(default_factory=dict)
    by_layer: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    meta: Optional[Dict[str, Any]] = None


@dataclass
class RunoffRatioResponse:
    simulated: float
    observed: float
    surface: float
    meta: Optional[Dict[str, Any]] = None


@dataclass
class AquiferBalanceInputsResponse:
    data: Dict[str, np.ndarray] = field(default_factory=dict)
    dates: Optional[np.ndarray] = None
    meta: Optional[Dict[str, Any]] = None


@dataclass
class AquiferBalanceResponse:
    mass_balance: Any
    flux: Any
    meta: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Model and catalog responses
# ---------------------------------------------------------------------------


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


@dataclass
class LayerInfo:
    id_layer: int
    n_cells: int
    cell_ids: np.ndarray
    cell_areas: np.ndarray
    cell_geometries: list
    layer_gis_name: str
    crs: Any = None


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


@dataclass
class LayerCatalog:
    id_layer: int
    name: str
    n_cells: int
    cell_id_column: Any = None
    crs: Any = None


@dataclass
class ObservationCatalog:
    layer_name: Optional[str]
    n_points: int
    point_id_column: Any = None
    point_name_column: Any = None
    point_layer_column: Any = None
    point_cell_column: Any = None
    point_names: List[str] = field(default_factory=list)
    point_ids: List[Any] = field(default_factory=list)
    layer_ids: List[int] = field(default_factory=list)
    geometries: List[Any] = field(default_factory=list)


@dataclass
class CompartmentCatalog:
    id_compartment: int
    name: str
    out_caw_path: str
    regime: str
    primary_layer_name: Optional[str]
    layer_cell_id_column: Any = None
    out_caw_directory: Optional[str] = None
    hyd_corresp_missing: bool = False
    layers: List[LayerCatalog] = field(default_factory=list)
    observations: Optional[ObservationCatalog] = None
    output_parameters: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def layers_gis_names(self) -> List[str]:
        return [layer.name for layer in self.layers]


@dataclass
class TwinCatalog:
    compartments: List[CompartmentCatalog] = field(default_factory=list)
    extract_kinds: List[str] = field(default_factory=list)
    transform_kinds: List[str] = field(default_factory=list)
    render_kinds: List[str] = field(default_factory=list)
    export_formats: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Macro-method result types
# ---------------------------------------------------------------------------


@dataclass
class TwinDescription:
    state: str
    n_compartments: int
    compartments: List[CompartmentInfo]
    metadata: Dict[str, Any] = field(default_factory=dict)
    catalog: Optional[TwinCatalog] = None


@dataclass(frozen=True)
class FacadeMethod:
    name: str
    level: str
    purpose: str
    delegates_to: List[str] = field(default_factory=list)


@dataclass
class FacadeDescription:
    entrypoint: str
    primary_consumer: str
    lifecycle: List[str]
    macro_methods: List[FacadeMethod] = field(default_factory=list)
    transition_methods: List[FacadeMethod] = field(default_factory=list)
    frontend_methods: List[FacadeMethod] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.frontend_methods and self.transition_methods:
            self.frontend_methods = list(self.transition_methods)
        if not self.transition_methods and self.frontend_methods:
            self.transition_methods = list(self.frontend_methods)


@dataclass
class RenderResult:
    artefacts: List[str] = field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None


@dataclass
class ExportResult:
    path: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
