"""Coarse-grained, dialog-shaped client API for HydrologicalTwin.

The :class:`HydrologicalTwinClient` exposes one method per user-facing
operation that the QGIS plug-in surfaces in its dialogs, plus the lifecycle
primitives (``configure`` / ``load`` / ``describe`` / ``is_ready``) and a
one-call ``build`` classmethod that runs the lifecycle end-to-end. Each
operation call wraps the ``fetch -> transform -> render`` chain so that
notebook users (today) and a future HTTP server (tomorrow) can reproduce a
dialog operation with a single call.

This module — and the rest of ``ht/client/`` — has zero ``qgis.*`` /
``PyQt5`` / ``processing`` imports.
"""

from __future__ import annotations

from ...services.public.automatic_detection_config import (
    detect_from_out_caw,
    detect_project_neighbors,
)
from ..developer import HydrologicalTwin
from . import operations_client
from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    HydrologicalRegimeResult,
    MaskAqBoundaryResult,
    MaskHydBoundaryResult,
    MaskInternalValuesResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
    StatisticalCriteriaResult,
)


class HydrologicalTwinClient:
    """Coarse-grained, dialog-shaped API on top of :class:`HydrologicalTwin`.

    One method per user-facing operation surfaced by the QGIS plug-in. Each
    method wraps a ``fetch -> transform -> render`` chain into a single call
    that returns a typed result dataclass and is safe to drive from a
    notebook today, from an HTTP server tomorrow — no ``qgis.*`` / ``PyQt5``
    / ``processing`` imports anywhere in this package.

    Method bodies are intentionally thin (≤5 statements): they delegate to
    the matching :func:`operations_client.run_*` function, which owns the
    orchestration. Add a new operation by (1) defining a ``*Result``
    dataclass in :mod:`api_types`, (2) implementing ``run_<name>`` in
    :mod:`operations_client`, and (3) adding a one-line facade method here.

    Pre-lifecycle discovery (static, no twin required):

    - :meth:`detect_from_out_caw` — scan a CaWaQS output directory and
      return ``{compartments, s_year, e_year, regime, warnings}``. Raises
      :class:`DetectionError` if the folder is not interpretable.
    - :meth:`detect_project_neighbors` — given a QGIS project file path
      (or ``None``), best-effort lookup of ``{geometry_config_path,
      obs_directory, project_name}``. Each field may be ``None``
      independently; the function never raises on missing neighbors.

    These run *before* a client is constructed: they take filesystem
    paths and return plain dicts the caller uses to fill the inputs to
    :meth:`configure` / :meth:`load`. Same import surface, same return
    shape, whether the caller is the QGIS dialog, a notebook, or a
    future HTTP server.

    Lifecycle:

    - :meth:`__init__` — construct from metadata; the underlying twin starts
      in ``EMPTY`` state.
    - :meth:`configure` / :meth:`load` — primitives that forward to the
      underlying twin; callers (e.g. ``ExploreData``) wrap each call to map
      developer-side errors to application-level ones.
    - :meth:`describe` / :meth:`is_ready` — cheap inspection helpers.
    - :meth:`build` — classmethod that runs ``configure`` + ``load`` in one
      call; convenience entry point for notebook users.

    Operations:

    - :meth:`budget_barplot` — water-balance bar plot (PNG + CSV)
    - :meth:`hydrological_regime` — discharge / piezometric-head regime
      plots (per-point PNGs and combined PDF)
    - :meth:`spatial_map_watbal` — single-variable WATBAL spatial map (gdf)
    - :meth:`spatial_map_aq` — AQ spatial map (gdf): head, fluxes,
      recharge, surface overflow
    - :meth:`compare_sim_obs` — sim-vs-obs comparison plot in PDF or
      interactive HTML mode
    - :meth:`statistical_criteria` — per-observation-point performance
      metrics (KGE, NSE, RMSE, ...) plus globals/by-layer for AQ
    - :meth:`mask_internal_values` — per-spec compartment cell masking
      (WATBAL params + AQ recharge) with persisted artefacts and one
      mesh-joined gdf per compartment
    - :meth:`mask_hyd_boundary` — HYD reaches on a polygon boundary plus
      inside-reaches plus boundary fluxes
    - :meth:`mask_aq_boundary` — AQ cells inside a polygon plus boundary
      fluxes
    """

    def __init__(self, metadata: dict):
        self._twin = HydrologicalTwin(metadata=metadata)

    def configure(self, **kwargs):
        return self._twin.configure(**kwargs)

    def load(self, **kwargs):
        return self._twin.load(**kwargs)

    def describe(self):
        return self._twin.describe()

    def is_ready(self) -> bool:
        return self._twin.state.value in {"LOADED", "READY"}

    @classmethod
    def build(cls, metadata: dict, *, configure_kwargs: dict, load_kwargs: dict) -> "HydrologicalTwinClient":
        client = cls(metadata)
        client.configure(**configure_kwargs)
        client.load(**load_kwargs)
        return client

    @staticmethod
    def detect_from_out_caw(out_caw_directory: str) -> dict:
        return detect_from_out_caw(out_caw_directory)

    @staticmethod
    def detect_project_neighbors(project_file_path) -> dict:
        return detect_project_neighbors(project_file_path)


    def budget_barplot(self, **kwargs) -> BudgetBarplotResult:
        return operations_client.run_budget_barplot(self._twin, **kwargs)

    def hydrological_regime(self, **kwargs) -> HydrologicalRegimeResult:
        return operations_client.run_hydrological_regime(self._twin, **kwargs)

    def spatial_map_watbal(self, **kwargs) -> SpatialMapWatbalResult:
        return operations_client.run_spatial_map_watbal(self._twin, **kwargs)

    def spatial_map_aq(self, **kwargs) -> SpatialMapAqResult:
        return operations_client.run_spatial_map_aq(self._twin, **kwargs)

    def compare_sim_obs(self, **kwargs) -> CompareSimObsResult:
        return operations_client.run_compare_sim_obs(self._twin, **kwargs)

    def statistical_criteria(self, **kwargs) -> StatisticalCriteriaResult:
        return operations_client.run_statistical_criteria(self._twin, **kwargs)

    def mask_internal_values(
        self, *, weighted: bool = True, **kwargs
    ) -> MaskInternalValuesResult:
        # ``weighted`` is broken out from kwargs so it appears in the public
        # signature; the output unit is now carried per-spec as the 4th element
        # of each ``(compartment, outtype, param, unit)`` tuple in ``specs``.
        # See :func:`operations_client.run_mask_internal_values` for the ``specs``
        # shape, the unit token table, and semantics.
        return operations_client.run_mask_internal_values(
            self._twin, weighted=weighted, **kwargs
        )

    def mask_hyd_boundary(self, **kwargs) -> MaskHydBoundaryResult:
        return operations_client.run_mask_hyd_boundary(self._twin, **kwargs)

    def mask_aq_boundary(self, **kwargs) -> MaskAqBoundaryResult:
        return operations_client.run_mask_aq_boundary(self._twin, **kwargs)
