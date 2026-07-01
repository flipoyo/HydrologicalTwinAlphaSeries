"""The actual work behind the dispatch ladders.

Role
----
This module holds the *handlers*: module-level functions that perform the
heavy hydrological work invoked by ``dispatch.py``. Each takes a
``HydrologicalTwin`` instance (named ``twin``) as first argument, plus
whatever request-specific parameters the dispatch branch passes through.
Handlers call into ``services/`` (``Renderer``, ``Operator``, ``Extractor``,
``Comparator``) and into ``services/public/twin_io.py`` to read twin state.

What belongs here
-----------------
- ``compute_performance_stats``, ``compute_budget_variable``,
  ``compute_hydrological_regime``
- ``aggregate_for_map``
- ``_build_watbal_spatial_gdf``, ``_build_effective_rainfall_gdf``,
  ``_build_aq_spatial_gdf``, ``_build_aquifer_outcropping``
- ``_prepare_sim_obs_data``
- ``extract_area``
- ``apply_temporal_operator``, ``apply_spatial_average``
- ``render_budget_barplot``, ``render_hydrological_regime``,
  ``render_aq_flux_diagram``
- ``_render_sim_obs_pdf``, ``_render_sim_obs_interactive`` (leading
  underscore retained — these remain package-internal)

What does NOT belong here
-------------------------
- ``if request.kind == "X":`` ladders → ``dispatch.py``.
- Pure state reads / lookups (``get_*``, ``read_*``, ``_resolve_*``,
  ``has_observations``, ``_ensure_disk_cache``) → ``services/public/twin_io.py``.
- Lifecycle state transitions or gatekeeping → ``hydrological_twin_developer.py``.
- Argument coercion from legacy call shapes → ``hydrological_twin_developer.py``.

Relation to other modules
-------------------------
- Called by ``dispatch.py`` (the primary entry point).
- May be called directly by facade wrappers in ``hydrological_twin_developer.py``
  when the spec requires the surface to be kept on the class (e.g.
  ``compute_performance_stats`` is called by
  ``ht/client/operations_client.py::run_statistical_criteria``).
- Reads twin state via ``services/public/twin_io.py``.
- Does NOT import ``dispatch.py`` or ``hydrological_twin_developer.py`` at runtime —
  the ``HydrologicalTwin`` type hint comes via ``TYPE_CHECKING``.

Import direction (no backward edges)
------------------------------------
    L2: hydrological_twin_developer.py → dispatch.py → handlers.py
    L3: → services/public/twin_io.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.services.public.geodata_assembly import (
    assemble_multi_layer_geodataframe,
    assemble_single_layer_geodataframe,
)
from HydrologicalTwinAlphaSeries.services.public.twin_io import read_values
from HydrologicalTwinAlphaSeries.services.public.renderer import Renderer
from HydrologicalTwinAlphaSeries.services.public.spatial import Spatial
from HydrologicalTwinAlphaSeries.services.public.vec_operator import Comparator, Extractor, Operator
from HydrologicalTwinAlphaSeries.tools.spatial_utils import verify_crs_match

from .api_types import (
    SpatialAverageResponse,
    TemporalOpResponse,
    ValuesResponse,
)

if TYPE_CHECKING:
    from .hydrological_twin_developer import HydrologicalTwin  # noqa: F401


def compute_performance_stats(
    twin: "HydrologicalTwin",
    sim: np.ndarray,
    obs: np.ndarray,
    metrics: List[str] = None,
) -> dict:
    """Compute performance statistics between sim and obs arrays.

    Target layer: L3 — Estimation Layer.
    Delegates to Comparator.calc_performance_metrics.
    """
    return Comparator().calc_performance_metrics(sim=sim, obs=obs, metrics=metrics)


def _prepare_sim_obs_data(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    simsdate: int,
    simedate: int,
    plotstart: str = None,
    plotend: str = None,
    id_layer: int = 0,
    aggr: Union[None, float, str] = None,
    compute_criteria: bool = False,
    criteria_metrics: List[str] = None,
    crit_start: str = None,
    crit_end: str = None,
    obs_unit: str = None,
) -> dict:
    """Load sim+obs and build per-point NumPy arrays for rendering."""
    comp = twin.get_compartment(id_compartment)

    if comp.obs is not None:
        for layer in comp.mesh.mesh.values():
            verify_crs_match(
                comp.obs.crs,
                layer.crs,
                context="observations vs mesh spatial linkage",
            )

    # L3 ``read_values`` returns a raw ``(sim_matrix, dates)`` tuple — there is
    # no DTO-returning ``twin.read_values`` method (unlike ``read_observations``
    # / ``read_watbal_converted``). Unpack it here, matching ``dispatch.py`` and
    # ``twin_io.read_watbal_converted``.
    sim_matrix, sim_dates = read_values(
        twin=twin,
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        syear=simsdate,
        eyear=simedate,
        id_layer=id_layer,
        cutsdate=plotstart,
        cutedate=plotend,
    )

    obs_response = twin.read_observations(
        id_compartment=id_compartment,
        syear=simsdate,
        eyear=simedate,
    )

    obs_dates = obs_response.dates

    obs_points_data = []
    if comp.obs is not None:
        for i, obs_point in enumerate(comp.obs.obs_points):
            sim_vals = sim_matrix[obs_point.id_cell - 1, :]
            if i < obs_response.data.shape[0]:
                obs_vals = obs_response.data[i, :]
            else:
                obs_vals = np.full(len(obs_dates), np.nan)

            obs_points_data.append({
                'name': obs_point.name,
                'id_cell': obs_point.id_cell,
                'id_layer': obs_point.id_layer,
                'id_point': obs_point.id_point,
                'sim': sim_vals,
                'obs': obs_vals,
            })

    if comp.compartment == 'HYD' and obs_unit is not None:
        for pt in obs_points_data:
            if obs_unit == 'm3/s':
                pt['obs'] = pt['obs'] * 1e-3
            elif obs_unit == 'l/s':
                pt['sim'] = pt['sim'] * 1e3

    if len(obs_dates) > 0 and plotstart is not None and plotend is not None:
        d_start = np.datetime64(plotstart)
        d_end = np.datetime64(plotend)
        obs_mask = (obs_dates >= d_start) & (obs_dates <= d_end)
        obs_dates = obs_dates[obs_mask]
        for pt in obs_points_data:
            pt['obs'] = pt['obs'][obs_mask]

    if aggr is not None:
        for pt in obs_points_data:
            obs = pt['obs']
            if aggr == 'mean':
                pt['obs'] = np.full_like(obs, np.nanmean(obs))
            elif aggr == 'min':
                pt['obs'] = np.full_like(obs, np.nanmin(obs))
            elif aggr == 'max':
                pt['obs'] = np.full_like(obs, np.nanmax(obs))
            elif isinstance(aggr, float):
                pt['obs'] = np.full_like(obs, np.nanquantile(obs, aggr))

    if compute_criteria and obs_points_data:
        for pt in obs_points_data:
            sim_for_crit = pt['sim']
            obs_for_crit = pt['obs']

            if crit_start is not None and crit_end is not None:
                cs = np.datetime64(crit_start)
                ce = np.datetime64(crit_end)
                sim_mask = (sim_dates >= cs) & (sim_dates <= ce)
                obs_mask = (obs_dates >= cs) & (obs_dates <= ce)
                sim_for_crit = sim_for_crit[sim_mask]
                obs_for_crit = obs_for_crit[obs_mask]

                n = min(len(sim_for_crit), len(obs_for_crit))
                sim_for_crit = sim_for_crit[:n]
                obs_for_crit = obs_for_crit[:n]

            pt['criteria'] = twin.compute_performance_stats(
                sim=sim_for_crit,
                obs=obs_for_crit,
                metrics=criteria_metrics,
            )

    ext_points_data = []
    if comp.extraction is not None:
        for ext_point in comp.extraction.ext_point:
            sim_vals = sim_matrix[ext_point.id_cell - 1, :]
            ext_points_data.append({
                'name': ext_point.name,
                'id_cell': ext_point.id_cell,
                'id_layer': ext_point.id_layer,
                'sim': sim_vals,
            })

    return {
        'sim_dates': sim_dates,
        'obs_dates': obs_dates,
        'compartment_name': comp.compartment,
        'obs_points': obs_points_data,
        'ext_points': ext_points_data,
    }


def aggregate_for_map(
    twin: "HydrologicalTwin",
    data: np.ndarray,
    dates: np.ndarray,
    agg: Union[str, float],
    frequency: str,
    pluriannual: bool = False,
    year_end_month: int = 8,
    cell_ids: np.ndarray = None,
) -> pd.DataFrame:
    """Temporal aggregation returning DataFrame for GIS layer creation."""
    arr_t = data.T

    arr_agg, date_labels = Operator().t_transform(
        arr=arr_t,
        dates=dates,
        fz=frequency,
        agg=agg,
        year_end_month=year_end_month,
        plurianual_agg=pluriannual,
    )

    if cell_ids is None:
        cell_ids = np.arange(data.shape[0])

    df = pd.DataFrame(arr_agg, index=date_labels, columns=cell_ids)
    return df


def _build_watbal_spatial_gdf(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    syear: int,
    eyear: int,
    cutsdate: str,
    cutedate: str,
    id_layer: int,
    target_unit: str,
    agg: Union[str, float],
    frequency: str,
    pluriannual: bool,
) -> gpd.GeoDataFrame:
    """Extract, aggregate, and assemble a WATBAL spatial map GeoDataFrame."""
    comp_info = twin.get_compartment_info(id_compartment)
    layer_info = twin.get_layer_info(id_compartment, id_layer)

    response = twin.read_watbal_converted(
        id_compartment=id_compartment, outtype=outtype, param=param,
        syear=syear, eyear=eyear,
        cutsdate=cutsdate, cutedate=cutedate,
        id_layer=id_layer, target_unit=target_unit,
    )

    agg_df = twin.aggregate_for_map(
        data=response.data, dates=response.dates,
        agg=agg, frequency=frequency,
        pluriannual=pluriannual, year_end_month=8,
        cell_ids=comp_info.cell_ids,
    )

    return assemble_single_layer_geodataframe(
        agg_df=agg_df,
        cell_ids=layer_info.cell_ids,
        cell_geometries=layer_info.cell_geometries,
        crs=layer_info.crs,
    )


def _build_effective_rainfall_gdf(
    twin: "HydrologicalTwin",
    id_compartment: int,
    syear: int,
    eyear: int,
    cutsdate: str,
    cutedate: str,
    id_layer: int,
    agg: Union[str, float],
    frequency: str,
    pluriannual: bool,
) -> gpd.GeoDataFrame:
    """Extract rain & ETR, compute effective rainfall, aggregate, assemble GeoDataFrame."""
    comp_info = twin.get_compartment_info(id_compartment)
    layer_info = twin.get_layer_info(id_compartment, id_layer)

    rain = twin.read_watbal_converted(
        id_compartment=id_compartment, outtype="MB", param="rain",
        syear=syear, eyear=eyear,
        cutsdate=cutsdate, cutedate=cutedate,
        id_layer=id_layer, target_unit="mm/j",
    )
    etr = twin.read_watbal_converted(
        id_compartment=id_compartment, outtype="MB", param="etr",
        syear=syear, eyear=eyear,
        cutsdate=cutsdate, cutedate=cutedate,
        id_layer=id_layer, target_unit="mm/j",
    )

    pe_data = Operator.compute_effective_rainfall(rain.data, etr.data)

    agg_df = twin.aggregate_for_map(
        data=pe_data, dates=rain.dates,
        agg=agg, frequency=frequency,
        pluriannual=pluriannual, year_end_month=8,
        cell_ids=comp_info.cell_ids,
    )

    return assemble_single_layer_geodataframe(
        agg_df=agg_df,
        cell_ids=layer_info.cell_ids,
        cell_geometries=layer_info.cell_geometries,
        crs=layer_info.crs,
    )


def _build_aq_spatial_gdf(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    syear: int,
    eyear: int,
    cutsdate: str,
    cutedate: str,
    layers: list,
    agg: Union[str, float],
    frequency: str,
    pluriannual: bool,
    layer_id_offset: int = 0,
    outcropping_cell_ids: np.ndarray = None,
) -> gpd.GeoDataFrame:
    """Extract, aggregate, and assemble an AQ spatial map GeoDataFrame."""
    comp_info = twin.get_compartment_info(id_compartment)

    response = twin.read_values(
        id_compartment=id_compartment, outtype=outtype, param=param,
        syear=syear, eyear=eyear,
        id_layer=-9999,
        cutsdate=cutsdate, cutedate=cutedate,
    )

    agg_df = twin.aggregate_for_map(
        data=response.data, dates=response.dates,
        agg=agg, frequency=frequency,
        pluriannual=pluriannual, year_end_month=8,
        # Label the aggregated columns by MATRIX ROW order, not gdf order: the
        # full matrix row ``i`` is the cell whose absolute id (``id_abs``) is
        # ``i + 1``. The mesh gdf need not be ``Id_ABS``-sorted, so labelling by
        # ``getCellIdVector()`` / gdf order would mis-map columns. The
        # multi-layer assembly's ``.loc[id_abs]`` then selects the right rows.
        cell_ids=np.arange(1, response.data.shape[0] + 1),
    )

    crs = layers[0].crs if layers else None

    gdf = assemble_multi_layer_geodataframe(
        agg_df=agg_df, layers=layers,
        crs=crs, layer_id_offset=layer_id_offset,
    )

    if outcropping_cell_ids is not None:
        gdf = gdf.loc[gdf["ID_ABS"].isin(outcropping_cell_ids)]

    return gdf


def _aq_outcropping_cells(
    twin: "HydrologicalTwin",
    id_compartment: int,
    save_directory: Optional[str] = None,
    coverage_threshold: float = 0.5,
) -> list:
    """Return the cross-layer aquifer outcropping ``Cell`` list.

    Thin wrapper over ``Spatial.buildAqOutcropping`` (all of layer 0 plus
    deeper-layer cells not already covered, by areal overlap, by shallower
    cells). When ``save_directory`` is given, the ``id_abs`` list is also
    persisted to ``OUTPCROOPCELLSLIST.dat``. ``coverage_threshold`` is forwarded
    to ``buildAqOutcropping`` (see its docstring).
    """
    comp = twin.get_compartment(id_compartment)

    class _ExdStub:
        def __init__(self, directory):
            self.post_process_directory = directory

    save = save_directory is not None
    exd_stub = _ExdStub(save_directory) if save else _ExdStub("")

    return Spatial().buildAqOutcropping(
        exd=exd_stub,
        aq_compartment=comp,
        save=save,
        coverage_threshold=coverage_threshold,
    )


def _build_aquifer_outcropping(
    twin: "HydrologicalTwin",
    id_compartment: int,
    save_directory: str = None,
    coverage_threshold: float = 0.5,
) -> np.ndarray:
    """Build aquifer outcropping cell ID array. Wraps Spatial.buildAqOutcropping."""
    cells = _aq_outcropping_cells(
        twin, id_compartment, save_directory, coverage_threshold=coverage_threshold
    )
    # Return the global, unique ``id_abs`` (not the per-layer ``cell.id``) so
    # the spatial-map ``gdf["ID_ABS"].isin(...)`` filter matches each cell
    # uniquely across layers. ``buildAqOutcropping`` already persists id_abs.
    return np.array([cell.id_abs for cell in cells])


def _build_outcropping_mesh_gdf(
    twin: "HydrologicalTwin",
    id_compartment: int,
    coverage_threshold: float = 0.5,
) -> gpd.GeoDataFrame:
    """Return a cross-layer outcropping mesh GeoDataFrame for AQ masking.

    Each row is one outcropping cell (all of layer 0 plus deeper-layer cells
    whose centroid no shallower cell covers), carrying its global ``id_abs``,
    per-cell ``area``, and footprint ``geometry``. ``cells_in_polygon`` /
    ``cells_in_polygon_weighted`` run against this gdf with ``id_col="id_abs"``
    so polygon selection yields **global** ids directly — correct for a cell
    outcropping in any layer, not just layer 0.

    The CRS is taken from the compartment's layer-0 mesh (all layers share it).
    """
    cells = _aq_outcropping_cells(
        twin, id_compartment, save_directory=None,
        coverage_threshold=coverage_threshold,
    )
    comp = twin.get_compartment(id_compartment)
    crs = comp.mesh.mesh[0].crs if comp.mesh.mesh else None
    return gpd.GeoDataFrame(
        {
            "id_abs": [cell.id_abs for cell in cells],
            "area": [cell.area for cell in cells],
            "geometry": [cell.geometry for cell in cells],
        },
        crs=crs,
        geometry="geometry",
    )


def compute_budget_variable(
    twin: "HydrologicalTwin",
    data: np.ndarray,
    param: str,
    agg: str,
    fz: str,
    sdate: int,
    edate: int,
    cutsdate: str,
    cutedate: str,
    pluriannual: bool = False,
) -> tuple:
    """Compute interannual budget for a single variable."""
    return twin.budget.calcInteranualBVariableNumpy(
        data=data,
        param=param,
        out_folder="",
        agg=agg,
        fz=fz,
        sdate=sdate,
        edate=edate,
        cutsdate=cutsdate,
        cutedate=cutedate,
        pluriannual=pluriannual,
    )


def compute_hydrological_regime(
    twin: "HydrologicalTwin",
    id_compartment: int,
    data: np.ndarray,
    dates: np.ndarray,
    output_folder: str,
    output_name: str,
) -> tuple:
    """Compute hydrological regime (monthly interannual averages at obs points)."""
    comp = twin.get_compartment(id_compartment)
    return twin.budget.calcInteranualHVariableNumpy(
        data=data,
        dates=dates,
        compartment=comp,
        output_folder=output_folder,
        output_name=output_name,
    )


def render_budget_barplot(
    twin: "HydrologicalTwin",
    data_dict: dict,
    plot_title: str,
    output_folder: str = None,
    output_name: str = None,
    yaxis_unit: str = 'mm',
):
    """Render budget bar plot. Delegates to Renderer."""
    return Renderer.plot_budget_barplot(
        data_dict=data_dict,
        plot_title=plot_title,
        output_folder=output_folder,
        output_name=output_name,
        yaxis_unit=yaxis_unit,
    )


def render_hydrological_regime(
    twin: "HydrologicalTwin",
    data: np.ndarray,
    obs_point_names: list,
    month_labels: np.ndarray,
    var: str,
    units: str,
    savepath: str,
    interactive: bool = False,
    staticpng: bool = True,
    staticpdf: bool = True,
    years: str = None,
    **kwargs: Any,
):
    """Render hydrological regime plots. Delegates to Renderer."""
    legacy_interactive = kwargs.pop("interractiv", None)
    if legacy_interactive is not None:
        interactive = legacy_interactive
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected keyword arguments: {unexpected}")

    return Renderer.plot_hydrological_regime(
        data=data,
        obs_point_names=obs_point_names,
        month_labels=month_labels,
        var=var,
        units=units,
        savepath=savepath,
        interactive=interactive,
        staticpng=staticpng,
        staticpdf=staticpdf,
        years=years,
    )


def _render_sim_obs_pdf(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    simsdate: int,
    simedate: int,
    plotstartdate: str,
    plotenddate: str,
    id_layer: int,
    directory: str,
    name_file: str,
    ylabel: str,
    obs_unit: str,
    crit_start: str = None,
    crit_end: str = None,
    aggr: Union[None, float, str] = None,
) -> List[str]:
    """Read sim+obs data and render to PDF."""
    pdf_criteria_metrics = ["n_obs", "pbias", "avg_ratio", "rmse", "nash", "kge"]

    data = _prepare_sim_obs_data(
        twin,
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        simsdate=simsdate,
        simedate=simedate,
        plotstart=plotstartdate,
        plotend=plotenddate,
        id_layer=id_layer,
        aggr=aggr,
        compute_criteria=True,
        criteria_metrics=pdf_criteria_metrics,
        crit_start=crit_start,
        crit_end=crit_end,
        obs_unit=obs_unit,
    )

    sim_dates_idx = pd.DatetimeIndex(data['sim_dates'].astype('datetime64[D]'))
    obs_dates_idx = pd.DatetimeIndex(data['obs_dates'].astype('datetime64[D]'))

    sim_columns = {}
    for pt in data['obs_points']:
        if pt['id_cell'] not in sim_columns:
            sim_columns[pt['id_cell']] = pt['sim']
    for pt in data['ext_points']:
        if pt['id_cell'] not in sim_columns:
            sim_columns[pt['id_cell']] = pt['sim']
    simdf = pd.DataFrame(sim_columns, index=sim_dates_idx)

    obs_df = None
    if data['obs_points']:
        obs_df = pd.DataFrame(
            {pt['id_point']: pt['obs'] for pt in data['obs_points']},
            index=obs_dates_idx,
        )

    obs_points_info = [
        {'name': pt['name'], 'id_cell': pt['id_cell'],
         'id_layer': pt['id_layer'], 'id_point': pt['id_point'],
         'criteria': pt.get('criteria')}
        for pt in data['obs_points']
    ]
    ext_points_info = [
        {'name': pt['name'], 'id_cell': pt['id_cell'], 'id_layer': pt['id_layer']}
        for pt in data['ext_points']
    ]

    pdf_file_path = os.path.join(
        directory,
        name_file + "_" + plotstartdate + "_" + plotenddate + ".pdf"
    )

    return Renderer.render_simobs_pdf(
        simdf=simdf,
        obs_df=obs_df,
        obs_points=obs_points_info,
        ext_points=ext_points_info,
        pdf_file_path=pdf_file_path,
        ylabel=ylabel,
        crit_start=crit_start,
        crit_end=crit_end,
        plotstartdate=plotstartdate,
        plotenddate=plotenddate,
    )


def _render_sim_obs_interactive(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    simsdate: int,
    simedate: int,
    plotstart: str,
    plotend: str,
    obs_unit: str,
    ylabel: str,
    df_other_variable: pd.DataFrame = None,
    other_variable_config: dict = None,
    out_file_path: str = None,
    crit_start: str = None,
    crit_end: str = None,
    aggr: Union[None, float, str] = None,
) -> List[str]:
    """Read sim+obs data and render interactive Plotly figure."""
    interactive_criteria_metrics = [
        "n_obs", "avg_ratio", "pbias", "std_ratio", "rmse", "nash", "kge",
    ]

    data = _prepare_sim_obs_data(
        twin,
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        simsdate=simsdate,
        simedate=simedate,
        plotstart=plotstart,
        plotend=plotend,
        aggr=aggr,
        compute_criteria=True,
        criteria_metrics=interactive_criteria_metrics,
        crit_start=crit_start,
        crit_end=crit_end,
        obs_unit=obs_unit,
    )

    sim_dates_idx = pd.DatetimeIndex(data['sim_dates'].astype('datetime64[D]'))
    obs_dates_idx = pd.DatetimeIndex(data['obs_dates'].astype('datetime64[D]'))

    sim_obs_data = []
    criteria_per_point = []
    for pt in data['obs_points']:
        sim_series = pd.Series(pt['sim'], index=sim_dates_idx, name='sim')
        obs_series = pd.Series(pt['obs'], index=obs_dates_idx, name='obs')
        df_sim_obs = pd.concat([sim_series, obs_series], axis=1)
        df_sim_obs = df_sim_obs.loc[plotstart:plotend]
        sim_obs_data.append((df_sim_obs, pt['name']))
        criteria_per_point.append(pt.get('criteria'))

    return Renderer.render_simobs_interactive(
        sim_obs_data=sim_obs_data,
        ylabel=ylabel,
        df_other_variable=df_other_variable,
        other_variable_config=other_variable_config,
        out_file_path=out_file_path,
        crit_start=crit_start,
        crit_end=crit_end,
        criteria_per_point=criteria_per_point,
    )


def render_aq_flux_diagram(
    twin: "HydrologicalTwin",
    tables: Optional[Dict[str, Any]],
    output_folder: Optional[str],
    output_name: Optional[str] = None,
    colors: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Render aquifer-balance artefacts from transformed workflow tables."""
    if tables is None:
        raise ValueError("render_aq_flux_diagram() requires transformed aquifer tables.")

    output_directory = Path(
        output_folder or twin.temp_directory or twin.out_caw_directory or "."
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    base_name = output_name or "aq_flux"

    mass_balance = tables.get("mass_balance")
    flux = tables.get("flux")
    if mass_balance is None or flux is None:
        raise ValueError("Aquifer render tables must contain 'mass_balance' and 'flux'.")

    mass_balance_path = output_directory / f"{base_name}_mass_balance.csv"
    flux_path = output_directory / f"{base_name}_flux.csv"
    html_path = output_directory / f"{base_name}_diagram.html"

    mass_balance.to_csv(mass_balance_path, index=False)
    flux.to_csv(flux_path, index=False)

    try:
        import plotly.graph_objects as go

        node_labels = list(dict.fromkeys(list(flux["source"]) + list(flux["target"])))
        node_lookup = {label: index for index, label in enumerate(node_labels)}

        link_colors = None
        if colors:
            link_colors = [colors.get(label, "#5f7d95") for label in flux["term"]]

        sankey = go.Figure(
            data=[
                go.Sankey(
                    node={
                        "label": node_labels,
                        "pad": 18,
                        "thickness": 18,
                    },
                    link={
                        "source": [node_lookup[label] for label in flux["source"]],
                        "target": [node_lookup[label] for label in flux["target"]],
                        "value": flux["value"],
                        "color": link_colors,
                        "label": flux["term"],
                    },
                )
            ]
        )
        sankey.update_layout(title_text="Aquifer Flux Diagram")
        sankey.write_html(html_path)
    except Exception:
        html_path.write_text(
            (
                "<html><body><h1>Aquifer Flux Diagram</h1>"
                "<p>Plotly rendering failed.</p></body></html>"
            ),
            encoding="utf-8",
        )

    return [str(mass_balance_path), str(flux_path), str(html_path)]


def extract_area(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    syear: int,
    eyear: int,
    cell_ids: Optional[np.ndarray] = None,
    spatial_operator: Optional[str] = None,
    id_layer: int = 0,
    cutsdate: Optional[str] = None,
    cutedate: Optional[str] = None,
    output_csv_path: Optional[Union[str, Path]] = None,
    **operator_kwargs: Any,
) -> ValuesResponse:
    """Extract simulated values for specific cells (area subset)."""
    comp = twin.get_compartment(id_compartment)

    full_response = twin.read_values(
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        syear=syear,
        eyear=eyear,
        id_layer=id_layer,
        cutsdate=cutsdate,
        cutedate=cutedate,
    )

    subset_data = Extractor().apply_spatial_mask(
        data=full_response.data,
        cell_ids=cell_ids.tolist() if isinstance(cell_ids, np.ndarray) else cell_ids,
        compartment=comp,
        spatial_operator=spatial_operator,
        spatial_manager=Spatial(),
        **operator_kwargs
    )

    csv_path: Optional[Path] = None
    if output_csv_path is not None:
        suffix = f"_{spatial_operator}" if spatial_operator else "_area"
        csv_path = Path(
            output_csv_path +
            f"/{comp.compartment}_{param}_{outtype}_{syear}-{eyear}{suffix}.csv"
        )

        n_cells = subset_data.shape[0]
        if cell_ids is not None:
            header = 'Date\t' + '\t'.join([f'Cell_{cid}' for cid in cell_ids])
        else:
            header = 'Date\t' + '\t'.join([f'Cell_{i}' for i in range(n_cells)])

        with open(csv_path, 'w') as f:
            f.write(header + '\n')
            for t, date in enumerate(full_response.dates):
                date_str = str(date)[:10]
                row_data = '\t'.join(f'{val:.6f}' for val in subset_data[:, t])
                f.write(f'{date_str}\t{row_data}\n')

    meta = {
        "id_compartment": id_compartment,
        "outtype": outtype,
        "param": param,
        "syear": syear,
        "eyear": eyear,
        "id_layer": id_layer,
        "n_cells": subset_data.shape[0],
    }

    if spatial_operator:
        meta["spatial_operator"] = spatial_operator
        meta["operator_kwargs"] = operator_kwargs
    elif cell_ids is not None:
        meta["cell_ids"] = cell_ids.tolist() if isinstance(cell_ids, np.ndarray) else cell_ids

    return ValuesResponse(
        data=subset_data,
        dates=full_response.dates,
        csv_path=csv_path,
        meta=meta,
    )


def apply_temporal_operator(
    twin: "HydrologicalTwin",
    arr: np.ndarray,
    dates: np.ndarray,
    column_names: Optional[np.ndarray],
    agg_dimension: Union[str, float],
    frequency: str,
    pluriennial: bool = False,
    year_end_month: int = 12,
) -> TemporalOpResponse:
    """Apply a temporal aggregation on a time series numpy array."""
    arr_agg, date_labels = Operator().t_transform(
        arr=arr,
        dates=dates,
        fz=frequency,
        agg=agg_dimension,
        year_end_month=year_end_month,
        plurianual_agg=pluriennial,
    )

    meta = {
        "agg_dimension": agg_dimension,
        "frequency": frequency,
        "pluriennial": pluriennial,
        "year_end_month": year_end_month,
        "method": "numpy",
        "shape": arr_agg.shape,
    }
    if column_names is not None:
        meta["column_names"] = list(column_names)

    return TemporalOpResponse(
        data=arr_agg,
        date_labels=date_labels,
        meta=meta,
    )


def apply_spatial_average(
    twin: "HydrologicalTwin",
    id_compartment: int,
    data: np.ndarray,
    operation: str,
    areas: Optional[np.ndarray] = None,
) -> SpatialAverageResponse:
    """Apply spatial averaging to simulation data."""
    comp = twin.get_compartment(id_compartment)

    averaged_data = Operator.sp_operator(
        data=data,
        operation=operation,
        areas=areas,
        compartment=comp
    )

    return SpatialAverageResponse(
        data=averaged_data,
        meta={
            "id_compartment": id_compartment,
            "operation": operation,
            "n_timesteps": len(averaged_data),
            "original_n_cells": data.shape[0],
        },
    )
