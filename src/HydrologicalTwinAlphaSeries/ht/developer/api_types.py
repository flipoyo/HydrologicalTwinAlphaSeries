from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Union

import numpy as np

# Leaf data DTOs live at L3 (``services/public/io_types.py``) so the L3 io
# service can import them with a strictly downward edge. They are re-exported
# here so existing L2 import sites keep referencing them from ``api_types``.
from ...services.public.io_types import (
    CompartmentInfo,
    LayerInfo,
    ObservationInfo,
    ObservationsResponse,
    ValuesResponse,
)

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
    "describe": TwinState.LOADED,
    "fetch": TwinState.LOADED,
    "mask": TwinState.LOADED,
    "transform": TwinState.LOADED,
    "render": TwinState.LOADED,
    "export": TwinState.LOADED,
    "assemble": TwinState.LOADED,
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
class FetchRequest:
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
class MaskRequest:
    """Inputs for ``HydrologicalTwin.mask(kind=...)``.

    ``weighted`` and ``target_unit`` are only consumed by
    ``kind="area_values"`` today: when ``weighted=True``, the dispatcher
    resolves cells via :func:`cells_in_polygon_weighted` and multiplies
    per-cell time-series by their area-fraction weights; ``target_unit``
    (e.g. ``"m3/j"``) routes the read through ``read_watbal_converted``
    instead of raw ``read_values``. Other kinds ignore both fields.
    """

    kind: str = "polygon_cells"
    id_compartment: Optional[int] = None
    outtype: Optional[str] = None
    param: Optional[str] = None
    syear: Optional[int] = None
    eyear: Optional[int] = None
    id_layer: int = 0
    id_layers: Optional[List[int]] = None
    cutsdate: Optional[str] = None
    cutedate: Optional[str] = None
    polygon: Any = None
    polygon_crs: Any = None
    cell_ids: Optional[List[int]] = None
    weighted: bool = False
    target_unit: Optional[str] = None
    # Cell-resolution selector for ``kind="area_values"`` polygon masks.
    # ``"single_layer"`` (default) resolves cells against the single-layer mesh
    # (``_resolve_mesh_gdf(..., id_layer)``) keyed on the per-layer GIS id —
    # WATBAL behaviour, byte-identical. ``"outcropping"`` resolves against the
    # cross-layer aquifer outcropping mesh keyed on the global ``id_abs`` — the
    # correct AQ-recharge free surface spanning whichever layer is exposed.
    # A plain string keeps the typed mask surface serializable for the server.
    resolution: str = "single_layer"
    # Pre-fetched time-series carriers for the boundary-flux kinds.
    # ``boundary_hyd_flux`` needs the full HYD discharge matrix; the L1
    # operations_client fetches it before calling mask() and threads it here so
    # the dispatcher never needs to call back up to L1 or re-read from disk.
    # ``boundary_aq_flux`` needs one ValuesResponse per AQ face direction
    # (keyed by direction name, e.g. ``"N"``, ``"S"``, ``"E"``, ``"W"``).
    # Both default to None; non-boundary-flux kinds ignore them entirely.
    q_response: Optional[Any] = None
    face_responses: Optional[Dict[str, Any]] = None
    # The boundary_aq BoundaryFluxResponse, threaded into boundary_aq_flux so
    # the flux pass reuses the multi-layer boundary faces / edges instead of
    # recomputing them. Typed Any (like q_response / face_responses) because it
    # carries a response dataclass, not a bare mapping.
    face_orientations: Optional[Any] = None


@dataclass
class AssembleRequest:
    """Inputs for ``HydrologicalTwin.assemble(kind=...)``.

    ``assemble`` is shape-only: it turns already-fetched per-key blocks into a
    serialization-ready payload (a :class:`CompartmentBundleResult`) that a
    subsequent ``twin.export(kind="geopackage", ...)`` writes to disk. It never
    fetches/masks and never touches disk itself.

    ``kind`` is the only required field; the rest are optional so the same
    request shape can serve future kinds. For ``kind="compartment_bundle"``:

    - ``label`` — basename token (e.g. ``"InternalValues"``); L3 composes
      ``{area_name}_{label}_{syear}_{eyear}.gpkg``.
    - ``compartment_blocks`` — the generic per-key block mapping
      ``{key: (rows_gdf, {series_key: ValuesResponse}, totals)}``.
    - ``output_dir`` — the directory the composed ``gpkg_path`` lives in.
    - ``source_run`` — a twin-derived value (the caller passes
      ``twin.out_caw_directory``) so L3 needs no upward import.

    For ``kind="boundary_aq_layers"`` (shape-only grouping of AQ boundary edges
    into one GeoDataFrame per aquifer layer):

    - ``edge_geometries`` — ``{cell_id: merged_edge_geometry}`` from the
      ``boundary_aq`` response.
    - ``cell_layer_ids`` — ``{cell_id: id_layer}`` (0-based) from the same
      response, tagging each boundary cell with its aquifer layer.
    - ``crs`` — the CRS the per-layer GeoDataFrames are built in.
    - ``face_directions`` — ``{cell_id: [direction, ...]}`` from the same
      response, used to format the per-cell ``faces`` cardinal-direction column.
    - ``face_sources`` — ``{cell_id: {direction: {"sign", "outside_ids"}}}`` from
      the same response, used to format the per-cell ``outside_ids`` coarse-cell
      provenance column (empty for cells with no ``EXT_cell`` face).
    """

    kind: str = "compartment_bundle"
    label: Optional[str] = None
    compartment_blocks: Optional[Mapping] = None
    output_dir: Optional[str] = None
    area_name: Optional[str] = None
    syear: Optional[int] = None
    eyear: Optional[int] = None
    polygon: Any = None
    polygon_crs: Any = None
    weighted: bool = False
    source_run: Optional[str] = None
    # Extra flat columns merged into every provenance row (compartment_bundle),
    # e.g. the AQ boundary-flux sign convention. None leaves rows unchanged.
    provenance_extra: Optional[Mapping[str, Any]] = None
    # Inputs for kind="boundary_aq_layers".
    edge_geometries: Optional[Mapping[Any, Any]] = None
    cell_layer_ids: Optional[Mapping[Any, int]] = None
    crs: Any = None
    face_directions: Optional[Mapping[Any, Any]] = None
    face_sources: Optional[Mapping[Any, Any]] = None


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
    # Volumetric token for kind="volumetric_rescale" (e.g. "m3/j", "m3/mois").
    target_unit: Optional[str] = None


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
    """Inputs for ``HydrologicalTwin.export(kind=...)`` (alpha-2 shape).

    ``kind`` selects a **data file format** (``"npy"`` or ``"geopackage"``),
    not a semantic artefact and never an image type. ``data`` carries the
    primary payload (an ndarray for npy, the ``compartment_blocks`` mapping for
    geopackage) and ``options`` carries kind-specific extras (e.g.
    ``provenance_rows`` / ``unit_override`` for geopackage). The extras ride an
    ``options`` dict rather than ``**kwargs`` so they never collide with the
    facade's ``request=`` coercion idiom.
    """

    kind: str = "npy"
    path: str = ""
    data: Any = None
    options: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extraction and transformation responses
# ---------------------------------------------------------------------------


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
class HydBoundaryResponse:
    reach_ids: List[Any] = field(default_factory=list)
    geometries: List[Any] = field(default_factory=list)
    meta: Optional[Dict[str, Any]] = None


@dataclass
class HydBoundaryFluxResponse:
    """Per-boundary-reach signed discharge time series.

    Q is shape (n_boundary_reaches, n_timesteps); rows aligned with
    reach_ids (sorted ascending). Sign already applied: inflow positive,
    outflow negative.
    """
    reach_ids: List[Any] = field(default_factory=list)
    signs: Dict[Any, int] = field(default_factory=dict)
    Q: Optional[np.ndarray] = None
    dates: Optional[np.ndarray] = None
    meta: Optional[Dict[str, Any]] = None


@dataclass
class BoundaryFluxResponse:
    """Per-(boundary-cell, face-direction) flux time series.

    fluxes is nested: ``fluxes[cell_id][direction]`` is a 1D ndarray of
    length n_timesteps. Sign convention follows CaWaQS data (positive =
    flux entering the cell). Unit conversion (m³/s → m³/d) is left to
    the caller — the response carries raw m³/s data.

    ``cell_layer_ids`` tags each boundary ``cell_id`` with the 0-based
    ``id_layer`` of the aquifer layer it belongs to. The ``boundary_aq`` scan
    visits every layer named in ``id_layers``, and the cross-layer-uniqueness
    guard ensures each ``cell_id`` appears in exactly one layer, so this mapping
    is single-valued. It lets downstream consumers split the merged boundary
    edges back into one surface per aquifer layer. The flux-bearing
    ``boundary_aq_flux`` mask keys on ``cell_id``/direction and never reads it.

    ``face_sources`` is the per-(cell, direction) flux-source map produced by the
    boundary face detection: ``{cell_id: {direction: {"sign": +1 | -1,
    "outside_ids": [id, ...]}}}``. ``sign=+1`` (``INT_cell``, empty
    ``outside_ids``) means read the inside cell's own face flux for that
    direction; ``sign=-1`` (``EXT_cell``) means the inside cell is coarser on that
    side, so its own face is a *blended* net and the flux is instead the negated
    sum of the ``outside_ids`` smaller outside neighbours' opposing faces (see the
    coarse-cell correction in ``dispatch.mask(kind="boundary_aq_flux")``).
    ``boundary_aq`` populates it and threads it to ``boundary_aq_flux``. It
    defaults to an empty mapping, so an equal-resolution mesh (all ``INT_cell``)
    or any existing construction without it reduces to prior own-face behaviour.
    """
    cell_ids: List[Any] = field(default_factory=list)
    face_directions: Dict[Any, List[str]] = field(default_factory=dict)
    edge_geometries: Dict[Any, Any] = field(default_factory=dict)
    fluxes: Dict[Any, Dict[str, np.ndarray]] = field(default_factory=dict)
    cell_layer_ids: Dict[Any, int] = field(default_factory=dict)
    face_sources: Dict[Any, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    dates: Optional[np.ndarray] = None
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


@dataclass
class CompartmentBundleResult:
    """Serialization-ready payload from ``assemble(kind="compartment_bundle")``.

    Constructed at L2 (``dispatch.assemble`` wraps the plain 4-tuple returned by
    the L3 :func:`build_compartment_bundle`) and consumed by L1
    ``operations_client``. L3 never names this type, so the import edge stays
    downward only. ``gpkg_path`` is a *composed* path string — no file exists at
    it until a later ``twin.export(kind="geopackage", ...)`` writes it.
    """

    gpkg_path: str
    compartment_blocks: Mapping
    provenance_rows: list
    unit_override: Mapping


@dataclass
class BoundaryAqLayersResult:
    """Per-aquifer-layer borders payload from ``assemble(kind="boundary_aq_layers")``.

    Constructed at L2 (``dispatch.assemble`` wraps the plain list returned by the
    pure L3 :func:`build_boundary_aq_layers`) and consumed by L1
    ``operations_client``. L3 never names this type, so the import edge stays
    downward only. Shape-only: the GeoDataFrames live in memory, no file is
    written.

    ``entries`` is an ordered ``[(id_layer, gdf), ...]`` list — one GeoDataFrame
    per aquifer layer that has boundary cells, ascending by ``id_layer``. Each
    ``gdf`` carries a ``cell_id`` column, a ``faces`` cardinal-direction column,
    and the cells' merged boundary-edge geometry. Layers the polygon does not
    reach are absent (silent skip); an empty input yields an empty list.

    ``faces_by_cell`` is the flat ``{cell_id: faces_str}`` map over every boundary
    cell — the same comma-separated cardinal-direction string the geometry rows
    carry — produced at the single L3 formatting site so a caller can annotate the
    GeoPackage ``daily_values`` surface without re-formatting (design D5).

    ``outside_ids_by_cell`` is the flat ``{cell_id: outside_ids_str}`` map over
    every boundary cell — comma-joined ids of the smaller outside neighbours a
    coarse cell's flux was sourced from (across all that cell's ``EXT_cell``
    faces), empty for a cell whose faces are all ``INT_cell`` — produced at the
    same single L3 formatting site so the GeoPackage ``daily_values`` coarse-cell
    provenance column is self-describing without L1 re-formatting (design D6).
    """

    entries: List[tuple] = field(default_factory=list)
    faces_by_cell: Dict[Any, str] = field(default_factory=dict)
    outside_ids_by_cell: Dict[Any, str] = field(default_factory=dict)
