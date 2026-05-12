"""Client package — coarse-grained API on top of HydrologicalTwin.

See :class:`HydrologicalTwinClient` for the entry point.
"""

from .api_types import BudgetBarplotResult, HydrologicalRegimeResult
from .hydrological_twin_client import HydrologicalTwinClient

__all__ = [
    "HydrologicalTwinClient",
    "BudgetBarplotResult",
    "HydrologicalRegimeResult",
]
