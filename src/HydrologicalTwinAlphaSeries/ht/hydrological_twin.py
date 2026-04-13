from __future__ import annotations

import os
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject
from HydrologicalTwinAlphaSeries.config.constants import obs_config
from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
from HydrologicalTwinAlphaSeries.services.Manage import Manage
from HydrologicalTwinAlphaSeries.services.Renderer import Renderer
from HydrologicalTwinAlphaSeries.services.Vec_Operator import Comparator, Extractor, Operator
from HydrologicalTwinAlphaSeries.tools.spatial_utils import verify_crs_match

from .api_types import (
    ALLOWED_TRANSITIONS,
    MINIMUM_STATE,
    CompartmentInfo,
    DescribeRequest,
    ExportRequest,
    ExportResult,
    ExtractRequest,
    ExtractResult,
    ExtractValuesResponse,
    FacadeDescription,
    FacadeMethod,
    InvalidStateError,
    LayerInfo,
    LoadCompartmentRequest,
    LoadDirectories,
    LoadGeometrySource,
    LoadObservationSource,
    LoadPeriod,
    LoadRequest,
    ObservationInfo,
    ObservationsResponse,
    RenderRequest,
    RenderResult,
    SpatialAverageResponse,
    TemporalOpResponse,
    TransformRequest,
    TransformResult,
    TwinDescription,
    TwinState,
)
from .persistence import HTPersistenceMixin

SUPPORTED_EXTRACT_KINDS = [
    "simulation_matrix",
    "observations",
    "sim_obs_bundle",
    "spatial_map",
    "catchment_cells",
    "aquifer_outcropping",
    "aq_balance_inputs",
]
SUPPORTED_TRANSFORM_KINDS = [
    "temporal_aggregation",
    "performance_criteria",
    "aggregated_budget",
    "hydrological_regime",
    "runoff_ratio",
    "interlayer_exchanges",
]
SUPPORTED_RENDER_KINDS = ["budget", "regime", "sim_obs_pdf", "sim_obs_interactive"]
SUPPORTED_EXPORT_KINDS = ["pickle"]
SUPPORTED_OUTPUTS = ["numpy", "plot", "pickle", "geodataframe"]
TRANSITIONAL_METHODS = [
    "register_compartment",
    "get_compartment_info",
    "get_layer_info",
    "get_all_layers",
    "get_observation_info",
    "extract_values",
    "read_observations",
    "_prepare_sim_obs_data",
    "build_watbal_spatial_gdf",
    "build_effective_rainfall_gdf",
    "build_aq_spatial_gdf",
    "build_aquifer_outcropping",
    "compute_performance_stats",
    "compute_budget_variable",
    "compute_hydrological_regime",
    "render_budget_barplot",
    "render_hydrological_regime",
    "render_sim_obs_pdf",
    "render_sim_obs_interactive",
]


class _StaticCompartmentProvider:
    def __init__(self, compartment: Compartment) -> None:
        self._compartment = compartment

    def build_compartment(self, request: LoadCompartmentRequest, twin: Any) -> Compartment:
        return self._compartment


class HydrologicalTwin(HTPersistenceMixin):
    """Monolithic backend facade for CaWaQS-ViZ.

    This class is the ONLY backend entry point that the QGIS interface should use.

    ``Compartment`` is the **primary domain aggregate**: all public operations
    flow through compartments, never through low-level artifacts (meshes,
    observations, extraction points) directly.

    Architecture follows the six-layer HydroTwin ontology:
        L1  Model Layer         — compartment & mesh metadata
        L2  Data Layer          — observations, simulations I/O
        L3  Estimation Layer    — comparison, filtering, Bayesian inference
        L4  Analysis Layer      — temporal & spatial transformations, extraction
        L5  Cartographic Layer  — visualization & spatial representation
        L6  Git-Synchronized Registry — identity, provenance, versioning

    Lifecycle states::

        EMPTY → CONFIGURED → LOADED → READY

    Macro-methods (public API, ≤ 8)::

        configure, load, describe, extract, transform, render, export
    """

    def __init__(
        self,
        config_geom: Optional[ConfigGeometry] = None,
        config_proj: Optional[ConfigProject] = None,
        out_caw_directory: Optional[str] = None,
        obs_directory: Optional[str] = None,
        temp_directory: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Construct a HydrologicalTwin instance.

        Parameters
        ----------
        config_geom : ConfigGeometry, optional
            Geometry / resolution configuration (as already used by Compartment).
            When provided together with *config_proj*, the twin starts in
            ``CONFIGURED`` state.
        config_proj : ConfigProject, optional
            Project-level configuration (includes ``regime``).
        out_caw_directory : str, optional
            Root directory containing CaWaQS outputs.
        obs_directory : str, optional
            Root directory containing observations (.dat) files.
        temp_directory : Optional[str]
            Directory to store temporary numpy/CSV/post-processing files.
            If None, defaults to ``out_caw_directory``.
        metadata : Optional[dict]
            Optional metadata dictionary attached to the twin.
        """
        # Internal state
        self._state: TwinState = TwinState.EMPTY

        self.config_geom: Optional[ConfigGeometry] = None
        self.config_proj: Optional[ConfigProject] = None
        self.out_caw_directory: Optional[str] = None
        self.obs_directory: Optional[str] = None
        self.temp_directory: Optional[str] = None

        self.metadata: Dict[str, Any] = metadata or {}

        # Compartments indexed by CaWaQS compartment ID (int)
        self.compartments: Dict[int, Compartment] = {}

        # Domain services reusing existing logic
        self.temporal = Manage.Temporal()
        self.spatial = Manage.Spatial()
        self.budget = Manage.Budget()

        # Auto-configure if full config provided at construction time
        if config_geom is not None and config_proj is not None:
            self.configure(
                config_geom=config_geom,
                config_proj=config_proj,
                out_caw_directory=out_caw_directory or "",
                obs_directory=obs_directory or "",
                temp_directory=temp_directory,
            )

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    @property
    def state(self) -> TwinState:
        """Current lifecycle state."""
        return self._state

    def _transition_to(self, target: TwinState) -> None:
        """Advance to *target* state, raising on illegal transitions."""
        if target not in ALLOWED_TRANSITIONS.get(self._state, frozenset()):
            raise InvalidStateError(
                f"Cannot transition from {self._state.value} to {target.value}. "
                f"Allowed: {sorted(s.value for s in ALLOWED_TRANSITIONS[self._state])}"
            )
        self._state = target

    def _require_state(self, method_name: str) -> None:
        """Raise :class:`InvalidStateError` if *method_name* is not callable yet."""
        minimum = MINIMUM_STATE.get(method_name)
        if minimum is None:
            return
        state_order = [TwinState.EMPTY, TwinState.CONFIGURED, TwinState.LOADED, TwinState.READY]
        if state_order.index(self._state) < state_order.index(minimum):
            raise InvalidStateError(
                f"'{method_name}' requires state {minimum.value} or later, "
                f"but current state is {self._state.value}."
            )

    def _warn_deprecated_helper(self, helper_name: str, replacement: str) -> None:
        warnings.warn(
            f"'{helper_name}' is deprecated and kept only for compatibility. "
            f"Use '{replacement}' with a typed request instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def _build_compartment_info(self, id_compartment: int) -> CompartmentInfo:
        comp = self.get_compartment(id_compartment)
        observation_layers: List[str] = []
        observation_units: Dict[str, str] = {}
        if comp.obs is not None:
            observation_layers.append(comp.obs.layer_gis_name)
            observation_units[comp.obs.obs_type] = "l/s" if comp.compartment == "HYD" else ""
        return CompartmentInfo(
            id_compartment=id_compartment,
            stable_id=str(id_compartment),
            name=comp.compartment,
            layers_gis_names=list(comp.layers_gis_names),
            resolutions=list(comp.layers_gis_names),
            n_layers=len(comp.mesh.mesh),
            n_cells=comp.mesh.ncells,
            cell_ids=np.array(comp.mesh.getCellIdVector()),
            out_caw_path=comp.out_caw_path,
            regime=comp.regime,
            observation_layers=observation_layers,
            observation_units=observation_units,
            supported_outputs=list(SUPPORTED_OUTPUTS),
            extract_kinds=list(SUPPORTED_EXTRACT_KINDS),
            transform_kinds=list(SUPPORTED_TRANSFORM_KINDS),
            render_kinds=list(SUPPORTED_RENDER_KINDS),
        )

    def _get_layer_info_impl(self, id_compartment: int, id_layer: int) -> LayerInfo:
        comp = self.get_compartment(id_compartment)
        layer = comp.mesh.mesh[id_layer]
        return LayerInfo(
            id_layer=id_layer,
            n_cells=layer.ncells,
            cell_ids=np.array([cell.id for cell in layer.layer]),
            cell_areas=np.array([cell.area for cell in layer.layer]),
            cell_geometries=[cell.geometry for cell in layer.layer],
            layer_gis_name=(
                comp.layers_gis_names[id_layer]
                if id_layer < len(comp.layers_gis_names)
                else ""
            ),
            crs=layer.crs,
        )

    def _get_observation_info_impl(self, id_compartment: int) -> Optional[ObservationInfo]:
        comp = self.get_compartment(id_compartment)
        if comp.obs is None:
            return None
        obs = comp.obs
        return ObservationInfo(
            id_compartment=id_compartment,
            obs_type=obs.obs_type,
            n_points=obs.n_obs,
            layer_gis_name=obs.layer_gis_name,
            point_names=[p.name for p in obs.obs_points],
            point_ids=[p.id_point for p in obs.obs_points],
            cell_ids=[p.id_cell for p in obs.obs_points],
            layer_ids=[p.id_layer for p in obs.obs_points],
            geometries=[p.geometry for p in obs.obs_points],
            mesh_ids=[p.id_mesh for p in obs.obs_points],
        )

    def _materialize_load_request(self, request: LoadRequest) -> Dict[int, Compartment]:
        if request.kind != "compartments":
            raise ValueError(f"Unknown load kind: {request.kind!r}")
        built: Dict[int, Compartment] = {}
        for compartment_request in request.compartments:
            geometry_source = compartment_request.geometry_source
            provider = geometry_source.provider
            if geometry_source.kind != "provider" or provider is None:
                raise ValueError(
                    "load() currently supports geometry_source.kind='provider' "
                    "with a public provider."
                )
            compartment = provider.build_compartment(compartment_request, self)
            if not isinstance(compartment, Compartment):
                raise TypeError(
                    "Compartment providers must return Compartment instances, "
                    f"got {type(compartment).__name__}"
                )
            built[compartment_request.id_compartment] = compartment
        return built

    def _extract_values_impl(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        id_layer: int = 0,
        cutsdate: Optional[str] = None,
        cutedate: Optional[str] = None,
    ) -> ExtractValuesResponse:
        comp = self.get_compartment(id_compartment)

        sim_matrix = self.temporal.readSimData(
            compartment=comp,
            outtype=outtype,
            param=param,
            id_layer=id_layer,
            syear=syear,
            eyear=eyear,
            tempDirectory=self.temp_directory,
        )

        start_date = datetime.strptime(f"{syear}-08-01", "%Y-%m-%d")
        end_date = datetime.strptime(f"{eyear}-08-01", "%Y-%m-%d")
        dates = np.arange(np.datetime64(start_date), np.datetime64(end_date), dtype="datetime64[D]")
        if sim_matrix.shape[1] != len(dates):
            min_len = min(sim_matrix.shape[1], len(dates))
            sim_matrix = sim_matrix[:, :min_len]
            dates = dates[:min_len]

        if cutsdate is not None or cutedate is not None:
            d_start = np.datetime64(cutsdate) if cutsdate else dates[0]
            d_end = np.datetime64(cutedate) if cutedate else dates[-1]
            mask = (dates >= d_start) & (dates <= d_end)
            sim_matrix = sim_matrix[:, mask]
            dates = dates[mask]

        return ExtractValuesResponse(
            data=sim_matrix,
            dates=dates,
            meta={
                "id_compartment": id_compartment,
                "outtype": outtype,
                "param": param,
                "syear": syear,
                "eyear": eyear,
                "id_layer": id_layer,
                "cutsdate": cutsdate,
                "cutedate": cutedate,
            },
        )

    def _read_observations_impl(
        self,
        id_compartment: int,
        syear: int,
        eyear: int,
    ) -> ObservationsResponse:
        comp = self.get_compartment(id_compartment)
        cfg = obs_config[id_compartment]

        result = self.temporal.readObsData(
            compartment=comp,
            id_col_data=cfg["id_col_data"],
            id_col_time=cfg["id_col_time"],
            sdate=syear,
            edate=eyear,
        )

        if result is None:
            return ObservationsResponse(
                data=np.empty((0, 0)),
                dates=np.array([], dtype="datetime64[D]"),
                meta={
                    "id_compartment": id_compartment,
                    "syear": syear,
                    "eyear": eyear,
                    "obs_point_ids": [],
                    "n_points": 0,
                },
            )

        data, dates, point_ids = result
        return ObservationsResponse(
            data=data,
            dates=dates,
            meta={
                "id_compartment": id_compartment,
                "syear": syear,
                "eyear": eyear,
                "obs_point_ids": point_ids,
                "n_points": len(point_ids),
            },
        )

    def _prepare_sim_obs_data_impl(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        simsdate: int,
        simedate: int,
        plotstart: str = None,
        plotend: str = None,
        id_layer: int = 0,
        aggr: Union[None, float, str] = None,
        compute_criteria: bool = False,
        criteria_metrics: List[str] = None,
        crit_start: str = None,
        crit_end: str = None,
        obs_unit: str = None,
    ) -> dict:
        extract_result = self.extract(
            ExtractRequest(
                kind="simulation_matrix",
                id_compartment=id_compartment,
                outtype=outtype,
                param=param,
                syear=simsdate,
                eyear=simedate,
                options={
                    "id_layer": id_layer,
                    "cutsdate": plotstart,
                    "cutedate": plotend,
                },
            )
        )
        obs_result = self.extract(
            ExtractRequest(
                kind="observations",
                id_compartment=id_compartment,
                syear=simsdate,
                eyear=simedate,
            )
        )
        sim_response = extract_result.payload
        obs_response = obs_result.payload
        comp = self.get_compartment(id_compartment)

        if comp.obs is not None:
            for layer in comp.mesh.mesh.values():
                verify_crs_match(
                    comp.obs.crs,
                    layer.crs,
                    context="observations vs mesh spatial linkage",
                )

        sim_dates = sim_response.dates
        obs_dates = obs_response.dates
        obs_points_data = []
        if comp.obs is not None:
            for i, obs_point in enumerate(comp.obs.obs_points):
                sim_vals = sim_response.data[obs_point.id_cell - 1, :]
                obs_vals = (
                    obs_response.data[i, :]
                    if i < obs_response.data.shape[0]
                    else np.full(len(obs_dates), np.nan)
                )
                obs_points_data.append(
                    {
                        "name": obs_point.name,
                        "id_cell": obs_point.id_cell,
                        "id_layer": obs_point.id_layer,
                        "id_point": obs_point.id_point,
                        "sim": sim_vals,
                        "obs": obs_vals,
                    }
                )

        if comp.compartment == "HYD" and obs_unit is not None:
            for pt in obs_points_data:
                if obs_unit == "m3/s":
                    pt["obs"] = pt["obs"] * 1e-3
                elif obs_unit == "l/s":
                    pt["sim"] = pt["sim"] * 1e3

        if len(obs_dates) > 0 and plotstart is not None and plotend is not None:
            d_start = np.datetime64(plotstart)
            d_end = np.datetime64(plotend)
            obs_mask = (obs_dates >= d_start) & (obs_dates <= d_end)
            obs_dates = obs_dates[obs_mask]
            for pt in obs_points_data:
                pt["obs"] = pt["obs"][obs_mask]

        if aggr is not None:
            for pt in obs_points_data:
                obs = pt["obs"]
                if aggr == "mean":
                    pt["obs"] = np.full_like(obs, np.nanmean(obs))
                elif aggr == "min":
                    pt["obs"] = np.full_like(obs, np.nanmin(obs))
                elif aggr == "max":
                    pt["obs"] = np.full_like(obs, np.nanmax(obs))
                elif isinstance(aggr, float):
                    pt["obs"] = np.full_like(obs, np.nanquantile(obs, aggr))

        if compute_criteria and obs_points_data:
            for pt in obs_points_data:
                sim_for_crit = pt["sim"]
                obs_for_crit = pt["obs"]
                if crit_start is not None and crit_end is not None:
                    cs = np.datetime64(crit_start)
                    ce = np.datetime64(crit_end)
                    sim_mask = (sim_dates >= cs) & (sim_dates <= ce)
                    obs_mask = (obs_dates >= cs) & (obs_dates <= ce)
                    sim_for_crit = sim_for_crit[sim_mask]
                    obs_for_crit = obs_for_crit[obs_mask]
                    n = min(len(sim_for_crit), len(obs_for_crit))
                    sim_for_crit = sim_for_crit[:n]
                    obs_for_crit = obs_for_crit[:n]
                criteria_result = self.transform(
                    TransformRequest(
                        kind="performance_criteria",
                        payload={"sim": sim_for_crit, "obs": obs_for_crit},
                        options={"metrics": criteria_metrics},
                    )
                )
                pt["criteria"] = criteria_result.payload

        ext_points_data = []
        if comp.extraction is not None:
            for ext_point in comp.extraction.ext_point:
                sim_vals = sim_response.data[ext_point.id_cell - 1, :]
                ext_points_data.append(
                    {
                        "name": ext_point.name,
                        "id_cell": ext_point.id_cell,
                        "id_layer": ext_point.id_layer,
                        "sim": sim_vals,
                    }
                )

        return {
            "sim_dates": sim_dates,
            "obs_dates": obs_dates,
            "compartment_name": comp.compartment,
            "obs_points": obs_points_data,
            "ext_points": ext_points_data,
        }

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  MACRO-METHODS — canonical public API                        ║
    # ╚════════════════════════════════════════════════════════════════╝

    def configure(
        self,
        config_geom: ConfigGeometry,
        config_proj: ConfigProject,
        out_caw_directory: str,
        obs_directory: str,
        temp_directory: Optional[str] = None,
    ) -> None:
        """Attach project and geometry configuration.

        Transitions: EMPTY → CONFIGURED.
        """
        self._require_state("configure")
        self.config_geom = config_geom
        self.config_proj = config_proj
        self.out_caw_directory = out_caw_directory
        self.obs_directory = obs_directory
        self.temp_directory = temp_directory or out_caw_directory
        self._transition_to(TwinState.CONFIGURED)

    def load(
        self,
        request: Optional[LoadRequest] = None,
        compartments: Optional[Dict[int, Compartment]] = None,
        **kwargs: Any,
    ) -> None:
        """Register compartments and mesh data.

        Transitions: CONFIGURED → LOADED.

        """
        self._require_state("load")
        if request is None:
            if compartments is not None:
                self._warn_deprecated_helper("load(compartments=...)", "load(LoadRequest(...))")
                request = LoadRequest(
                    compartments=[
                        LoadCompartmentRequest(
                            id_compartment=id_compartment,
                            stable_id=str(id_compartment),
                            geometry_source=LoadGeometrySource(
                                kind="provider",
                                provider=_StaticCompartmentProvider(compartment),
                            ),
                            observation_source=LoadObservationSource(kind="attached"),
                        )
                        for id_compartment, compartment in compartments.items()
                    ],
                    period=LoadPeriod(
                        start_year=getattr(self.config_proj, "startSim", 0),
                        end_year=getattr(self.config_proj, "endSim", 0),
                    ),
                    directories=LoadDirectories(
                        out_caw_directory=self.out_caw_directory,
                        obs_directory=self.obs_directory,
                        temp_directory=self.temp_directory,
                    ),
                )
            else:
                request = LoadRequest()

        if request.directories is not None:
            if request.directories.out_caw_directory is not None:
                self.out_caw_directory = request.directories.out_caw_directory
            if request.directories.obs_directory is not None:
                self.obs_directory = request.directories.obs_directory
            if request.directories.temp_directory is not None:
                self.temp_directory = request.directories.temp_directory
        if request.period is not None:
            self.metadata["period"] = {
                "start_year": request.period.start_year,
                "end_year": request.period.end_year,
            }
        if request.metadata:
            self.metadata.update(request.metadata)

        self.compartments = self._materialize_load_request(request)
        self._transition_to(TwinState.LOADED)

    def register_compartment(
        self,
        id_compartment: int,
        compartment: Compartment,
    ) -> None:
        """Register a single compartment into the twin.

        Can be called repeatedly to add compartments one at a time after
        ``load()`` has been called.  Requires state LOADED or later.

        Parameters
        ----------
        id_compartment : int
            CaWaQS compartment identifier.
        compartment : Compartment
            Fully constructed Compartment aggregate.

        Raises
        ------
        TypeError
            If *compartment* is not a :class:`Compartment` instance.
        """
        self._warn_deprecated_helper("register_compartment", "load(LoadRequest(...))")
        self._require_state("register_compartment")
        if not isinstance(compartment, Compartment):
            raise TypeError(
                f"Expected a Compartment instance, got {type(compartment).__name__}"
            )
        self.compartments[id_compartment] = compartment

    def describe(self, request: Optional[DescribeRequest] = None, **kwargs: Any) -> TwinDescription:
        """Return a structured description of the twin.

        Requires state LOADED.
        """
        self._require_state("describe")
        request = request or DescribeRequest()
        if request.kind != "catalog":
            raise ValueError(f"Unknown describe kind: {request.kind!r}")
        return TwinDescription(
            kind=request.kind,
            state=self._state.value,
            n_compartments=len(self.compartments),
            compartments=[self._build_compartment_info(cid) for cid in self.compartments],
            supported_outputs=list(SUPPORTED_OUTPUTS),
            extract_kinds=list(SUPPORTED_EXTRACT_KINDS),
            transform_kinds=list(SUPPORTED_TRANSFORM_KINDS),
            render_kinds=list(SUPPORTED_RENDER_KINDS),
            export_kinds=list(SUPPORTED_EXPORT_KINDS),
            transitional_methods=list(TRANSITIONAL_METHODS),
            metadata=self.metadata,
        )

    def describe_api_facade(self) -> FacadeDescription:
        """Describe the explicit HydrologicalTwin facade for frontend consumers.

        This documents the stable consumer contract and the temporary
        compatibility wrappers preserved for the CWV migration.
        """
        return FacadeDescription(
            entrypoint="HydrologicalTwin",
            primary_consumer="cawaqsviz",
            lifecycle=[state.value for state in TwinState],
            macro_methods=[
                FacadeMethod(
                    name="configure",
                    level="macro",
                    purpose="Attach project and geometry configuration.",
                ),
                FacadeMethod(
                    name="load",
                    level="macro",
                    purpose="Load typed compartment requests, period and directory inputs.",
                ),
                FacadeMethod(
                    name="describe",
                    level="macro",
                    purpose="Expose the frontend catalog of compartments and capabilities.",
                ),
                FacadeMethod(
                    name="extract",
                    level="macro",
                    purpose="Run public extraction workflows through typed requests.",
                ),
                FacadeMethod(
                    name="transform",
                    level="macro",
                    purpose="Transform extracted public payloads into business calculations.",
                ),
                FacadeMethod(
                    name="render",
                    level="macro",
                    purpose="Produce final artefacts from typed rendering requests.",
                ),
                FacadeMethod(
                    name="export",
                    level="macro",
                    purpose="Export persistent snapshots and artefacts through typed requests.",
                ),
            ],
            transitional_methods=[
                FacadeMethod(
                    name="register_compartment",
                    level="compatibility",
                    purpose="Temporary CWV wrapper for incremental loading.",
                ),
                FacadeMethod(
                    name=(
                        "get_compartment_info / get_layer_info / get_all_layers / "
                        "get_observation_info"
                    ),
                    level="compatibility",
                    purpose="Temporary metadata wrappers superseded by describe(kind='catalog').",
                ),
                FacadeMethod(
                    name="extract_values / read_observations / _prepare_sim_obs_data",
                    level="compatibility",
                    purpose="Temporary data wrappers superseded by extract(kind=...).",
                ),
                FacadeMethod(
                    name="compute_* / build_* / render_* specifics",
                    level="compatibility",
                    purpose=(
                        "Temporary wrappers superseded by transform(kind=...) "
                        "and render(kind=...)."
                    ),
                ),
            ],
        )

    def extract(
        self,
        request: Optional[ExtractRequest] = None,
        id_compartment: Optional[int] = None,
        outtype: Optional[str] = None,
        param: Optional[str] = None,
        syear: Optional[int] = None,
        eyear: Optional[int] = None,
        **kwargs: Any,
    ) -> Union[ExtractResult, ExtractValuesResponse]:
        """Extract simulation data (macro-method).

        Requires state LOADED.
        """
        self._require_state("extract")
        legacy_mode = request is None
        request = request or ExtractRequest(
            kind="simulation_matrix",
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            syear=syear,
            eyear=eyear,
            options=kwargs,
        )
        kind = request.kind
        options = dict(request.options)
        if kind == "simulation_matrix":
            payload = self._extract_values_impl(
                id_compartment=request.id_compartment,
                outtype=request.outtype,
                param=request.param,
                syear=request.syear,
                eyear=request.eyear,
                id_layer=options.get("id_layer", 0),
                cutsdate=options.get("cutsdate"),
                cutedate=options.get("cutedate"),
            )
        elif kind == "observations":
            payload = self._read_observations_impl(
                id_compartment=request.id_compartment,
                syear=request.syear,
                eyear=request.eyear,
            )
        elif kind == "sim_obs_bundle":
            payload = self._prepare_sim_obs_data_impl(
                id_compartment=request.id_compartment,
                outtype=request.outtype,
                param=request.param,
                simsdate=request.syear,
                simedate=request.eyear,
                plotstart=options.get("plotstart"),
                plotend=options.get("plotend"),
                id_layer=options.get("id_layer", 0),
                aggr=options.get("aggr"),
                compute_criteria=options.get("compute_criteria", False),
                criteria_metrics=options.get("criteria_metrics"),
                crit_start=options.get("crit_start"),
                crit_end=options.get("crit_end"),
                obs_unit=options.get("obs_unit"),
            )
        elif kind == "spatial_map":
            payload = {
                "compartment": self._build_compartment_info(request.id_compartment),
                "layer": self._get_layer_info_impl(
                    request.id_compartment,
                    options.get("id_layer", 0),
                ),
                "values": self._extract_values_impl(
                    id_compartment=request.id_compartment,
                    outtype=request.outtype,
                    param=request.param,
                    syear=request.syear,
                    eyear=request.eyear,
                    id_layer=options.get("id_layer", 0),
                    cutsdate=options.get("cutsdate"),
                    cutedate=options.get("cutedate"),
                ),
            }
        elif kind == "catchment_cells":
            payload = self.extract_area_values(
                id_compartment=request.id_compartment,
                outtype=request.outtype,
                param=request.param,
                syear=request.syear,
                eyear=request.eyear,
                spatial_operator="catchment_cells",
                **options,
            )
        elif kind == "aquifer_outcropping":
            payload = np.array(
                [
                    cell.id
                    for cell in self.spatial.buildAqOutcropping(
                        exd=type(
                            "_ExdStub",
                            (),
                            {"post_process_directory": options.get("save_directory", "")},
                        )(),
                        aq_compartment=self.get_compartment(request.id_compartment),
                        save=options.get("save_directory") is not None,
                    )
                ]
            )
        elif kind == "aq_balance_inputs":
            payload = {
                name: self._extract_values_impl(
                    id_compartment=request.id_compartment,
                    outtype=spec["outtype"],
                    param=spec["param"],
                    syear=request.syear,
                    eyear=request.eyear,
                    id_layer=spec.get("id_layer", 0),
                    cutsdate=spec.get("cutsdate"),
                    cutedate=spec.get("cutedate"),
                )
                for name, spec in options.get("variables", {}).items()
            }
        else:
            raise ValueError(f"Unknown extract kind: {kind!r}")
        result = ExtractResult(kind=kind, payload=payload, meta={"kind": kind})
        return payload if legacy_mode else result

    def transform(
        self,
        request: Optional[TransformRequest] = None,
        arr: Optional[np.ndarray] = None,
        dates: Optional[np.ndarray] = None,
        frequency: Optional[str] = None,
        agg_dimension: Union[str, float] = "mean",
        **kwargs: Any,
    ) -> Union[TransformResult, TemporalOpResponse]:
        """Apply temporal aggregation (macro-method).

        Requires state LOADED.
        """
        self._require_state("transform")
        legacy_mode = request is None
        request = request or TransformRequest(
            kind="temporal_aggregation",
            payload={"arr": arr, "dates": dates},
            options={"frequency": frequency, "agg_dimension": agg_dimension, **kwargs},
        )
        options = dict(request.options)
        if request.kind == "temporal_aggregation":
            payload = self.apply_temporal_operator(
                arr=request.payload["arr"],
                dates=request.payload["dates"],
                column_names=options.get("column_names"),
                agg_dimension=options.get("agg_dimension", "mean"),
                frequency=options.get("frequency"),
                pluriennial=options.get("pluriennial", False),
                year_end_month=options.get("year_end_month", 12),
            )
        elif request.kind == "performance_criteria":
            payload = Comparator().calc_performance_metrics(
                sim=request.payload["sim"],
                obs=request.payload["obs"],
                metrics=options.get("metrics"),
            )
        elif request.kind == "aggregated_budget":
            payload = self.budget.calcInteranualBVariableNumpy(
                data=request.payload["data"],
                param=options["param"],
                out_folder="",
                agg=options["agg"],
                fz=options["fz"],
                sdate=options["sdate"],
                edate=options["edate"],
                cutsdate=options.get("cutsdate"),
                cutedate=options.get("cutedate"),
                pluriannual=options.get("pluriannual", False),
            )
        elif request.kind == "hydrological_regime":
            payload = self.budget.calcInteranualHVariableNumpy(
                data=request.payload["data"],
                dates=request.payload["dates"],
                compartment=self.get_compartment(options["id_compartment"]),
                output_folder=options["output_folder"],
                output_name=options["output_name"],
            )
        elif request.kind == "runoff_ratio":
            numerator = np.asarray(request.payload["runoff"], dtype=float)
            denominator = np.asarray(request.payload["rainfall"], dtype=float)
            payload = np.divide(
                numerator,
                denominator,
                out=np.full_like(numerator, np.nan, dtype=float),
                where=denominator != 0,
            )
        elif request.kind == "interlayer_exchanges":
            upper = np.asarray(request.payload["upper"], dtype=float)
            lower = np.asarray(request.payload["lower"], dtype=float)
            payload = lower - upper
        else:
            raise ValueError(f"Unknown transform kind: {request.kind!r}")
        result = TransformResult(kind=request.kind, payload=payload, meta={"kind": request.kind})
        return payload if legacy_mode else result

    def render(
        self,
        request: Optional[RenderRequest] = None,
        kind: str = "budget",
        **kwargs: Any,
    ) -> RenderResult:
        """Produce visualizations (macro-method).

        Delegates to the appropriate render helper.  Requires state LOADED.

        Parameters
        ----------
        """
        self._require_state("render")
        request = request or RenderRequest(kind=kind, options=kwargs)
        options = dict(request.options)
        if request.kind == "budget":
            payload = request.payload or {}
            artefacts = Renderer.plot_budget_barplot(
                data_dict=payload["data_dict"],
                plot_title=payload["plot_title"],
                output_folder=options.get("output_folder"),
                output_name=options.get("output_name"),
                yaxis_unit=options.get("yaxis_unit", "mm"),
            )
        elif request.kind == "regime":
            payload = request.payload or {}
            artefacts = Renderer.plot_hydrological_regime(
                data=payload["data"],
                obs_point_names=payload["obs_point_names"],
                month_labels=payload["month_labels"],
                var=payload["var"],
                units=payload["units"],
                savepath=payload["savepath"],
                interactive=options.get("interactive", False),
                staticpng=options.get("staticpng", True),
                staticpdf=options.get("staticpdf", True),
                years=options.get("years"),
            )
        elif request.kind == "sim_obs_pdf":
            payload = request.payload
            if payload is None:
                payload = self.extract(
                    ExtractRequest(
                        kind="sim_obs_bundle",
                        id_compartment=options["id_compartment"],
                        outtype=options["outtype"],
                        param=options["param"],
                        syear=options["simsdate"],
                        eyear=options["simedate"],
                        options={
                            "plotstart": options["plotstartdate"],
                            "plotend": options["plotenddate"],
                            "id_layer": options["id_layer"],
                            "aggr": options.get("aggr"),
                            "compute_criteria": True,
                            "criteria_metrics": [
                                "n_obs",
                                "pbias",
                                "avg_ratio",
                                "rmse",
                                "nash",
                                "kge",
                            ],
                            "crit_start": options.get("crit_start"),
                            "crit_end": options.get("crit_end"),
                            "obs_unit": options["obs_unit"],
                        },
                    )
                ).payload
            sim_dates_idx = pd.DatetimeIndex(payload["sim_dates"].astype("datetime64[D]"))
            obs_dates_idx = pd.DatetimeIndex(payload["obs_dates"].astype("datetime64[D]"))
            sim_columns = {}
            for pt in payload["obs_points"]:
                sim_columns.setdefault(pt["id_cell"], pt["sim"])
            for pt in payload["ext_points"]:
                sim_columns.setdefault(pt["id_cell"], pt["sim"])
            simdf = pd.DataFrame(sim_columns, index=sim_dates_idx)
            obs_df = None
            if payload["obs_points"]:
                obs_df = pd.DataFrame(
                    {pt["id_point"]: pt["obs"] for pt in payload["obs_points"]},
                    index=obs_dates_idx,
                )
            artefacts = Renderer.render_simobs_pdf(
                simdf=simdf,
                obs_df=obs_df,
                obs_points=[
                    {
                        "name": pt["name"],
                        "id_cell": pt["id_cell"],
                        "id_layer": pt["id_layer"],
                        "id_point": pt["id_point"],
                        "criteria": pt.get("criteria"),
                    }
                    for pt in payload["obs_points"]
                ],
                ext_points=[
                    {"name": pt["name"], "id_cell": pt["id_cell"], "id_layer": pt["id_layer"]}
                    for pt in payload["ext_points"]
                ],
                pdf_file_path=os.path.join(
                    options["directory"],
                    (
                        options["name_file"]
                        + "_"
                        + options["plotstartdate"]
                        + "_"
                        + options["plotenddate"]
                        + ".pdf"
                    ),
                ),
                ylabel=options["ylabel"],
                crit_start=options.get("crit_start"),
                crit_end=options.get("crit_end"),
                plotstartdate=options["plotstartdate"],
                plotenddate=options["plotenddate"],
            )
        elif request.kind == "sim_obs_interactive":
            payload = request.payload
            if payload is None:
                payload = self.extract(
                    ExtractRequest(
                        kind="sim_obs_bundle",
                        id_compartment=options["id_compartment"],
                        outtype=options["outtype"],
                        param=options["param"],
                        syear=options["simsdate"],
                        eyear=options["simedate"],
                        options={
                            "plotstart": options["plotstart"],
                            "plotend": options["plotend"],
                            "aggr": options.get("aggr"),
                            "compute_criteria": True,
                            "criteria_metrics": [
                                "n_obs",
                                "avg_ratio",
                                "pbias",
                                "std_ratio",
                                "rmse",
                                "nash",
                                "kge",
                            ],
                            "crit_start": options.get("critstart"),
                            "crit_end": options.get("critend"),
                            "obs_unit": options["obs_unit"],
                        },
                    )
                ).payload
            sim_dates_idx = pd.DatetimeIndex(payload["sim_dates"].astype("datetime64[D]"))
            obs_dates_idx = pd.DatetimeIndex(payload["obs_dates"].astype("datetime64[D]"))
            sim_obs_data = []
            criteria_per_point = []
            for pt in payload["obs_points"]:
                sim_series = pd.Series(pt["sim"], index=sim_dates_idx, name="sim")
                obs_series = pd.Series(pt["obs"], index=obs_dates_idx, name="obs")
                df_sim_obs = pd.concat([sim_series, obs_series], axis=1)
                df_sim_obs = df_sim_obs.loc[options["plotstart"]: options["plotend"]]
                sim_obs_data.append((df_sim_obs, pt["name"]))
                criteria_per_point.append(pt.get("criteria"))
            artefacts = Renderer.render_simobs_interactive(
                sim_obs_data=sim_obs_data,
                ylabel=options["ylabel"],
                df_other_variable=options.get("df_other_variable"),
                other_variable_config=options.get("other_variable_config"),
                out_file_path=options.get("outFilePath"),
                crit_start=options.get("critstart"),
                crit_end=options.get("critend"),
                criteria_per_point=criteria_per_point,
            )
        else:
            raise ValueError(f"Unknown render kind: {request.kind!r}")
        return RenderResult(artefacts=artefacts, meta={"kind": request.kind})

    def export(
        self,
        request: Optional[ExportRequest] = None,
        path: Optional[str] = None,
        fmt: str = "pickle",
        **kwargs: Any,
    ) -> ExportResult:
        """Export data or twin snapshot to disk (macro-method).

        Requires state LOADED.

        Parameters
        ----------
        """
        self._require_state("export")
        request = request or ExportRequest(kind=fmt, path=path, options=kwargs)
        if request.kind == "pickle":
            if request.path is None:
                raise ValueError("'path' is required for pickle export.")
            self.to_pickle(request.path)
        else:
            raise ValueError(f"Unknown export format: {request.kind!r}")
        return ExportResult(path=request.path, meta={"fmt": request.kind})

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L1 — MODEL LAYER  (Compartment & Mesh metadata)             ║
    # ╚════════════════════════════════════════════════════════════════╝

    def get_compartment(self, id_compartment: int) -> Compartment:
        """Return a registered Compartment.

        Raises KeyError if the compartment was not registered at init time.
        """
        if id_compartment not in self.compartments:
            raise KeyError(
                f"Compartment {id_compartment} is not registered. "
                f"Available: {list(self.compartments.keys())}"
            )
        return self.compartments[id_compartment]

    def get_compartment_info(self, id_compartment: int) -> CompartmentInfo:
        """Return a serializable snapshot of compartment metadata."""
        self._warn_deprecated_helper(
            "get_compartment_info",
            "describe(DescribeRequest(kind='catalog'))",
        )
        return self._build_compartment_info(id_compartment)

    def list_compartments(self) -> List[CompartmentInfo]:
        """Return info for all registered compartments."""
        return [self._build_compartment_info(cid) for cid in self.compartments]

    def get_layer_info(self, id_compartment: int, id_layer: int) -> LayerInfo:
        """Return cell data for a specific mesh layer."""
        self._warn_deprecated_helper("get_layer_info", "describe(DescribeRequest(kind='catalog'))")
        return self._get_layer_info_impl(id_compartment, id_layer)

    def get_all_layers(self, id_compartment: int) -> List[LayerInfo]:
        """Return LayerInfo for every layer in a compartment's mesh."""
        self._warn_deprecated_helper("get_all_layers", "describe(DescribeRequest(kind='catalog'))")
        comp = self.get_compartment(id_compartment)
        return [self._get_layer_info_impl(id_compartment, lid) for lid in comp.mesh.mesh]

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L2 — DATA LAYER  (Observations & Simulations I/O)           ║
    # ╚════════════════════════════════════════════════════════════════╝

    def get_observation_info(self, id_compartment: int) -> Optional[ObservationInfo]:
        """Return a serializable snapshot of observation metadata.

        Returns None if the compartment has no observations.
        """
        self._warn_deprecated_helper(
            "get_observation_info",
            "describe(DescribeRequest(kind='catalog'))",
        )
        return self._get_observation_info_impl(id_compartment)

    def extract_values(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        id_layer: int = 0,
        cutsdate: Optional[str] = None,
        cutedate: Optional[str] = None,
    ) -> ExtractValuesResponse:
        """Extract simulated values for a given variable and period (NumPy version)."""
        self._warn_deprecated_helper("extract_values", "extract(ExtractRequest(...))")
        return self.extract(
            ExtractRequest(
                kind="simulation_matrix",
                id_compartment=id_compartment,
                outtype=outtype,
                param=param,
                syear=syear,
                eyear=eyear,
                options={
                    "id_layer": id_layer,
                    "cutsdate": cutsdate,
                    "cutedate": cutedate,
                },
            )
        ).payload
    
    def read_observations(
        self,
        id_compartment: int,
        syear: int,
        eyear: int,
    ) -> ObservationsResponse:
        """Read observation data for all observation points of a compartment.

        Target layer: L2 — Data Layer

        Wraps ``Manage.Temporal.readObsData`` and internalises the
        ``obs_config`` column mapping so callers only need the compartment ID
        and date range.

        Parameters
        ----------
        id_compartment : int
            Compartment ID (must be present in ``obs_config``).
        syear : int
            Start year of simulation period.
        eyear : int
            End year of simulation period.

        Returns
        -------
        ObservationsResponse
            ``data`` shape (n_points, n_timesteps), may contain NaN.
            ``dates`` datetime64 array (n_timesteps,).
            ``meta`` carries obs_point_ids and period info.
        """
        self._warn_deprecated_helper(
            "read_observations",
            "extract(ExtractRequest(kind='observations', ...))",
        )
        return self.extract(
            ExtractRequest(
                kind="observations",
                id_compartment=id_compartment,
                syear=syear,
                eyear=eyear,
            )
        ).payload

    def read_sim_steady(self, id_compartment: int) -> pd.DataFrame:
        """Read steady-state simulation data. Wraps Manage.Temporal.readSimSteady."""
        comp = self.get_compartment(id_compartment)
        return self.temporal.readSimSteady(comp)

    def read_obs_steady(
        self,
        id_compartment: int,
        obs_aggr: Union[str, float],
        cutsdate: str = None,
        cutedate: str = None,
    ) -> pd.DataFrame:
        """Read steady-state observation data. Wraps Manage.Temporal.readObsSteady."""
        comp = self.get_compartment(id_compartment)
        cfg = obs_config[id_compartment]
        return self.temporal.readObsSteady(
            compartment=comp,
            id_col_time=cfg["id_col_time"],
            id_col_data=cfg["id_col_data"],
            obs_aggr=obs_aggr,
            cutsdate=cutsdate,
            cutedate=cutedate,
        )

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L3 — ESTIMATION LAYER  (comparison, filtering, inference)   ║
    # ╚════════════════════════════════════════════════════════════════╝

    def compute_performance_stats(
        self,
        sim: np.ndarray,
        obs: np.ndarray,
        metrics: List[str] = None,
    ) -> dict:
        """Compute performance statistics between sim and obs arrays.

        Target layer: L3 — Estimation Layer.
        Delegates to Comparator.calc_performance_metrics.

        Parameters
        ----------
        sim : np.ndarray
            Simulated values (1D).
        obs : np.ndarray
            Observed values (1D), may contain NaN.
        metrics : List[str], optional
            List of metric names to compute. If None, defaults to
            ["nash", "kge", "rmse", "pbias"].

        Returns
        -------
        dict
            {metric_name: value} for each requested metric.
        """
        self._warn_deprecated_helper(
            "compute_performance_stats",
            "transform(TransformRequest(kind='performance_criteria', ...))",
        )
        return self.transform(
            TransformRequest(
                kind="performance_criteria",
                payload={"sim": sim, "obs": obs},
                options={"metrics": metrics},
            )
        ).payload

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L4 — ANALYSIS LAYER  (temporal & spatial transformations)   ║
    # ╚════════════════════════════════════════════════════════════════╝

    def _prepare_sim_obs_data(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        simsdate: int,
        simedate: int,
        plotstart: str = None,
        plotend: str = None,
        id_layer: int = 0,
        aggr: Union[None, float, str] = None,
        compute_criteria: bool = False,
        criteria_metrics: List[str] = None,
        crit_start: str = None,
        crit_end: str = None,
        obs_unit: str = None,
    ) -> dict:
        """Load sim+obs and build per-point NumPy arrays for rendering.

        Combines extract_values + read_observations with per-point slicing.
        Both render_sim_obs_pdf and render_sim_obs_interactive use this method.

        Parameters
        ----------
        id_compartment : int
        outtype : str
        param : str
        simsdate, simedate : int
            Start/end years of simulation.
        plotstart, plotend : str, optional
            Date strings for sim temporal slicing via extract_values.
        id_layer : int
            Layer ID (default 0).
        aggr : None, float, or str, optional
            Observation aggregation for steady-state comparison.
            None = no aggregation (daily), 'mean'/'min'/'max' or float for quantile.
        compute_criteria : bool
            If True, compute performance criteria for each obs point.
        criteria_metrics : List[str], optional
            List of metric names to compute. Passed to compute_performance_stats.
        crit_start, crit_end : str, optional
            Date range for criteria computation. If None, uses full range.
        obs_unit : str, optional
            Target display unit for HYD compartment. When set and compartment
            is HYD, applies l/s ↔ m3/s conversion on the NumPy arrays.
            CaWaQS sim is in m3/s; obs are natively in l/s.

        Returns
        -------
        dict
            sim_dates : np.ndarray[datetime64]
            obs_dates : np.ndarray[datetime64]
            compartment_name : str
            obs_points : list[dict]
                Each: name, id_cell, id_layer, id_point, sim (1D), obs (1D)
                If compute_criteria=True, also 'criteria' : dict
            ext_points : list[dict]
                Each: name, id_cell, id_layer, sim (1D)
        """
        self._warn_deprecated_helper(
            "_prepare_sim_obs_data",
            "extract(ExtractRequest(kind='sim_obs_bundle', ...))",
        )
        return self.extract(
            ExtractRequest(
                kind="sim_obs_bundle",
                id_compartment=id_compartment,
                outtype=outtype,
                param=param,
                syear=simsdate,
                eyear=simedate,
                options={
                    "plotstart": plotstart,
                    "plotend": plotend,
                    "id_layer": id_layer,
                    "aggr": aggr,
                    "compute_criteria": compute_criteria,
                    "criteria_metrics": criteria_metrics,
                    "crit_start": crit_start,
                    "crit_end": crit_end,
                    "obs_unit": obs_unit,
                },
            )
        ).payload

    def extract_watbal_for_map(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        cutsdate: str = None,
        cutedate: str = None,
        id_layer: int = 0,
        target_unit: str = 'mm/j',
    ) -> ExtractValuesResponse:
        """Extract watbal values with vectorized unit conversion.

        Combines extract_values + Operator.convert_watbal_units.
        Returns ExtractValuesResponse with converted data.
        """
        response = self.extract_values(
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            syear=syear,
            eyear=eyear,
            id_layer=id_layer,
            cutsdate=cutsdate,
            cutedate=cutedate,
        )

        if target_unit != 'm3/s':
            layer_info = self.get_layer_info(id_compartment, id_layer)
            cell_areas = np.array(layer_info.cell_areas)
            response.data = Operator.convert_watbal_units(
                data=response.data,
                cell_areas=cell_areas,
                target_unit=target_unit,
            )

        return response

    def aggregate_for_map(
        self,
        data: np.ndarray,
        dates: np.ndarray,
        agg: Union[str, float],
        frequency: str,
        pluriannual: bool = False,
        year_end_month: int = 8,
        cell_ids: np.ndarray = None,
    ) -> pd.DataFrame:
        """Temporal aggregation returning DataFrame for GIS layer creation.

        Uses Operator.t_transform internally. Data is (n_cells, n_timesteps).
        Returns DataFrame with index=date_labels, columns=cell_ids.

        :param data: Array (n_cells, n_timesteps)
        :param dates: datetime64 array (n_timesteps,)
        :param agg: Aggregation function ('mean', 'sum', 'min', 'max', or float)
        :param frequency: 'Annual', 'Monthly', or 'Daily'
        :param pluriannual: If True, average across years
        :param year_end_month: Month at which year ends (8=hydrological, 12=calendar)
        :param cell_ids: Optional cell ID labels for columns
        :return: DataFrame (index=date_labels, columns=cell_ids)
        """
        # t_transform expects (n_timesteps, n_locations), so transpose
        arr_t = data.T  # (n_timesteps, n_cells)

        arr_agg, date_labels = Operator().t_transform(
            arr=arr_t,
            dates=dates,
            fz=frequency,
            agg=agg,
            year_end_month=year_end_month,
            plurianual_agg=pluriannual,
        )

        # arr_agg shape: (n_date_labels, n_cells)
        if cell_ids is None:
            cell_ids = np.arange(data.shape[0])

        df = pd.DataFrame(arr_agg, index=date_labels, columns=cell_ids)
        return df

    def build_watbal_spatial_gdf(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        cutsdate: str,
        cutedate: str,
        id_layer: int,
        target_unit: str,
        agg: Union[str, float],
        frequency: str,
        pluriannual: bool,
    ) -> gpd.GeoDataFrame:
        """Extract, aggregate, and assemble a WATBAL spatial map GeoDataFrame.

        Composes: extract_watbal_for_map → aggregate_for_map → assemble_single_layer_geodataframe.
        """
        self._warn_deprecated_helper(
            "build_watbal_spatial_gdf",
            "extract(ExtractRequest(kind='spatial_map', ...))",
        )
        comp_info = self.get_compartment_info(id_compartment)
        layer_info = self.get_layer_info(id_compartment, id_layer)

        response = self.extract_watbal_for_map(
            id_compartment=id_compartment, outtype=outtype, param=param,
            syear=syear, eyear=eyear,
            cutsdate=cutsdate, cutedate=cutedate,
            id_layer=id_layer, target_unit=target_unit,
        )

        agg_df = self.aggregate_for_map(
            data=response.data, dates=response.dates,
            agg=agg, frequency=frequency,
            pluriannual=pluriannual, year_end_month=8,
            cell_ids=comp_info.cell_ids,
        )

        return Manage.Spatial.assemble_single_layer_geodataframe(
            agg_df=agg_df,
            cell_ids=layer_info.cell_ids,
            cell_geometries=layer_info.cell_geometries,
            crs=layer_info.crs,
        )

    def build_effective_rainfall_gdf(
        self,
        id_compartment: int,
        syear: int,
        eyear: int,
        cutsdate: str,
        cutedate: str,
        id_layer: int,
        agg: Union[str, float],
        frequency: str,
        pluriannual: bool,
    ) -> gpd.GeoDataFrame:
        """Extract rain & ETR, compute effective rainfall, aggregate, assemble GeoDataFrame.

        Composes: extract_watbal_for_map (×2) → compute_effective_rainfall
                  → aggregate_for_map → assemble_single_layer_geodataframe.
        """
        self._warn_deprecated_helper(
            "build_effective_rainfall_gdf",
            "transform(TransformRequest(kind='runoff_ratio', ...))",
        )
        comp_info = self.get_compartment_info(id_compartment)
        layer_info = self.get_layer_info(id_compartment, id_layer)

        rain = self.extract_watbal_for_map(
            id_compartment=id_compartment, outtype="MB", param="rain",
            syear=syear, eyear=eyear,
            cutsdate=cutsdate, cutedate=cutedate,
            id_layer=id_layer, target_unit="mm/j",
        )
        etr = self.extract_watbal_for_map(
            id_compartment=id_compartment, outtype="MB", param="etr",
            syear=syear, eyear=eyear,
            cutsdate=cutsdate, cutedate=cutedate,
            id_layer=id_layer, target_unit="mm/j",
        )

        pe_data = Operator.compute_effective_rainfall(rain.data, etr.data)

        agg_df = self.aggregate_for_map(
            data=pe_data, dates=rain.dates,
            agg=agg, frequency=frequency,
            pluriannual=pluriannual, year_end_month=8,
            cell_ids=comp_info.cell_ids,
        )

        return Manage.Spatial.assemble_single_layer_geodataframe(
            agg_df=agg_df,
            cell_ids=layer_info.cell_ids,
            cell_geometries=layer_info.cell_geometries,
            crs=layer_info.crs,
        )

    def build_aq_spatial_gdf(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        cutsdate: str,
        cutedate: str,
        layers: list,
        agg: Union[str, float],
        frequency: str,
        pluriannual: bool,
        layer_id_offset: int = 0,
        outcropping_cell_ids: np.ndarray = None,
    ) -> gpd.GeoDataFrame:
        """Extract, aggregate, and assemble an AQ spatial map GeoDataFrame.

        Composes: extract_values → aggregate_for_map → assemble_multi_layer_geodataframe.

        :param layers: list of LayerInfo objects (single layer or all layers)
        :param layer_id_offset: starting layer ID (0 for MB, 1 for H)
        :param outcropping_cell_ids: if provided, filter to these cell IDs
        """
        self._warn_deprecated_helper(
            "build_aq_spatial_gdf",
            "extract(ExtractRequest(kind='spatial_map', ...))",
        )
        comp_info = self.get_compartment_info(id_compartment)

        response = self.extract_values(
            id_compartment=id_compartment, outtype=outtype, param=param,
            syear=syear, eyear=eyear,
            id_layer=-9999,
            cutsdate=cutsdate, cutedate=cutedate,
        )

        agg_df = self.aggregate_for_map(
            data=response.data, dates=response.dates,
            agg=agg, frequency=frequency,
            pluriannual=pluriannual, year_end_month=8,
            cell_ids=comp_info.cell_ids,
        )

        crs = layers[0].crs if layers else None

        gdf = Manage.Spatial.assemble_multi_layer_geodataframe(
            agg_df=agg_df, layers=layers,
            crs=crs, layer_id_offset=layer_id_offset,
        )

        if outcropping_cell_ids is not None:
            gdf = gdf.loc[gdf["ID_ABS"].isin(outcropping_cell_ids)]

        return gdf

    def build_aquifer_outcropping(
        self,
        id_compartment: int,
        save_directory: str = None,
    ) -> np.ndarray:
        """Build aquifer outcropping cell ID array.

        Wraps Manage.Spatial.buildAqOutcropping.
        Returns array of cell IDs that outcrop at the surface.

        :param id_compartment: Aquifer compartment ID
        :param save_directory: Directory to save the cell list file.
            If None, no file is saved.
        :return: 1D array of cell IDs
        """
        self._warn_deprecated_helper(
            "build_aquifer_outcropping",
            "extract(ExtractRequest(kind='aquifer_outcropping', ...))",
        )
        return self.extract(
            ExtractRequest(
                kind="aquifer_outcropping",
                id_compartment=id_compartment,
                options={"save_directory": save_directory},
            )
        ).payload

    def compute_budget_variable(
        self,
        data: np.ndarray,
        param: str,
        agg: str,
        fz: str,
        sdate: int,
        edate: int,
        cutsdate: str,
        cutedate: str,
        pluriannual: bool = False,
    ) -> tuple:
        """Compute interannual budget for a single variable.

        Delegates to Manage.Budget.calcInteranualBVariableNumpy.
        Returns (aggregated_data, date_labels, param).
        """
        self._warn_deprecated_helper(
            "compute_budget_variable",
            "transform(TransformRequest(kind='aggregated_budget', ...))",
        )
        return self.transform(
            TransformRequest(
                kind="aggregated_budget",
                payload={"data": data},
                options={
                    "param": param,
                    "agg": agg,
                    "fz": fz,
                    "sdate": sdate,
                    "edate": edate,
                    "cutsdate": cutsdate,
                    "cutedate": cutedate,
                    "pluriannual": pluriannual,
                },
            )
        ).payload

    def compute_hydrological_regime(
        self,
        id_compartment: int,
        data: np.ndarray,
        dates: np.ndarray,
        output_folder: str,
        output_name: str,
    ) -> tuple:
        """Compute hydrological regime (monthly interannual averages at obs points).

        Delegates to Manage.Budget.calcInteranualHVariableNumpy.
        Returns (interannual_data, obs_point_names, month_labels).
        """
        self._warn_deprecated_helper(
            "compute_hydrological_regime",
            "transform(TransformRequest(kind='hydrological_regime', ...))",
        )
        return self.transform(
            TransformRequest(
                kind="hydrological_regime",
                payload={"data": data, "dates": dates},
                options={
                    "id_compartment": id_compartment,
                    "output_folder": output_folder,
                    "output_name": output_name,
                },
            )
        ).payload

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L5 — CARTOGRAPHIC LAYER  (visualization & rendering)       ║
    # ╚════════════════════════════════════════════════════════════════╝

    def render_budget_barplot(
        self,
        data_dict: dict,
        plot_title: str,
        output_folder: str = None,
        output_name: str = None,
        yaxis_unit: str = 'mm',
    ):
        """Render budget bar plot. Delegates to Renderer."""
        self._warn_deprecated_helper(
            "render_budget_barplot",
            "render(RenderRequest(kind='budget', ...))",
        )
        return self.render(
            RenderRequest(
                kind="budget",
                payload={"data_dict": data_dict, "plot_title": plot_title},
                options={
                    "output_folder": output_folder,
                    "output_name": output_name,
                    "yaxis_unit": yaxis_unit,
                },
            )
        ).artefacts

    def render_hydrological_regime(
        self,
        data: np.ndarray,
        obs_point_names: list,
        month_labels: np.ndarray,
        var: str,
        units: str,
        savepath: str,
        interactive: bool = False,
        staticpng: bool = True,
        staticpdf: bool = True,
        years: str = None,
        **kwargs: Any,
    ):
        """Render hydrological regime plots. Delegates to Renderer."""
        legacy_interactive = kwargs.pop("interractiv", None)
        if legacy_interactive is not None:
            interactive = legacy_interactive
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")
        self._warn_deprecated_helper(
            "render_hydrological_regime",
            "render(RenderRequest(kind='regime', ...))",
        )
        return self.render(
            RenderRequest(
                kind="regime",
                payload={
                    "data": data,
                    "obs_point_names": obs_point_names,
                    "month_labels": month_labels,
                    "var": var,
                    "units": units,
                    "savepath": savepath,
                },
                options={
                    "interactive": interactive,
                    "staticpng": staticpng,
                    "staticpdf": staticpdf,
                    "years": years,
                },
            )
        ).artefacts

    def render_sim_obs_pdf(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        simsdate: int,
        simedate: int,
        plotstartdate: str,
        plotenddate: str,
        id_layer: int,
        directory: str,
        name_file: str,
        ylabel: str,
        obs_unit: str,
        crit_start: str = None,
        crit_end: str = None,
        aggr: Union[None, float, str] = None,
    ) -> List[str]:
        """Read sim+obs data and render to PDF.

        Uses _prepare_sim_obs_data for NumPy I/O + per-point slicing,
        then converts to DataFrames for Renderer.render_simobs_pdf.
        """
        self._warn_deprecated_helper(
            "render_sim_obs_pdf",
            "render(RenderRequest(kind='sim_obs_pdf', ...))",
        )
        return self.render(
            RenderRequest(
                kind="sim_obs_pdf",
                options={
                    "id_compartment": id_compartment,
                    "outtype": outtype,
                    "param": param,
                    "simsdate": simsdate,
                    "simedate": simedate,
                    "plotstartdate": plotstartdate,
                    "plotenddate": plotenddate,
                    "id_layer": id_layer,
                    "directory": directory,
                    "name_file": name_file,
                    "ylabel": ylabel,
                    "obs_unit": obs_unit,
                    "crit_start": crit_start,
                    "crit_end": crit_end,
                    "aggr": aggr,
                },
            )
        ).artefacts

    def render_sim_obs_interactive(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        simsdate: int,
        simedate: int,
        plotstart: str,
        plotend: str,
        obs_unit: str,
        ylabel: str,
        df_other_variable: pd.DataFrame = None,
        other_variable_config: dict = None,
        outFilePath: str = None,
        critstart: str = None,
        critend: str = None,
        aggr: Union[None, float, str] = None,
    ) -> List[str]:
        """Read sim+obs data and render interactive Plotly figure.

        Uses _prepare_sim_obs_data for NumPy I/O + per-point slicing,
        then converts to per-point DataFrames for Renderer.render_simobs_interactive.
        """
        self._warn_deprecated_helper(
            "render_sim_obs_interactive",
            "render(RenderRequest(kind='sim_obs_interactive', ...))",
        )
        return self.render(
            RenderRequest(
                kind="sim_obs_interactive",
                options={
                    "id_compartment": id_compartment,
                    "outtype": outtype,
                    "param": param,
                    "simsdate": simsdate,
                    "simedate": simedate,
                    "plotstart": plotstart,
                    "plotend": plotend,
                    "obs_unit": obs_unit,
                    "ylabel": ylabel,
                    "df_other_variable": df_other_variable,
                    "other_variable_config": other_variable_config,
                    "outFilePath": outFilePath,
                    "critstart": critstart,
                    "critend": critend,
                    "aggr": aggr,
                },
            )
        ).artefacts

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L6 — GIT-SYNCHRONIZED REGISTRY  (identity & provenance)    ║
    # ╚════════════════════════════════════════════════════════════════╝
    # IdCard, fingerprinting, and version tracking will be added here.

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  FRONTEND INTEGRATION FACADE                                ║
    # ║  High-level integrated methods consumed by cawaqsviz.       ║
    # ║  These orchestrate lower-level generic helpers into         ║
    # ║  frontend-ready artefacts and datasets.                     ║
    # ╚════════════════════════════════════════════════════════════════╝

    def has_observations(self, id_compartment: int) -> bool:
        """Check if a compartment has observation data.

        Target layer: L2 — Data Layer
        """
        comp = self.get_compartment(id_compartment)
        return comp.obs is not None

    def extract_area_values(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        cell_ids: Optional[np.ndarray] = None,
        spatial_operator: Optional[str] = None,
        id_layer: int = 0,
        cutsdate: Optional[str] = None,
        cutedate: Optional[str] = None,
        output_csv_path: Optional[Union[str, Path]] = None,
        **operator_kwargs: Any,
    ) -> ExtractValuesResponse:
        """Extract simulated values for specific cells (area subset).

        Target layer: L2 — Data Layer

        Two modes of operation:
        1. **Manual selection**: Provide cell_ids directly
        2. **Spatial operator**: Provide spatial_operator name to auto-identify cells

        Typical workflows:
        - Manual: data = twin.extract_area_values(cell_ids=[1,2,3], ...)
        - Catchment: data = twin.extract_area_values(
                         spatial_operator='catchment_cells',
                         obs_point=pt, network_gis_layer=layer, ...)
        - Then analyze: agg = twin.apply_temporal_operator(data.data, ...)

        Parameters
        ----------
        id_compartment : int
            Compartment ID to extract from
        outtype : str
            Output type (e.g., 'MB', 'TS')
        param : str
            Parameter name (e.g., 'etr', 'rain', 'runoff')
        syear : int
            Start year for extraction
        eyear : int
            End year for extraction
        cell_ids : Optional[np.ndarray], default None
            Array of cell IDs to extract. Use for manual cell selection.
            Mutually exclusive with spatial_operator.
        spatial_operator : Optional[str], default None
            Name of spatial operator for automatic cell identification.
            Mutually exclusive with cell_ids.

            Available operators:
            - 'catchment_cells': Upstream catchment cells
              Requires: obs_point, network_gis_layer, network_col_name_cell,
                       network_col_name_fnode, network_col_name_tnode
            - 'aquifer_outcropping': Aquifer outcropping cells
              Requires: exd, save (optional)
        id_layer : int, default 0
            Layer ID for multi-layer compartments
        cutsdate : Optional[str]
            Start date for temporal subset
        cutedate : Optional[str]
            End date for temporal subset
        output_csv_path : Optional[Union[str, Path]]
            Path to save CSV output
        **operator_kwargs
            Additional kwargs for spatial operator (if used)

        Returns
        -------
        ExtractValuesResponse
            Contains data for only the specified/identified cells

        Examples
        --------
        Manual cell selection:
            >>> data = twin.extract_area_values(
            ...     id_compartment=0,
            ...     cell_ids=np.array([103, 245, 567]),
            ...     outtype='MB',
            ...     param='etr',
            ...     syear=1990,
            ...     eyear=2000
            ... )

        Catchment-based extraction:
            >>> data = twin.extract_area_values(
            ...     id_compartment=0,
            ...     spatial_operator='catchment_cells',
            ...     obs_point=observation_point,
            ...     network_gis_layer=river_network,
            ...     network_col_name_cell='ID_CPROD',
            ...     network_col_name_fnode='FNODE',
            ...     network_col_name_tnode='TNODE',
            ...     outtype='MB',
            ...     param='runoff',
            ...     syear=1990,
            ...     eyear=2000
            ... )
        """
        comp = self.get_compartment(id_compartment)

        # First, extract all cells
        full_response = self.extract_values(
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            syear=syear,
            eyear=eyear,
            id_layer=id_layer,
            cutsdate=cutsdate,
            cutedate=cutedate,
        )

        # Subset to requested cells using Extractor
        # Support both manual cell_ids and spatial_operator modes
        subset_data = Extractor().extract_spatial(
            data=full_response.data,
            cell_ids=cell_ids.tolist() if isinstance(cell_ids, np.ndarray) else cell_ids,
            compartment=comp,
            spatial_operator=spatial_operator,
            spatial_manager=self.spatial,
            **operator_kwargs
        )

        # Save to CSV if requested
        csv_path: Optional[Path] = None
        if output_csv_path is not None:
            suffix = f"_{spatial_operator}" if spatial_operator else "_area"
            csv_path = Path(
                output_csv_path +
                f"/{comp.compartment}_{param}_{outtype}_{syear}-{eyear}{suffix}.csv"
            )

            # Create header with cell indices
            n_cells = subset_data.shape[0]
            if cell_ids is not None:
                header = 'Date\t' + '\t'.join([f'Cell_{cid}' for cid in cell_ids])
            else:
                # If using spatial operator, use generic numbering
                header = 'Date\t' + '\t'.join([f'Cell_{i}' for i in range(n_cells)])

            # Save with dates
            with open(csv_path, 'w') as f:
                f.write(header + '\n')
                for t, date in enumerate(full_response.dates):
                    date_str = str(date)[:10]
                    row_data = '\t'.join(f'{val:.6f}' for val in subset_data[:, t])
                    f.write(f'{date_str}\t{row_data}\n')

        # Build metadata
        meta = {
            "id_compartment": id_compartment,
            "outtype": outtype,
            "param": param,
            "syear": syear,
            "eyear": eyear,
            "id_layer": id_layer,
            "n_cells": subset_data.shape[0],
        }

        # Add cell_ids or spatial_operator info to metadata
        if spatial_operator:
            meta["spatial_operator"] = spatial_operator
            meta["operator_kwargs"] = operator_kwargs
        elif cell_ids is not None:
            meta["cell_ids"] = cell_ids.tolist() if isinstance(cell_ids, np.ndarray) else cell_ids

        return ExtractValuesResponse(
            data=subset_data,
            dates=full_response.dates,
            meta={**meta, "csv_path": str(csv_path) if csv_path is not None else None},
        )

    def apply_temporal_operator(
        self,
        arr: np.ndarray,
        dates: np.ndarray,
        column_names: Optional[np.ndarray],
        agg_dimension: Union[str, float],
        frequency: str,
        pluriennial: bool = False,
        year_end_month: int = 12,
    ) -> TemporalOpResponse:
        """Apply a temporal aggregation on a time series numpy array.

        Target layer: L4 — Analysis Layer

        Parameters
        ----------
        arr : np.ndarray
            Input time series data, shape (n_timesteps, n_locations).
        dates : np.ndarray
            Array of datetime64 objects corresponding to rows in arr.
        column_names : np.ndarray, optional
            Column names/identifiers for the locations (cells or sites).
            If None, will use default numeric indices.
        agg_dimension : str or float
            Aggregation function: 'mean', 'sum', 'min', 'max', or a float
            in [0,1] for quantile.
        frequency : str
            'Annual', 'Monthly', or 'Daily'.
        pluriennial : bool, default False
            If True, additional aggregation across years.
        year_end_month : int, default 12
            Month at which the fiscal/hydrological year ends.
            12 = calendar year, 8 = hydrological year (A-AUG).

        Returns
        -------
        TemporalOpResponse
            Contains aggregated numpy array, date labels, and metadata.
        """

        arr_agg, date_labels = Operator().t_transform(
            arr=arr,
            dates=dates,
            fz=frequency,
            agg=agg_dimension,
            year_end_month=year_end_month,
            plurianual_agg=pluriennial,
        )

        meta = {
            "agg_dimension": agg_dimension,
            "frequency": frequency,
            "pluriennial": pluriennial,
            "year_end_month": year_end_month,
            "method": "numpy",
            "shape": arr_agg.shape,
        }
        if column_names is not None:
            meta["column_names"] = list(column_names)

        return TemporalOpResponse(
            data=arr_agg,
            date_labels=date_labels,
            meta=meta,
        )

    def apply_spatial_average(
        self,
        id_compartment: int,
        data: np.ndarray,
        operation: str,
        areas: Optional[np.ndarray] = None,
    ) -> SpatialAverageResponse:
        """Apply spatial averaging to simulation data.

        Target layer: L4 — Analysis Layer

        :param id_compartment: Compartment ID
        :param data: Array (n_cells, n_timesteps) of simulated values
        :param operation: 'arithmetic', 'weighted', 'geometric', 'harmonic'
        :param areas: Optional cell areas (extracted from compartment if None)
        :return: SpatialAverageResponse with averaged timeseries
        """
        comp = self.get_compartment(id_compartment)

        # Perform spatial averaging
        averaged_data = Operator.sp_operator(
            data=data,
            operation=operation,
            areas=areas,
            compartment=comp
        )

        return SpatialAverageResponse(
            data=averaged_data,
            meta={
                "id_compartment": id_compartment,
                "operation": operation,
                "n_timesteps": len(averaged_data),
                "original_n_cells": data.shape[0],
            },
        )
