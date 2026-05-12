"""Result dataclasses for the HydrologicalTwinClient operations.

These types are user-facing: they expose the on-disk artefacts produced by
each client method. They are intentionally separate from the developer-side
api_types in ``..api_types`` so the client surface can evolve independently
(e.g. for future server transport).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


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


@dataclass(frozen=True)
class SpatialMapWatbalResult:
    """Result of :meth:`HydrologicalTwinClient.spatial_map_watbal`.

    :param gdf: GeoDataFrame holding the cell geometries plus the aggregated
        water-balance variable as an attribute column.
    :param layer_name: Composed display name for the layer
        (``"<param>_<syear><eyear> <fz> <agg>[<unit>]"``); the QGIS dialog uses
        it as-is when converting the GeoDataFrame to a vector layer.
    """

    gdf: Any
    layer_name: str


@dataclass(frozen=True)
class SpatialMapAqResult:
    """Result of :meth:`HydrologicalTwinClient.spatial_map_aq`.

    :param gdf: GeoDataFrame holding the AQ cell geometries plus the
        aggregated parameter as an attribute column.
    :param layer_name: Composed display name for the layer
        (``"<prefix>_<resolution>_<fz>_<agg>_[<unit>]"``).
    """

    gdf: Any
    layer_name: str


@dataclass(frozen=True)
class CompareSimObsResult:
    """Result of :meth:`HydrologicalTwinClient.compare_sim_obs`.

    :param mode: ``"pdf"`` or ``"interactive"``.
    :param pdf_path: Path to the PDF written in ``"pdf"`` mode, else ``None``.
    :param html_path: Path to the HTML written in ``"interactive"`` mode, else
        ``None``.
    :param output_directory: Directory the artefacts were written to (matches
        the ``directory`` / containing folder of ``out_file_path``).
    """

    mode: str
    pdf_path: Optional[str] = None
    html_path: Optional[str] = None
    output_directory: str = ""
