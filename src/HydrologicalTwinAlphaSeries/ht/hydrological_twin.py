from __future__ import annotations

import os
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
    ExportResult,
    ExtractValuesResponse,
    InvalidStateError,
    LayerInfo,
    ObservationInfo,
    ObservationsResponse,
    RenderResult,
    SpatialAverageResponse,
    TemporalOpResponse,
    TwinDescription,
    TwinState,
)
from .persistence import HTPersistenceMixin


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

        configure, load, register_compartment, describe,
        extract, transform, render, export
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
        compartments: Optional[Dict[int, Compartment]] = None,
        **kwargs: Any,
    ) -> None:
        """Register compartments and mesh data.

        Transitions: CONFIGURED → LOADED.

        Parameters
        ----------
        compartments : dict, optional
            ``{id_compartment: Compartment}`` mapping.  When supplied the
            compartments are stored directly.
        """
        self._require_state("load")
        if compartments is not None:
            self.compartments = compartments
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
        self._require_state("register_compartment")
        if not isinstance(compartment, Compartment):
            raise TypeError(
                f"Expected a Compartment instance, got {type(compartment).__name__}"
            )
        self.compartments[id_compartment] = compartment

    def describe(self, **kwargs: Any) -> TwinDescription:
        """Return a structured description of the twin.

        Requires state LOADED.
        """
        self._require_state("describe")
        return TwinDescription(
            state=self._state.value,
            n_compartments=len(self.compartments),
            compartments=self.list_compartments(),
            metadata=self.metadata,
        )

    def extract(
        self,
        id_compartment: int,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        **kwargs: Any,
    ) -> ExtractValuesResponse:
        """Extract simulation data (macro-method).

        Delegates to :meth:`extract_values`.  Requires state LOADED.
        """
        self._require_state("extract")
        return self.extract_values(
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            syear=syear,
            eyear=eyear,
            **kwargs,
        )

    def transform(
        self,
        arr: np.ndarray,
        dates: np.ndarray,
        frequency: str,
        agg_dimension: Union[str, float] = "mean",
        **kwargs: Any,
    ) -> TemporalOpResponse:
        """Apply temporal aggregation (macro-method).

        Delegates to :meth:`apply_temporal_operator`.  Requires state LOADED.
        """
        self._require_state("transform")
        return self.apply_temporal_operator(
            arr=arr,
            dates=dates,
            column_names=kwargs.pop("column_names", None),
            agg_dimension=agg_dimension,
            frequency=frequency,
            **kwargs,
        )

    def render(self, kind: str = "budget", **kwargs: Any) -> RenderResult:
        """Produce visualizations (macro-method).

        Delegates to the appropriate render helper.  Requires state LOADED.

        Parameters
        ----------
        kind : str
            ``"budget"`` | ``"regime"`` | ``"sim_obs_pdf"`` | ``"sim_obs_interactive"``
        """
        self._require_state("render")
        if kind == "budget":
            self.render_budget_barplot(**kwargs)
        elif kind == "regime":
            self.render_hydrological_regime(**kwargs)
        elif kind == "sim_obs_pdf":
            self.render_sim_obs_pdf(**kwargs)
        elif kind == "sim_obs_interactive":
            self.render_sim_obs_interactive(**kwargs)
        else:
            raise ValueError(f"Unknown render kind: {kind!r}")
        return RenderResult(meta={"kind": kind})

    def export(
        self,
        path: Optional[str] = None,
        fmt: str = "pickle",
        **kwargs: Any,
    ) -> ExportResult:
        """Export data or twin snapshot to disk (macro-method).

        Requires state LOADED.

        Parameters
        ----------
        path : str, optional
            Destination file/directory path.
        fmt : str
            ``"pickle"`` (default) — full twin snapshot via ``to_pickle``.
        """
        self._require_state("export")
        if fmt == "pickle":
            if path is None:
                raise ValueError("'path' is required for pickle export.")
            self.to_pickle(path)
        else:
            raise ValueError(f"Unknown export format: {fmt!r}")
        return ExportResult(path=path, meta={"fmt": fmt})

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
        comp = self.get_compartment(id_compartment)
        return CompartmentInfo(
            id_compartment=id_compartment,
            name=comp.compartment,
            layers_gis_names=list(comp.layers_gis_names),
            n_layers=len(comp.mesh.mesh),
            n_cells=comp.mesh.ncells,
            cell_ids=np.array(comp.mesh.getCellIdVector()),
            out_caw_path=comp.out_caw_path,
            regime=comp.regime,
        )

    def list_compartments(self) -> List[CompartmentInfo]:
        """Return info for all registered compartments."""
        return [
            self.get_compartment_info(cid)
            for cid in self.compartments
        ]

    def get_layer_info(self, id_compartment: int, id_layer: int) -> LayerInfo:
        """Return cell data for a specific mesh layer."""
        comp = self.get_compartment(id_compartment)
        layer = comp.mesh.mesh[id_layer]
        return LayerInfo(
            id_layer=id_layer,
            n_cells=layer.ncells,
            cell_ids=np.array([cell.id for cell in layer.layer]),
            cell_areas=np.array([cell.area for cell in layer.layer]),
            cell_geometries=[cell.geometry for cell in layer.layer],
            layer_gis_name=comp.layers_gis_names[id_layer]
                           if id_layer < len(comp.layers_gis_names) else "",
            crs=layer.crs,
        )

    def get_all_layers(self, id_compartment: int) -> List[LayerInfo]:
        """Return LayerInfo for every layer in a compartment's mesh."""
        comp = self.get_compartment(id_compartment)
        return [
            self.get_layer_info(id_compartment, lid)
            for lid in comp.mesh.mesh
        ]

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L2 — DATA LAYER  (Observations & Simulations I/O)           ║
    # ╚════════════════════════════════════════════════════════════════╝

    def get_observation_info(self, id_compartment: int) -> Optional[ObservationInfo]:
        """Return a serializable snapshot of observation metadata.

        Returns None if the compartment has no observations.
        """
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

        comp = self.get_compartment(id_compartment)

        # Read simulation data (returns NumPy array)
        sim_matrix = self.temporal.readSimData(
            compartment=comp,
            outtype=outtype,
            param=param,
            id_layer=id_layer,
            syear=syear,
            eyear=eyear,
            tempDirectory=self.temp_directory,
        )


        # Generate date array as datetime64 
        #The np.arange trim with an open intervall [start date, end date)
        start_date = datetime.strptime(f"{syear}-08-01", "%Y-%m-%d")
        end_date = datetime.strptime(f"{eyear}-08-01", "%Y-%m-%d")
        dates = np.arange(
            np.datetime64(start_date),
            np.datetime64(end_date),
            dtype='datetime64[D]'
        )
        # Ensure data length matches dates (time axis = columns)
        if sim_matrix.shape[1] != len(dates):
            min_len = min(sim_matrix.shape[1], len(dates))
            sim_matrix = sim_matrix[:, :min_len]   # keep all cells, trim time columns
            dates = dates[:min_len]

        # Apply date slicing if requested
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
        return Comparator().calc_performance_metrics(sim=sim, obs=obs, metrics=metrics)

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
        comp = self.get_compartment(id_compartment)

        if comp.obs is not None:
            for layer in comp.mesh.mesh.values():
                verify_crs_match(
                    comp.obs.crs,
                    layer.crs,
                    context="observations vs mesh spatial linkage",
                )

        sim_response = self.extract_values(
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            syear=simsdate,
            eyear=simedate,
            id_layer=id_layer,
            cutsdate=plotstart,
            cutedate=plotend,
        )

        obs_response = self.read_observations(
            id_compartment=id_compartment,
            syear=simsdate,
            eyear=simedate,
        )

        sim_dates = sim_response.dates
        obs_dates = obs_response.dates

        # Per-obs-point sim+obs arrays
        obs_points_data = []
        if comp.obs is not None:
            for i, obs_point in enumerate(comp.obs.obs_points):
                sim_vals = sim_response.data[obs_point.id_cell - 1, :]
                if i < obs_response.data.shape[0]:
                    obs_vals = obs_response.data[i, :]
                else:
                    obs_vals = np.full(len(obs_dates), np.nan)

                obs_points_data.append({
                    'name': obs_point.name,
                    'id_cell': obs_point.id_cell,
                    'id_layer': obs_point.id_layer,
                    'id_point': obs_point.id_point,
                    'sim': sim_vals,
                    'obs': obs_vals,
                })

        # Unit conversion for HYD: obs_unit is the TARGET display unit.
        # CaWaQS sim is in m3/s; obs are natively in l/s.
        if comp.compartment == 'HYD' and obs_unit is not None:
            for pt in obs_points_data:
                if obs_unit == 'm3/s':
                    pt['obs'] = pt['obs'] * 1e-3
                elif obs_unit == 'l/s':
                    pt['sim'] = pt['sim'] * 1e3

        # Slice obs to plot range
        if len(obs_dates) > 0 and plotstart is not None and plotend is not None:
            d_start = np.datetime64(plotstart)
            d_end = np.datetime64(plotend)
            obs_mask = (obs_dates >= d_start) & (obs_dates <= d_end)
            obs_dates = obs_dates[obs_mask]
            for pt in obs_points_data:
                pt['obs'] = pt['obs'][obs_mask]

        # Apply steady-state obs aggregation
        if aggr is not None:
            for pt in obs_points_data:
                obs = pt['obs']
                if aggr == 'mean':
                    pt['obs'] = np.full_like(obs, np.nanmean(obs))
                elif aggr == 'min':
                    pt['obs'] = np.full_like(obs, np.nanmin(obs))
                elif aggr == 'max':
                    pt['obs'] = np.full_like(obs, np.nanmax(obs))
                elif isinstance(aggr, float):
                    pt['obs'] = np.full_like(obs, np.nanquantile(obs, aggr))

        # Compute performance criteria per obs point
        if compute_criteria and obs_points_data:
            for pt in obs_points_data:
                sim_for_crit = pt['sim']
                obs_for_crit = pt['obs']

                # Slice to criteria period if specified
                if crit_start is not None and crit_end is not None:
                    cs = np.datetime64(crit_start)
                    ce = np.datetime64(crit_end)
                    # sim aligned with sim_dates, obs aligned with obs_dates
                    sim_mask = (sim_dates >= cs) & (sim_dates <= ce)
                    obs_mask = (obs_dates >= cs) & (obs_dates <= ce)
                    sim_for_crit = sim_for_crit[sim_mask]
                    obs_for_crit = obs_for_crit[obs_mask]

                    # Align lengths (take the shorter)
                    n = min(len(sim_for_crit), len(obs_for_crit))
                    sim_for_crit = sim_for_crit[:n]
                    obs_for_crit = obs_for_crit[:n]

                pt['criteria'] = self.compute_performance_stats(
                    sim=sim_for_crit,
                    obs=obs_for_crit,
                    metrics=criteria_metrics,
                )

        # Per-extraction-point sim arrays
        ext_points_data = []
        if comp.extraction is not None:
            for ext_point in comp.extraction.ext_point:
                sim_vals = sim_response.data[ext_point.id_cell - 1, :]
                ext_points_data.append({
                    'name': ext_point.name,
                    'id_cell': ext_point.id_cell,
                    'id_layer': ext_point.id_layer,
                    'sim': sim_vals,
                })

        return {
            'sim_dates': sim_dates,
            'obs_dates': obs_dates,
            'compartment_name': comp.compartment,
            'obs_points': obs_points_data,
            'ext_points': ext_points_data,
        }

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
        comp = self.get_compartment(id_compartment)

        class _ExdStub:
            """Minimal stub providing the post_process_directory attribute."""
            def __init__(self, directory):
                self.post_process_directory = directory

        save = save_directory is not None
        exd_stub = _ExdStub(save_directory) if save else _ExdStub("")

        cells = self.spatial.buildAqOutcropping(
            exd=exd_stub,
            aq_compartment=comp,
            save=save,
        )
        return np.array([cell.id for cell in cells])

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
        return self.budget.calcInteranualBVariableNumpy(
            data=data,
            param=param,
            out_folder="",  # not used for computation, only for CSV in original
            agg=agg,
            fz=fz,
            sdate=sdate,
            edate=edate,
            cutsdate=cutsdate,
            cutedate=cutedate,
            pluriannual=pluriannual,
        )

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
        comp = self.get_compartment(id_compartment)
        return self.budget.calcInteranualHVariableNumpy(
            data=data,
            dates=dates,
            compartment=comp,
            output_folder=output_folder,
            output_name=output_name,
        )

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
        Renderer.plot_budget_barplot(
            data_dict=data_dict,
            plot_title=plot_title,
            output_folder=output_folder,
            output_name=output_name,
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
        interractiv: bool = True,
        staticpng: bool = True,
        staticpdf: bool = True,
        years: str = None,
    ):
        """Render hydrological regime plots. Delegates to Renderer."""
        Renderer.plot_hydrological_regime(
            data=data,
            obs_point_names=obs_point_names,
            month_labels=month_labels,
            var=var,
            units=units,
            savepath=savepath,
            interractiv=interractiv,
            staticpng=staticpng,
            staticpdf=staticpdf,
            years=years,
        )

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
    ):
        """Read sim+obs data and render to PDF.

        Uses _prepare_sim_obs_data for NumPy I/O + per-point slicing,
        then converts to DataFrames for Renderer.render_simobs_pdf.
        """
        # Default criteria metrics for PDF rendering
        pdf_criteria_metrics = ["n_obs", "pbias", "avg_ratio", "rmse", "nash", "kge"]

        data = self._prepare_sim_obs_data(
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            simsdate=simsdate,
            simedate=simedate,
            plotstart=plotstartdate,
            plotend=plotenddate,
            id_layer=id_layer,
            aggr=aggr,
            compute_criteria=True,
            criteria_metrics=pdf_criteria_metrics,
            crit_start=crit_start,
            crit_end=crit_end,
            obs_unit=obs_unit,
        )

        # --- Convert NumPy → DataFrames for Renderer ---
        sim_dates_idx = pd.DatetimeIndex(data['sim_dates'].astype('datetime64[D]'))
        obs_dates_idx = pd.DatetimeIndex(data['obs_dates'].astype('datetime64[D]'))

        # Build simdf: one column per unique cell id (keyed by id_cell)
        sim_columns = {}
        for pt in data['obs_points']:
            if pt['id_cell'] not in sim_columns:
                sim_columns[pt['id_cell']] = pt['sim']
        for pt in data['ext_points']:
            if pt['id_cell'] not in sim_columns:
                sim_columns[pt['id_cell']] = pt['sim']
        simdf = pd.DataFrame(sim_columns, index=sim_dates_idx)

        # Build obs_df: one column per obs point id_point
        obs_df = None
        if data['obs_points']:
            obs_df = pd.DataFrame(
                {pt['id_point']: pt['obs'] for pt in data['obs_points']},
                index=obs_dates_idx,
            )

        # Build obs/ext point info dicts (include pre-computed criteria)
        obs_points_info = [
            {'name': pt['name'], 'id_cell': pt['id_cell'],
             'id_layer': pt['id_layer'], 'id_point': pt['id_point'],
             'criteria': pt.get('criteria')}
            for pt in data['obs_points']
        ]
        ext_points_info = [
            {'name': pt['name'], 'id_cell': pt['id_cell'], 'id_layer': pt['id_layer']}
            for pt in data['ext_points']
        ]

        pdf_file_path = os.path.join(
            directory,
            name_file + "_" + plotstartdate + "_" + plotenddate + ".pdf"
        )

        Renderer.render_simobs_pdf(
            simdf=simdf,
            obs_df=obs_df,
            obs_points=obs_points_info,
            ext_points=ext_points_info,
            pdf_file_path=pdf_file_path,
            ylabel=ylabel,
            crit_start=crit_start,
            crit_end=crit_end,
            plotstartdate=plotstartdate,
            plotenddate=plotenddate,
        )

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
    ):
        """Read sim+obs data and render interactive Plotly figure.

        Uses _prepare_sim_obs_data for NumPy I/O + per-point slicing,
        then converts to per-point DataFrames for Renderer.render_simobs_interactive.
        """
        # Default criteria metrics for interactive rendering
        interactive_criteria_metrics = [
            "n_obs", "avg_ratio", "pbias", "std_ratio", "rmse", "nash", "kge",
        ]

        data = self._prepare_sim_obs_data(
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            simsdate=simsdate,
            simedate=simedate,
            plotstart=plotstart,
            plotend=plotend,
            aggr=aggr,
            compute_criteria=True,
            criteria_metrics=interactive_criteria_metrics,
            crit_start=critstart,
            crit_end=critend,
            obs_unit=obs_unit,
        )

        # --- Convert NumPy → per-point DataFrames for Renderer ---
        # Unit conversion already applied upstream in _prepare_sim_obs_data
        sim_dates_idx = pd.DatetimeIndex(data['sim_dates'].astype('datetime64[D]'))
        obs_dates_idx = pd.DatetimeIndex(data['obs_dates'].astype('datetime64[D]'))

        sim_obs_data = []
        criteria_per_point = []
        for pt in data['obs_points']:
            sim_series = pd.Series(pt['sim'], index=sim_dates_idx, name='sim')
            obs_series = pd.Series(pt['obs'], index=obs_dates_idx, name='obs')
            df_sim_obs = pd.concat([sim_series, obs_series], axis=1)
            df_sim_obs = df_sim_obs.loc[plotstart:plotend]
            sim_obs_data.append((df_sim_obs, pt['name']))
            criteria_per_point.append(pt.get('criteria'))

        Renderer.render_simobs_interactive(
            sim_obs_data=sim_obs_data,
            ylabel=ylabel,
            df_other_variable=df_other_variable,
            other_variable_config=other_variable_config,
            out_file_path=outFilePath,
            crit_start=critstart,
            crit_end=critend,
            criteria_per_point=criteria_per_point,
        )

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  L6 — GIT-SYNCHRONIZED REGISTRY  (identity & provenance)    ║
    # ╚════════════════════════════════════════════════════════════════╝
    # IdCard, fingerprinting, and version tracking will be added here.

    # ╔════════════════════════════════════════════════════════════════╗
    # ║  STAGING — implemented, not yet consumed by frontend         ║
    # ║  These APIs are ready for integration but have no caller     ║
    # ║  outside of tests.  Move them to the appropriate layer       ║
    # ║  once wired into the frontend.                               ║
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
            csv_path=csv_path,
            meta=meta,
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
