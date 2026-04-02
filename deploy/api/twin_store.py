"""In-memory singleton for the HydrologicalTwin instance.

The quick-deployment server keeps exactly one twin in memory.
It is initialised via the ``POST /api/init/`` endpoint or by pointing
the ``HYDROTWIN_CONFIG_FILE`` environment variable at a JSON file that
the settings module will load at startup.
"""

from __future__ import annotations

from typing import Optional

from hydrological_twin_alpha_series.ht.hydrological_twin import HydrologicalTwin

_twin: Optional[HydrologicalTwin] = None


def get_twin() -> Optional[HydrologicalTwin]:
    """Return the current twin instance, or *None* if not yet initialised."""
    return _twin


def set_twin(twin: Optional[HydrologicalTwin]) -> None:
    """Replace the singleton twin instance (use *None* to clear)."""
    global _twin  # noqa: PLW0603
    _twin = twin
