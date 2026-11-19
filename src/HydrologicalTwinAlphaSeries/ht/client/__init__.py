"""Client package — coarse-grained API on top of HydrologicalTwin.

See :class:`HydrologicalTwinClient` for the entry point.
"""

from ...services.public.automatic_detection_config import DetectionError
from ..developer.api_types import InvalidStateError
from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    CriteriaPointResult,
    HydrologicalRegimeResult,
    AqBoundaryLayerEntry,
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
    "InvalidStateError",
    "BudgetBarplotResult",
    "HydrologicalRegimeResult",
    "SpatialMapWatbalResult",
    "SpatialMapAqResult",
    "CompareSimObsResult",
    "StatisticalCriteriaResult",
    "CriteriaPointResult",
    "CompartmentCellsEntry",
    "AqBoundaryLayerEntry",
    "MaskInternalValuesResult",
    "MaskHydBoundaryResult",
    "MaskAqBoundaryResult",
]
