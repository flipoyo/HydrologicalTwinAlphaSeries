"""Result dataclasses for the HydrologicalTwinClient operations.

These types are user-facing: they expose the on-disk artefacts produced by
each client method. They are intentionally separate from the developer-side
api_types in ``..api_types`` so the client surface can evolve independently
(e.g. for future server transport).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class BudgetBarplotResult:
    """Result of :meth:`HydrologicalTwinClient.budget_barplot`.

    :param png_path: Path to the static PNG file written by the renderer.
    :param csv_path: Path to the CSV file with the budget values.
    """

    png_path: str
    csv_path: str


@dataclass(frozen=True)
class HydrologicalRegimeResult:
    """Result of :meth:`HydrologicalTwinClient.hydrological_regime`.

    :param png_paths: Paths to the per-observation-point static PNGs (empty if
        ``staticpng=False``).
    :param pdf_path: Path to the combined PDF, or ``None`` if ``staticpdf=False``.
    :param savepath: Output directory in which the artefacts were written.
    """

    png_paths: List[str] = field(default_factory=list)
    pdf_path: Optional[str] = None
    savepath: str = ""
