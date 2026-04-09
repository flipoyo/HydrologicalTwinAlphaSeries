from importlib.metadata import PackageNotFoundError, version

from HydrologicalTwinAlphaSeries.Compartment import Compartment  # noqa: F401
from HydrologicalTwinAlphaSeries.config import Config, ConfigGeometry, ConfigProject  # noqa: F401
from HydrologicalTwinAlphaSeries.Extraction import Extraction, ExtractionPoint  # noqa: F401
from HydrologicalTwinAlphaSeries.ht import HydrologicalTwin
from HydrologicalTwinAlphaSeries.Manage import Manage  # noqa: F401
from HydrologicalTwinAlphaSeries.Mesh import Mesh  # noqa: F401
from HydrologicalTwinAlphaSeries.Observations import Observation, ObsPoint  # noqa: F401
from HydrologicalTwinAlphaSeries.Renderer import Renderer  # noqa: F401
from HydrologicalTwinAlphaSeries.Vec_Operator import Comparator, Extractor, Operator  # noqa: F401

__all__ = ["HydrologicalTwin"]

try:
    __version__: str = version("HydrologicalTwinAlphaSeries")
except PackageNotFoundError:  # pragma: no cover - only when running from source without install
    __version__ = "0.0.0.dev0"