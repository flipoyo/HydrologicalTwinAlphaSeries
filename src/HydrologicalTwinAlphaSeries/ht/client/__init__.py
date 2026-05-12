"""Client package — coarse-grained API on top of HydrologicalTwin.

See :class:`HydrologicalTwinClient` for the entry point.
"""

from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    HydrologicalRegimeResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
)
from .hydrological_twin_client import HydrologicalTwinClient

__all__ = [
    "HydrologicalTwinClient",
    "BudgetBarplotResult",
    "HydrologicalRegimeResult",
    "SpatialMapWatbalResult",
    "SpatialMapAqResult",
    "CompareSimObsResult",
]
