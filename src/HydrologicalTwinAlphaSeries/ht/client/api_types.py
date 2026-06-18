"""Result dataclasses for the HydrologicalTwinClient operations.

These types are user-facing: they expose the on-disk artefacts produced by
each client method. They are intentionally separate from the developer-side
api_types in ``..api_types`` so the client surface can evolve independently
(e.g. for future server transport).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
class CriteriaPointResult:
    """Per-observation-point statistical-criteria result.

    :param name: Display name of the observation point.
    :param point_id: External id of the observation point.
    :param layer_id: Index of the aquifer / hydro layer the point sits on.
    :param geometry: Geometry of the point (e.g. shapely / WKT-compatible);
        the dialog converts this to a QGIS feature.
    :param criteria: Metric-key → numeric value mapping computed by the
        criteria transform.
    """

    name: str
    point_id: Any
    layer_id: Any
    geometry: Any
    criteria: dict


@dataclass(frozen=True)
class StatisticalCriteriaResult:
    """Result of :meth:`HydrologicalTwinClient.statistical_criteria`.

    :param points: Per-observation-point criteria (one entry per point).
    :param metrics: Ordered list of metric keys actually computed; matches
        both the text-file header columns and the keys in
        :attr:`CriteriaPointResult.criteria`.
    :param compartment_name: ``"AQ"`` or ``"HYD"``.
    :param period: ``(crit_start, crit_end)`` as ``YYYY-MM-DD`` strings.
    :param txt_path: Path to the per-point criteria text file.
    :param aq_layer_txt_path: Path to the AQ globals+by-layer text file
        (only set when ``compartment_name == "AQ"``).
    """

    points: List[CriteriaPointResult] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    compartment_name: str = ""
    period: tuple = ("", "")
    txt_path: str = ""
    aq_layer_txt_path: Optional[str] = None


@dataclass(frozen=True)
class CompareSimObsResult:
    """Result of :meth:`HydrologicalTwinClient.compare_sim_obs`.

    :param mode: ``"pdf"``, ``"interactive"`` or ``"csv"``.
    :param pdf_path: Path to the PDF written in ``"pdf"`` mode, else ``None``.
    :param html_path: Path to the HTML written in ``"interactive"`` mode, else
        ``None``.
    :param csv_data: The assembled daily sim/obs table returned in ``"csv"``
        mode, else ``None``. In ``csv`` mode the backend writes no file — the
        frontend persists this DataFrame to disk. Typed loosely as ``Any`` so
        this user-facing module stays free of a hard ``pandas`` import.
    :param output_directory: Directory the artefacts were written to (matches
        the ``directory`` / containing folder of ``out_file_path``). In
        ``csv`` mode this is the directory the frontend should write into.
    """

    mode: str
    pdf_path: Optional[str] = None
    html_path: Optional[str] = None
    csv_data: Optional[Any] = None
    output_directory: str = ""


@dataclass(frozen=True)
class CompartmentCellsEntry:
    """A single compartment's masked-cells GeoDataFrame + layer name.

    One entry per distinct compartment named in the ``specs`` of a
    :meth:`HydrologicalTwinClient.mask_internal_values` call. A single polygon
    selects a *different* cell set from each compartment's mesh, so the result
    carries one of these per compartment rather than a single ``gdf``.

    :param compartment: Compartment name (e.g. ``"WATBAL"``, ``"AQ"``).
    :param gdf: GeoDataFrame of the masked cells for this compartment, already
        joined to their mesh geometries. The caller can pass this straight to
        ``convertGdfToVectorLayer``. The geometry semantics depend on the
        ``weighted`` flag:

        * ``weighted=False`` (default): full cell footprints, no ``weight``
          column.
        * ``weighted=True``: per-cell clipped intersection geometries
          (``cell.intersection(polygon)``), with an additional numeric
          ``weight`` column in ``(0, 1]``.

    :param layer_name: Display name for this compartment's cells layer.
    """

    compartment: str
    gdf: Any
    layer_name: str


@dataclass(frozen=True)
class MaskInternalValuesResult:
    """Result of :meth:`HydrologicalTwinClient.mask_internal_values`.

    A single masked polygon selects a distinct cell set from each
    compartment's mesh, so the produced cells are grouped **per compartment**
    rather than exposed as one flat ``gdf``. Single-compartment callers simply
    iterate one entry.

    :param entries: One :class:`CompartmentCellsEntry` per distinct
        compartment named in ``specs`` (e.g. one WATBAL entry and one AQ
        entry), in first-seen spec order.
    :param artefacts: Flat on-disk artefact path list across all compartments,
        one CSV + one .npy per requested ``(compartment, param)`` spec (plus
        the per-spec polygon-total CSVs when ``weighted=True``, plus the
        ``.gpkg`` when ``write_geopackage=True``).
    :param polygon_total_paths: Only populated when the call ran with
        ``weighted=True``. Maps each requested ``(compartment, param)`` spec to
        the absolute path of its one-column ``date, polygon_total`` CSV, in the
        caller-selected ``unit`` (``m3/s`` | ``m3/j``, default ``m3/j``); the
        unit is encoded in the CSV filename token. Stays ``None`` on the binary
        (unweighted) path.
    """

    entries: List[CompartmentCellsEntry] = field(default_factory=list)
    artefacts: List[str] = field(default_factory=list)
    polygon_total_paths: Optional[Dict[tuple, str]] = None


@dataclass(frozen=True)
class MaskHydBoundaryResult:
    """Result of :meth:`HydrologicalTwinClient.mask_hyd_boundary`.

    :param boundary_gdf: GeoDataFrame of HYD reaches that intersect the
        polygon boundary (geometries are the original reach polylines).
    :param inside_gdf: GeoDataFrame of HYD reaches that lie inside the
        polygon (centroid-in test). Includes the boundary reaches with an
        ``is_boundary`` column.
    :param flux_gdf: Point GeoDataFrame of boundary crossings — one point
        per (reach × polygon-exterior) intersection, with a ``reach_id``
        attribute.
    :param layer_names: Display names for the three layers, in
        ``(inside, flux, boundary)`` order. ``flux`` may be ``None`` when
        no crossings are found.
    :param artefacts: On-disk artefact paths (one CSV with the per-reach
        signed-Q time series, when fluxes are non-empty).
    """

    boundary_gdf: Any
    inside_gdf: Any
    flux_gdf: Any
    layer_names: tuple = ("", "", "")
    artefacts: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MaskAqBoundaryResult:
    """Result of :meth:`HydrologicalTwinClient.mask_aq_boundary`.

    :param cells_gdf: GeoDataFrame of AQ boundary edges (one feature per
        edge, with a ``cell_id`` attribute).
    :param flux_gdf: Placeholder for a future flux gdf; currently unused
        (the time-series live in the CSV artefact).
    :param layer_names: Display names for the layers, ``(cells, flux)``;
        ``flux`` is ``None`` when no fluxes are emitted.
    :param artefacts: On-disk artefact paths (one CSV with per-(cell, dir)
        flux time series in m³/d, when fluxes are non-empty).
    """

    cells_gdf: Any
    flux_gdf: Any
    layer_names: tuple = ("", "")
    artefacts: List[str] = field(default_factory=list)
