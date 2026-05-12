"""Coarse-grained, dialog-shaped client API for HydrologicalTwin.

The :class:`HydrologicalTwinClient` exposes one method per user-facing
operation that the QGIS plug-in surfaces in its dialogs. Each call wraps the
``fetch -> transform -> render`` chain so that notebook users (today) and a
future HTTP server (tomorrow) can reproduce a dialog operation with a single
call.

This module — and the rest of ``ht/client/`` — has zero ``qgis.*`` /
``PyQt5`` / ``processing`` imports.
"""

from __future__ import annotations

from . import operations
from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    HydrologicalRegimeResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
)


class HydrologicalTwinClient:
    """Coarse-grained, dialog-shaped API on top of :class:`HydrologicalTwin`.

    One method per user-facing operation surfaced by the QGIS plug-in. Each
    method wraps a ``fetch -> transform -> render`` chain into a single call
    that returns a typed result dataclass and is safe to drive from a
    notebook today, from an HTTP server tomorrow — no ``qgis.*`` / ``PyQt5``
    / ``processing`` imports anywhere in this package.

    Method bodies are intentionally thin (≤5 statements): they delegate to
    the matching :func:`operations.run_*` function, which owns the
    orchestration. Add a new operation by (1) defining a ``*Result``
    dataclass in :mod:`api_types`, (2) implementing ``run_<name>`` in
    :mod:`operations`, and (3) adding a one-line facade method here.

    Operations:

    - :meth:`budget_barplot` — water-balance bar plot (PNG + CSV)
    - :meth:`hydrological_regime` — discharge / piezometric-head regime
      plots (per-point PNGs and combined PDF)
    - :meth:`spatial_map_watbal` — single-variable WATBAL spatial map (gdf)
    - :meth:`spatial_map_aq` — AQ spatial map (gdf): head, fluxes,
      recharge, surface overflow
    - :meth:`compare_sim_obs` — sim-vs-obs comparison plot in PDF or
      interactive HTML mode
    """

    def __init__(self, twin):
        self.twin = twin

    def budget_barplot(self, **kwargs) -> BudgetBarplotResult:
        return operations.run_budget_barplot(self.twin, **kwargs)

    def hydrological_regime(self, **kwargs) -> HydrologicalRegimeResult:
        return operations.run_hydrological_regime(self.twin, **kwargs)

    def spatial_map_watbal(self, **kwargs) -> SpatialMapWatbalResult:
        return operations.run_spatial_map_watbal(self.twin, **kwargs)

    def spatial_map_aq(self, **kwargs) -> SpatialMapAqResult:
        return operations.run_spatial_map_aq(self.twin, **kwargs)

    def compare_sim_obs(self, **kwargs) -> CompareSimObsResult:
        return operations.run_compare_sim_obs(self.twin, **kwargs)
