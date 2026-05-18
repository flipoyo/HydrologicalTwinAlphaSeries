"""Client package — coarse-grained API on top of HydrologicalTwin.

See :class:`HydrologicalTwinClient` for the entry point.
"""

from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    CriteriaPointResult,
    HydrologicalRegimeResult,
    MaskAqBoundaryResult,
    MaskHydBoundaryResult,
    MaskWatbalResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
    StatisticalCriteriaResult,
)
from .hydrological_twin_client import HydrologicalTwinClient

__all__ = [
    "HydrologicalTwinClient",
    "BudgetBarplotResult",
    "HydrologicalRegimeResult",
    "SpatialMapWatbalResult",
    "SpatialMapAqResult",
    "CompareSimObsResult",
    "StatisticalCriteriaResult",
    "CriteriaPointResult",
    "MaskWatbalResult",
    "MaskHydBoundaryResult",
    "MaskAqBoundaryResult",
]
