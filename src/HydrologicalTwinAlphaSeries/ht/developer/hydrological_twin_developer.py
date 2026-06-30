"""L2 · HT DEVELOPER · MICRO — micro-verb facade for :class:`HydrologicalTwin`.

Owns the 8 canonical verbs (``configure``, ``load``, ``describe``, ``fetch``,
``mask``, ``transform``, ``render``, ``export``), the lifecycle state machine,
and ``_require_state`` gatekeeping. The 4 dispatching verbs delegate to
``dispatch.py`` after coercing arguments to canonical ``*Request`` dataclasses.

Import direction (downward only):
    L2: hydrological_twin_developer.py → dispatch.py → handlers.py  (transitional)
    L3: → services/public/twin_io.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject
from HydrologicalTwinAlphaSeries.config.constants import paramRecs
from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
from HydrologicalTwinAlphaSeries.services.public.budget import Budget
from HydrologicalTwinAlphaSeries.services.public.temporal import Temporal

from .api_types import (
    ALLOWED_TRANSITIONS,
    MINIMUM_STATE,
    AssembleRequest,
    CompartmentBundleResult,
    CompartmentCatalog,
    CompartmentInfo,
    ConfigureRequest,
    DescribeRequest,
    ExportRequest,
    ExportResult,
    FetchRequest,
    InvalidStateError,
    LayerCatalog,
    LayerInfo,
    LoadRequest,
    MaskRequest,
    ObservationCatalog,
    ObservationInfo,
    ObservationsResponse,
    RenderRequest,
    RenderResult,
    SimObsBundleResponse,
    SimObsPointData,
    SpatialAverageResponse,
    TemporalOpResponse,
    TransformRequest,
    TwinCatalog,
    TwinDescription,
    TwinState,
    ValuesResponse,
)


class HydrologicalTwin:
    """HydrologicalTwin class is the main and only entry point for the hydrological twin package. It encapsulates the entire twin state and provides the canonical public API for configuration, data loading, description, extraction, transformation, rendering, and export. This Alpha Series is a first POC of a wider project that will develop private methods for :
    extraction, git synchronisation for navigation in the space-state continuum of data, software and simulations, building and launching of CaWaQS submodels, creation of subtwins, advanced multisimulation statistics, bayesian inference, uncertainties quantification, intellectual rights and property certification.

    ``Compartment`` is the **primary domain aggregate**: all public operations
    flow through compartments, never through low-level artifacts (meshes,
    observations, extraction points) directly.

    HydrologicalTwin instances have a well-defined lifecycle, with explicit states and allowed transitions. Each macro-method checks the current state and raises :class:`InvalidStateError` if called prematurely.
    Lifecycle states::

        EMPTY → CONFIGURED → LOADED → READY

    Public basic services along this life cycle are configure, load, describe


    Once READY HydrologicalTwin offers public services in three main categories for the Alpha Series : 
        transform, render, export

    The transition between Alpha and Beta Series will consist in developping the private git-sync and extraction methods.

    The transition between beta and the first complete POC of HydrologicalTwin will consist in creating private methods for subTwin instantiation, allowing it to be initialized with a CaWaQS simulation on the pure local extraction of the original Hydrological Twin in a masked domain

    After first POC, the roadmap is to develop the next private methods namely for :
    1. development of a bayesian framework for self-fitting and uncertainty quantification, with the creation of a twin manager to handle multiple twin instances in parallel and their interactions
    2. improvment of the self_fitting procedure including frequency domain analysis in a stepwise fitting process 
    3. development of intellectual property and rights management, with certification of the originality of twins and their components, and tracking of their evolution in the state-space continuum of data, software and simulations.
   

        
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

        # Domain services reusing existing logic#Watch that is is a global set up that can be tuned within compartment
        self.temporal = Temporal()
        self.budget = Budget()

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

    @staticmethod
    def _normalize_frequency(frequency: Optional[str], *, target: str = "short") -> str:
        mapping = {
            "Y": ("Y", "Annual"),
            "Annual": ("Y", "Annual"),
            "M": ("M", "Monthly"),
            "Monthly": ("M", "Monthly"),
            "D": ("D", "Daily"),
            "Daily": ("D", "Daily"),
        }
        normalized = mapping.get(frequency or "Annual", ("Y", "Annual"))
        return normalized[0] if target == "short" else normalized[1]

    def _build_compartments(self, request: LoadRequest) -> Dict[int, Compartment]:
        if request.compartments is not None:
            return dict(request.compartments)
        if request.geo_provider is None:
            raise ValueError(
                "load() requires either fully built compartments or a geo_provider."
            )
        if self.config_geom is None or self.config_proj is None:
            raise InvalidStateError("load() requires configure() to be called first.")

        ids_compartments = request.ids_compartments or list(self.config_geom.idCompartments)
        return {
            id_compartment: Compartment(
                id_compartment=id_compartment,
                config_geom=self.config_geom,
                config_proj=self.config_proj,
                out_caw_directory=self.out_caw_directory or "",
                obs_directory=self.obs_directory or "",
                geo_provider=request.geo_provider,
            )
            for id_compartment in ids_compartments
        }

    def _build_catalog(self, request: DescribeRequest) -> TwinCatalog:
        compartments: List[CompartmentCatalog] = []
        for comp_info in self.list_compartments():
            layers: List[LayerCatalog] = []
            if request.include_layers:
                layers = [
                    LayerCatalog(
                        id_layer=layer_index,
                        name=layer_name,
                        n_cells=self.get_layer_info(comp_info.id_compartment, layer_index).n_cells,
                        cell_id_column=(
                            self.config_geom.idColCells.get(comp_info.id_compartment)
                            if self.config_geom is not None
                            else None
                        ),
                        crs=self.get_layer_info(comp_info.id_compartment, layer_index).crs,
                    )
                    for layer_index, layer_name in enumerate(comp_info.layers_gis_names)
                ]

            observations = None
            obs_info = self.get_observation_info(comp_info.id_compartment)
            if request.include_observations and obs_info is not None:
                observations = ObservationCatalog(
                    layer_name=obs_info.layer_gis_name,
                    n_points=obs_info.n_points,
                    point_id_column=(
                        self.config_geom.obsIdsColNames.get(comp_info.id_compartment)
                        if self.config_geom is not None
                        else None
                    ),
                    point_name_column=(
                        self.config_geom.obsIdsColNames.get(comp_info.id_compartment)
                        if self.config_geom is not None
                        else None
                    ),
                    point_layer_column=(
                        self.config_geom.obsIdsColLayer.get(comp_info.id_compartment)
                        if self.config_geom is not None
                        else None
                    ),
                    point_cell_column=(
                        self.config_geom.obsIdsColCells.get(comp_info.id_compartment)
                        if self.config_geom is not None
                        else None
                    ),
                    point_names=list(obs_info.point_names),
                    point_ids=list(obs_info.point_ids),
                    layer_ids=list(obs_info.layer_ids),
                    geometries=list(obs_info.geometries),
                )

            output_parameters: Dict[str, List[str]] = {}
            if request.include_outputs:
                prefix = f"{comp_info.name}_"
                output_parameters = {
                    key.split("_", 1)[1]: list(values)
                    for key, values in paramRecs.items()
                    if key.startswith(prefix)
                }

            compartments.append(
                CompartmentCatalog(
                    id_compartment=comp_info.id_compartment,
                    name=comp_info.name,
                    out_caw_path=comp_info.out_caw_path,
                    regime=comp_info.regime,
                    primary_layer_name=(
                        comp_info.layers_gis_names[0]
                        if comp_info.layers_gis_names
                        else None
                    ),
                    layer_cell_id_column=(
                        self.config_geom.idColCells.get(comp_info.id_compartment)
                        if self.config_geom is not None
                        else None
                    ),
                    out_caw_directory=self.out_caw_directory,
                    hyd_corresp_missing=self.get_compartment(comp_info.id_compartment).hyd_corresp_missing,
                    layers=layers,
                    observations=observations,
                    output_parameters=output_parameters,
                )
            )

        return TwinCatalog(
            compartments=compartments,
            extract_kinds=[
                "simulation_matrix",
                "observations",
                "sim_obs_bundle",
                "spatial_map",
                "catchment_cells",
                "aquifer_outcropping_map",
                "aq_balance_inputs",
            ],
            transform_kinds=[
                "temporal_aggregation",
                "spatial_average",
                "criteria",
                "budget",
                "hydrological_regime",
                "runoff_ratio",
                "aq_balance",
            ],
            render_kinds=[
                "budget_barplot",
                "hydrological_regime",
                "sim_obs_pdf",
                "sim_obs_interactive",
                "aq_flux_diagram",
            ],
            export_formats=["npy", "geopackage"],
        )

    @staticmethod
    def _bundle_dict_to_response(bundle: Dict[str, Any]) -> SimObsBundleResponse:
        obs_points = [
            SimObsPointData(
                name=point["name"],
                id_cell=point["id_cell"],
                id_layer=point["id_layer"],
                id_point=point.get("id_point"),
                sim=point.get("sim"),
                obs=point.get("obs"),
                criteria=point.get("criteria"),
            )
            for point in bundle.get("obs_points", [])
        ]
        ext_points = [
            SimObsPointData(
                name=point["name"],
                id_cell=point["id_cell"],
                id_layer=point["id_layer"],
                sim=point.get("sim"),
            )
            for point in bundle.get("ext_points", [])
        ]
        return SimObsBundleResponse(
            sim_dates=bundle["sim_dates"],
            obs_dates=bundle["obs_dates"],
            compartment_name=bundle["compartment_name"],
            obs_points=obs_points,
            ext_points=ext_points,
            meta=bundle.get("meta"),
        )

    @staticmethod
    def _bundle_response_to_dict(
        bundle: Union[SimObsBundleResponse, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if isinstance(bundle, dict):
            return bundle
        return {
            "sim_dates": bundle.sim_dates,
            "obs_dates": bundle.obs_dates,
            "compartment_name": bundle.compartment_name,
            "obs_points": [
                {
                    "name": point.name,
                    "id_cell": point.id_cell,
                    "id_layer": point.id_layer,
                    "id_point": point.id_point,
                    "sim": point.sim,
                    "obs": point.obs,
                    "criteria": point.criteria,
                }
                for point in bundle.obs_points
            ],
            "ext_points": [
                {
                    "name": point.name,
                    "id_cell": point.id_cell,
                    "id_layer": point.id_layer,
                    "sim": point.sim,
                }
                for point in bundle.ext_points
            ],
            "meta": bundle.meta,
        }

    def _resolve_layer_infos(
        self,
        id_compartment: int,
        request: FetchRequest,
    ) -> List[LayerInfo]:
        from ...services.public import twin_io
        return twin_io._resolve_layer_infos(
            self,
            id_compartment,
            layers=request.layers,
            layer_names=request.layer_names,
            id_layer=request.id_layer,
        )

    @staticmethod
    def _collapse_aq_series(values: np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if array.ndim <= 1:
            return array
        return np.nansum(array, axis=0)

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L2 · HT DEVELOPER · MICRO — canonical micro-verbs          ║
    # ╚════════════════════════════════════════════════════════════════╝

    def configure(
        self,
        config_geom: Optional[ConfigGeometry] = None,
        config_proj: Optional[ConfigProject] = None,
        out_caw_directory: Optional[str] = None,
        obs_directory: Optional[str] = None,
        temp_directory: Optional[str] = None,
        request: Optional[ConfigureRequest] = None,
    ) -> None:
        """Attach project and geometry configuration via the canonical macro API."""
        if isinstance(config_geom, ConfigureRequest) and request is None:
            request = config_geom
            config_geom = None

        if request is not None:
            config_geom = request.config_geom
            config_proj = request.config_proj
            out_caw_directory = request.out_caw_directory
            obs_directory = request.obs_directory
            temp_directory = request.temp_directory
            if request.metadata:
                self.metadata.update(request.metadata)

        if config_geom is None or config_proj is None:
            raise ValueError("configure() requires both config_geom and config_proj.")

        self._require_state("configure")
        self.config_geom = config_geom
        self.config_proj = config_proj
        self.out_caw_directory = out_caw_directory or ""
        self.obs_directory = obs_directory or ""
        self.temp_directory = temp_directory or self.out_caw_directory
        self._transition_to(TwinState.CONFIGURED)

    def load(
        self,
        compartments: Optional[Dict[int, Compartment]] = None,
        request: Optional[LoadRequest] = None,
        **kwargs: Any,
    ) -> None:
        """Register compartments and mesh data via the canonical macro API."""
        if isinstance(compartments, LoadRequest) and request is None:
            request = compartments
            compartments = None
        if request is None:
            request = LoadRequest(
                compartments=compartments,
                ids_compartments=kwargs.pop("ids_compartments", []),
                geo_provider=kwargs.pop("geo_provider", None),
            )
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        self._require_state("load")
        self.compartments = self._build_compartments(request)
        self._ensure_disk_cache()
        self._transition_to(TwinState.LOADED)

    def describe(
        self,
        request: Optional[DescribeRequest] = None,
        **kwargs: Any,
    ) -> TwinDescription:
        """Return the structured twin description and frontend catalog."""
        self._require_state("describe")
        if request is None:
            request = DescribeRequest(**kwargs) if kwargs else DescribeRequest()
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        return TwinDescription(
            state=self._state.value,
            n_compartments=len(self.compartments),
            compartments=self.list_compartments(),
            metadata=self.metadata,
            catalog=self._build_catalog(request),
        )


    def fetch(
        self,
        id_compartment: Optional[int] = None,
        outtype: Optional[str] = None,
        param: Optional[str] = None,
        syear: Optional[int] = None,
        eyear: Optional[int] = None,
        request: Optional[FetchRequest] = None,
        kind: str = "simulation_matrix",
        **kwargs: Any,
    ) -> Any:
        """Fetch frontend-ready workflow payloads via the canonical macro API."""
        self._require_state("fetch")
        if isinstance(id_compartment, FetchRequest) and request is None:
            request = id_compartment
            id_compartment = None
        if request is None:
            request = FetchRequest(
                kind=kind,
                id_compartment=id_compartment,
                outtype=outtype,
                param=param,
                syear=syear,
                eyear=eyear,
                **kwargs,
            )
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")
        from . import dispatch
        return dispatch.fetch(self, request)

    def mask(
        self,
        id_compartment: Optional[int] = None,
        polygon: Any = None,
        request: Optional[MaskRequest] = None,
        kind: str = "polygon_cells",
        **kwargs: Any,
    ) -> Any:
        """Polygon-mask-driven extraction macro.

        Dispatches on ``kind`` to spatial-mask workflows: cell selection
        inside a polygon, sim-data restricted to that selection, and
        boundary geometries (HYD reaches / AQ cell edges) on the
        polygon's perimeter. See the ``twin-mask-macro`` spec for the
        full kind catalogue.
        """
        self._require_state("mask")
        if isinstance(id_compartment, MaskRequest) and request is None:
            request = id_compartment
            id_compartment = None
        if request is None:
            request = MaskRequest(
                kind=kind,
                id_compartment=id_compartment,
                polygon=polygon,
                **kwargs,
            )
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        from . import dispatch
        return dispatch.mask(self, request)

    def transform(
        self,
        arr: Any = None,
        dates: Optional[np.ndarray] = None,
        frequency: Optional[str] = None,
        agg_dimension: Union[str, float] = "mean",
        request: Optional[TransformRequest] = None,
        kind: str = "temporal_aggregation",
        **kwargs: Any,
    ) -> Any:
        """Apply frontend-facing workflow computations via the canonical macro API."""
        self._require_state("transform")
        if isinstance(arr, TransformRequest) and request is None:
            request = arr
            arr = None
        if request is None:
            # Allow 'data' to be passed via kwargs (e.g. from frontend callers)
            if arr is None and "data" in kwargs:
                arr = kwargs.pop("data")
            if dates is None and "dates" in kwargs:
                dates = kwargs.pop("dates")
            request = TransformRequest(
                kind=kind,
                data=arr,
                dates=dates,
                frequency=frequency,
                agg_dimension=agg_dimension,
                **kwargs,
            )
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        from . import dispatch
        return dispatch.transform(self, request)

    def render(
        self,
        kind: Union[str, RenderRequest] = "budget_barplot",
        request: Optional[RenderRequest] = None,
        **kwargs: Any,
    ) -> RenderResult:
        """Produce final artefacts via the canonical macro rendering entry point."""
        self._require_state("render")
        if isinstance(kind, RenderRequest) and request is None:
            request = kind
            kind = request.kind
        data_dict = kwargs.pop("data_dict", None)
        if request is None:
            request = RenderRequest(kind=kind, data=kwargs.pop("data", data_dict), **kwargs)
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        from . import dispatch
        return dispatch.render(self, request)

    def export(
        self,
        kind: Union[str, ExportRequest] = "npy",
        request: Optional[ExportRequest] = None,
        **kwargs: Any,
    ) -> ExportResult:
        """Serialize already-computed data to disk, keyed by **data format**.

        ``export`` is the 5th canonical dispatching verb, alongside ``fetch``,
        ``mask``, ``transform``, and ``render``. ``kind`` selects a file format
        (``"npy"`` or ``"geopackage"``) — never a semantic artefact and never an
        image type (PNG/PDF/HTML stay with ``render``: ``render`` = pixels,
        ``export`` = data files). It is **pure serialization**: it performs no
        ``fetch``/``transform``/compute and no shaping beyond what the
        destination L3 writer already does — a transparent pass-through to the
        privileged L3 writers in ``services/private/submodel_export.py``.

        Follows the same coercion idiom as the other dispatching verbs: pass a
        pre-built :class:`ExportRequest` positionally, or supply kwargs
        (``path``, ``data``, ``options``) that are folded into one. Unexpected
        kwargs raise ``TypeError``.
        """
        self._require_state("export")
        if isinstance(kind, ExportRequest) and request is None:
            request = kind
            kind = request.kind
        if request is None:
            request = ExportRequest(kind=kind, **kwargs)
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        from . import dispatch
        return dispatch.export(self, request)

    def assemble(
        self,
        kind: Union[str, AssembleRequest] = "compartment_bundle",
        request: Optional[AssembleRequest] = None,
        **kwargs: Any,
    ) -> Any:
        """Shape already-fetched per-key blocks into a serialization-ready payload.

        ``assemble`` is the 6th canonical dispatching verb, alongside ``fetch``,
        ``mask``, ``transform``, ``render``, and ``export``. ``kind`` selects a
        shaping workflow (``"compartment_bundle"`` for a GeoPackage bundle,
        ``"boundary_aq_layers"`` for per-aquifer-layer borders GeoDataFrames). It
        is **shape-only**:
        it performs no ``fetch``/``mask``/``transform`` and no disk I/O — the
        returned :class:`CompartmentBundleResult` is written by a subsequent
        ``twin.export(kind="geopackage", ...)`` call.

        Follows the same coercion idiom as the other dispatching verbs: pass a
        pre-built :class:`AssembleRequest` positionally, or supply kwargs that
        are folded into one. Unexpected kwargs raise ``TypeError``.
        """
        self._require_state("assemble")
        if isinstance(kind, AssembleRequest) and request is None:
            request = kind
            kind = request.kind
        if request is None:
            assert isinstance(kind, str)
            request = AssembleRequest(kind=kind, **kwargs)
        elif kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        from . import dispatch
        return dispatch.assemble(self, request)

    def get_compartment(self, id_compartment: int) -> Compartment:
        """Return a registered Compartment.

        Raises KeyError if the compartment was not registered at init time.
        """
        from ...services.public import twin_io
        return twin_io.get_compartment(self, id_compartment)

    def get_compartment_info(self, id_compartment: int) -> CompartmentInfo:
        """Return a serializable snapshot of compartment metadata."""
        from ...services.public import twin_io
        return twin_io.get_compartment_info(self, id_compartment)

    def list_compartments(self) -> List[CompartmentInfo]:
        """Return info for all registered compartments."""
        from ...services.public import twin_io
        return twin_io.list_compartments(self)

    def get_layer_info(self, id_compartment: int, id_layer: int) -> LayerInfo:
        """Return cell data for a specific mesh layer."""
        from ...services.public import twin_io
        return twin_io.get_layer_info(self, id_compartment, id_layer)

    def get_all_layers(self, id_compartment: int) -> List[LayerInfo]:
        """Return LayerInfo for every layer in a compartment's mesh."""
        from ...services.public import twin_io
        return twin_io.get_all_layers(self, id_compartment)

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L2 — DATA LAYER  (Observations & Simulations I/O)           ║
    # ╚════════════════════════════════════════════════════════════════╝

    def get_observation_info(self, id_compartment: int) -> Optional[ObservationInfo]:
        """Return a serializable snapshot of observation metadata.

        Returns None if the compartment has no observations.
        """
        from ...services.public import twin_io
        return twin_io.get_observation_info(self, id_compartment)


    def read_observations(
        self,
        id_compartment: int,
        syear: int,
        eyear: int,
    ) -> ObservationsResponse:
        """Read observation data for all observation points of a compartment."""
        from ...services.public import twin_io
        return twin_io.read_observations(self, id_compartment, syear, eyear)

    def read_sim_steady(self, id_compartment: int) -> pd.DataFrame:
        """Read steady-state simulation data. Wraps Temporal.readSimSteady."""
        from ...services.public import twin_io
        return twin_io.read_sim_steady(self, id_compartment)

    def read_obs_steady(
        self,
        id_compartment: int,
        obs_aggr: Union[str, float],
        cutsdate: str = None,
        cutedate: str = None,
    ) -> pd.DataFrame:
        """Read steady-state observation data. Wraps Temporal.readObsSteady."""
        from ...services.public import twin_io
        return twin_io.read_obs_steady(
            self, id_compartment, obs_aggr,
            cutsdate=cutsdate, cutedate=cutedate,
        )

    def _ensure_disk_cache(self) -> None:
        """Materialise the on-disk ``.npy`` cache for every compartment and outtype."""
        from ...services.public import twin_io
        return twin_io._ensure_disk_cache(self)

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L3 — ESTIMATION LAYER  (comparison, filtering, inference)   ║
    # ╚════════════════════════════════════════════════════════════════╝

    def compute_performance_stats(
        self,
        sim: np.ndarray,
        obs: np.ndarray,
        metrics: List[str] = None,
    ) -> dict:
        """Compute performance statistics between sim and obs arrays."""
        from . import handlers
        return handlers.compute_performance_stats(self, sim, obs, metrics=metrics)

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
        """Load sim+obs and build per-point NumPy arrays for rendering."""
        from . import handlers
        return handlers._prepare_sim_obs_data(
            self, id_compartment, outtype, param, simsdate, simedate,
            plotstart=plotstart, plotend=plotend, id_layer=id_layer,
            aggr=aggr, compute_criteria=compute_criteria,
            criteria_metrics=criteria_metrics,
            crit_start=crit_start, crit_end=crit_end, obs_unit=obs_unit,
        )

    def read_watbal_converted(
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
    ) -> ValuesResponse:
        """Extract watbal values with vectorized unit conversion."""
        from ...services.public import twin_io
        return twin_io.read_watbal_converted(
            self, id_compartment, outtype, param, syear, eyear,
            cutsdate=cutsdate, cutedate=cutedate,
            id_layer=id_layer, target_unit=target_unit,
        )

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
        """Temporal aggregation returning DataFrame for GIS layer creation."""
        from . import handlers
        return handlers.aggregate_for_map(
            self, data, dates, agg, frequency,
            pluriannual=pluriannual, year_end_month=year_end_month,
            cell_ids=cell_ids,
        )

    def _build_watbal_spatial_gdf(
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
        """Extract, aggregate, and assemble a WATBAL spatial map GeoDataFrame."""
        from . import handlers
        return handlers._build_watbal_spatial_gdf(
            self, id_compartment, outtype, param, syear, eyear,
            cutsdate, cutedate, id_layer, target_unit,
            agg, frequency, pluriannual,
        )

    def _build_effective_rainfall_gdf(
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
        """Extract rain & ETR, compute effective rainfall, aggregate, assemble GeoDataFrame."""
        from . import handlers
        return handlers._build_effective_rainfall_gdf(
            self, id_compartment, syear, eyear,
            cutsdate, cutedate, id_layer,
            agg, frequency, pluriannual,
        )

    def _build_aq_spatial_gdf(
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
        """Extract, aggregate, and assemble an AQ spatial map GeoDataFrame."""
        from . import handlers
        return handlers._build_aq_spatial_gdf(
            self, id_compartment, outtype, param, syear, eyear,
            cutsdate, cutedate, layers,
            agg, frequency, pluriannual,
            layer_id_offset=layer_id_offset,
            outcropping_cell_ids=outcropping_cell_ids,
        )

    def _build_aquifer_outcropping(
        self,
        id_compartment: int,
        save_directory: str = None,
    ) -> np.ndarray:
        """Build aquifer outcropping cell ID array. Wraps Spatial.buildAqOutcropping."""
        from . import handlers
        return handlers._build_aquifer_outcropping(
            self, id_compartment, save_directory=save_directory,
        )

    def _build_outcropping_mesh_gdf(self, id_compartment: int):
        """Return the cross-layer outcropping mesh gdf (id_abs/area/geometry)."""
        from . import handlers
        return handlers._build_outcropping_mesh_gdf(self, id_compartment)

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
        """Compute interannual budget for a single variable."""
        from . import handlers
        return handlers.compute_budget_variable(
            self, data, param, agg, fz, sdate, edate,
            cutsdate, cutedate, pluriannual=pluriannual,
        )

    def compute_hydrological_regime(
        self,
        id_compartment: int,
        data: np.ndarray,
        dates: np.ndarray,
        output_folder: str,
        output_name: str,
    ) -> tuple:
        """Compute hydrological regime (monthly interannual averages at obs points)."""
        from . import handlers
        return handlers.compute_hydrological_regime(
            self, id_compartment, data, dates, output_folder, output_name,
        )

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  Visualization & rendering                                     ║
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
        from . import handlers
        return handlers.render_budget_barplot(
            self, data_dict, plot_title,
            output_folder=output_folder, output_name=output_name,
            yaxis_unit=yaxis_unit,
        )

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
        from . import handlers
        return handlers.render_hydrological_regime(
            self, data, obs_point_names, month_labels, var, units, savepath,
            interactive=interactive, staticpng=staticpng,
            staticpdf=staticpdf, years=years, **kwargs,
        )

    def _render_sim_obs_pdf(
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
        """Read sim+obs data and render to PDF."""
        from . import handlers
        return handlers._render_sim_obs_pdf(
            self, id_compartment, outtype, param, simsdate, simedate,
            plotstartdate, plotenddate, id_layer, directory, name_file,
            ylabel, obs_unit,
            crit_start=crit_start, crit_end=crit_end, aggr=aggr,
        )

    def _render_sim_obs_interactive(
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
        out_file_path: str = None,
        crit_start: str = None,
        crit_end: str = None,
        aggr: Union[None, float, str] = None,
    ) -> List[str]:
        """Read sim+obs data and render interactive Plotly figure."""
        from . import handlers
        return handlers._render_sim_obs_interactive(
            self, id_compartment, outtype, param, simsdate, simedate,
            plotstart, plotend, obs_unit, ylabel,
            df_other_variable=df_other_variable,
            other_variable_config=other_variable_config,
            out_file_path=out_file_path,
            crit_start=crit_start, crit_end=crit_end, aggr=aggr,
        )

    def render_aq_flux_diagram(
        self,
        tables: Optional[Dict[str, Any]],
        output_folder: Optional[str],
        output_name: Optional[str] = None,
        colors: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Render aquifer-balance artefacts from transformed workflow tables."""
        from . import handlers
        return handlers.render_aq_flux_diagram(
            self, tables, output_folder,
            output_name=output_name, colors=colors,
        )

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  FRONTEND INTEGRATION FACADE                                ║
    # ║  High-level integrated methods consumed by cawaqsviz.       ║
    # ║  These orchestrate lower-level generic helpers into         ║
    # ║  frontend-ready artefacts and datasets.                     ║
    # ╚════════════════════════════════════════════════════════════════╝

    def has_observations(self, id_compartment: int) -> bool:
        """Check if a compartment has observation data."""
        from ...services.public import twin_io
        return twin_io.has_observations(self, id_compartment)

    def extract_area(
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
    ) -> ValuesResponse:
        """Extract simulated values for specific cells (area subset)."""
        from . import handlers
        return handlers.extract_area(
            self, id_compartment, outtype, param, syear, eyear,
            cell_ids=cell_ids, spatial_operator=spatial_operator,
            id_layer=id_layer, cutsdate=cutsdate, cutedate=cutedate,
            output_csv_path=output_csv_path, **operator_kwargs,
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
        """Apply a temporal aggregation on a time series numpy array."""
        from . import handlers
        return handlers.apply_temporal_operator(
            self, arr, dates, column_names, agg_dimension, frequency,
            pluriennial=pluriennial, year_end_month=year_end_month,
        )

    def apply_spatial_average(
        self,
        id_compartment: int,
        data: np.ndarray,
        operation: str,
        areas: Optional[np.ndarray] = None,
    ) -> SpatialAverageResponse:
        """Apply spatial averaging to simulation data."""
        from . import handlers
        return handlers.apply_spatial_average(
            self, id_compartment, data, operation, areas=areas,
        )
