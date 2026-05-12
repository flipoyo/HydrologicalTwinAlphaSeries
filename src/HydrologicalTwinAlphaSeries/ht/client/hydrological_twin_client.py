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
    HydrologicalRegimeResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
)


class HydrologicalTwinClient:
    """Facade over a configured :class:`HydrologicalTwin`.

    Each public method body is intentionally thin (≤5 statements):
    it builds a result by delegating to the matching ``operations.run_*``
    function. All orchestration logic lives in :mod:`operations`.
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
