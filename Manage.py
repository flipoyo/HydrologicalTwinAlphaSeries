import warnings

warnings.warn(
    "Importing Manage from the package root is deprecated. "
    "Use HydrologicalTwin facade instead.",
    DeprecationWarning,
    stacklevel=2,
)

from HydrologicalTwinAlphaSeries.services.Manage import Manage

__all__ = ["Manage"]