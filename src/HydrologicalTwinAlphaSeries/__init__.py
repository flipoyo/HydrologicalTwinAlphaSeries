from importlib.metadata import PackageNotFoundError, version

from HydrologicalTwinAlphaSeries.config import Config, ConfigGeometry, ConfigProject
from HydrologicalTwinAlphaSeries.ht import HydrologicalTwin

__all__ = ["Config", "ConfigGeometry", "ConfigProject", "HydrologicalTwin"]

try:
    __version__: str = version("HydrologicalTwinAlphaSeries")
except PackageNotFoundError:  # pragma: no cover - only when running from source without install
    __version__ = "0.0.0.dev0"
