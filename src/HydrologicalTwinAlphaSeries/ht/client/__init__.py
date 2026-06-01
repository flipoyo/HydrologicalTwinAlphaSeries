"""Client package — coarse-grained API on top of HydrologicalTwin.

See :class:`HydrologicalTwinClient` for the entry point.
"""

from ...services.public.automatic_detection_config import DetectionError
from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    CriteriaPointResult,
    HydrologicalRegimeResult,
    CompartmentCellsEntry,
    MaskAqBoundaryResult,
    MaskHydBoundaryResult,
    MaskInternalValuesResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
    StatisticalCriteriaResult,
)
from .hydrological_twin_client import HydrologicalTwinClient

__all__ = [
    "HydrologicalTwinClient",
    "DetectionError",
    "BudgetBarplotResult",
    "HydrologicalRegimeResult",
    "SpatialMapWatbalResult",
    "SpatialMapAqResult",
    "CompareSimObsResult",
    "StatisticalCriteriaResult",
    "CriteriaPointResult",
    "CompartmentCellsEntry",
    "MaskInternalValuesResult",
    "MaskHydBoundaryResult",
    "MaskAqBoundaryResult",
]
