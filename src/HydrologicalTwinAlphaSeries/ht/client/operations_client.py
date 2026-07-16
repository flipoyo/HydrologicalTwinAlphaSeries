"""L1 · HT CLIENT · MACRO — orchestration for :class:`HydrologicalTwinClient`.

Each ``run_<name>`` owns the ``fetch → transform → render`` chain for one dialog
operation. Zero ``qgis.*`` / ``PyQt5`` / ``processing`` imports.
"""

from __future__ import annotations

import os
from typing import Sequence, Tuple

import numpy as np

from HydrologicalTwinAlphaSeries.config.constants import _LENGTH_UNITS
from HydrologicalTwinAlphaSeries.services.private.raw_data_export import (
    assemble_daily_sim_obs_table,
)

from .api_types import (
    AqBoundaryLayerEntry,
    BudgetBarplotResult,
    CompareSimObsResult,
    CompartmentCellsEntry,
    CriteriaPointResult,
    HydrologicalRegimeResult,
    MaskAqBoundaryResult,
    MaskHydBoundaryResult,
    MaskInternalValuesResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
    StatisticalCriteriaResult,
)


def _resolve_compartment_id(twin, name: str) -> int:
    """Look up a compartment integer id from its string name on a raw twin."""
    for info in twin.list_compartments():
        if info.name == name:
            return info.id_compartment
    raise ValueError(
        f"Compartment {name!r} not found on twin (known: "
        f"{[c.name for c in twin.list_compartments()]})"
    )


def run_budget_barplot(
    twin,
    period: Tuple[str, str],
    frequency: str,
    agg: str,
    pluriannual: bool,
    output_dir: str,
    variables: Sequence[str] = ("rain", "etr", "inf", "runoff"),
    frequency_label: str = None,
    agg_label: str = None,
) -> BudgetBarplotResult:
    """Fetch, transform and render a water-balance budget bar plot.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param period: ``(cutsdate, cutedate)`` as ``YYYY-MM-DD`` strings.
    :param frequency: Aggregation frequency code (``"Y"``, ``"M"``, ``"D"``).
    :param agg: Aggregation function (``"sum"``, ``"mean"``, ``"max"``, ``"min"``).
    :param pluriannual: Whether to compute pluriannual aggregation.
    :param output_dir: Directory in which both the PNG and the CSV are written.
    :param variables: Water-balance variables to include.
    :param frequency_label: Human label for the filename (e.g. ``"Annual"``);
        defaults to ``frequency`` if not provided.
    :param agg_label: Human label for the filename (e.g. ``"Sum"``);
        defaults to ``agg`` if not provided.
    :returns: Paths to the rendered PNG and the written CSV.
    """
    cutsdate, cutedate = period
    watbal_id = _resolve_compartment_id(twin, "WATBAL")
    syear = twin.metadata["start_year"]
    eyear = twin.metadata["end_year"]

    data_dict = {}
    for var in variables:
        fetch_response = twin.fetch(
            kind="simulation_matrix",
            id_compartment=watbal_id,
            outtype="MB",
            param=var,
            syear=syear,
            eyear=eyear,
            cutsdate=cutsdate,
            cutedate=cutedate,
            id_layer=0,
            target_unit="mm/j",
        )
        budget_response = twin.transform(
            kind="budget",
            data=fetch_response.data,
            id_compartment=watbal_id,
            param=var,
            agg_dimension=agg,
            frequency=frequency,
            sdate=syear,
            edate=eyear,
            cutsdate=cutsdate,
            cutedate=cutedate,
            pluriannual=pluriannual,
        )
        data_dict[var] = (
            budget_response.data,
            budget_response.date_labels,
            budget_response.param,
        )

    fz_label = frequency_label if frequency_label is not None else frequency
    ag_label = agg_label if agg_label is not None else agg
    output_basename = f"BUDGET_{cutsdate}{cutedate}{fz_label}_{ag_label}"
    csv_path = os.path.join(output_dir, output_basename + ".csv")
    all_vars = list(data_dict.keys())
    combined_data = np.column_stack([data_dict[var][0] for var in all_vars])
    np.savetxt(
        csv_path,
        combined_data,
        delimiter="\t",
        header="\t".join(all_vars),
        comments="",
        fmt="%.6f",
    )

    yaxis_unit = "mm" if agg == "sum" else "mm/day"
    render_result = twin.render(
        kind="budget_barplot",
        data=data_dict,
        plot_title=f"PERIOD : {cutsdate} - {cutedate}",
        output_folder=output_dir,
        output_name=output_basename,
        yaxis_unit=yaxis_unit,
    )
    png_path = render_result.artefacts[0]

    return BudgetBarplotResult(png_path=png_path, csv_path=csv_path)


def run_hydrological_regime(
    twin,
    compartment_name: str,
    outtype: str,
    param: str,
    var_label: str,
    units: str,
    savepath: str,
    interactive: bool = False,
    staticpng: bool = True,
    staticpdf: bool = True,
    period: Tuple[str, str] = ("", ""),
) -> HydrologicalRegimeResult:
    """Fetch, transform and render a hydrological regime plot.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param compartment_name: ``"HYD"`` for discharge, ``"AQ"`` for piezometric head.
    :param outtype: HT outtype code (``"Q"`` or ``"H"``).
    :param param: HT param code (``"discharge"`` or ``"piezhead"``).
    :param var_label: Display variable name (``"Discharge"`` or ``"Piezometric Head"``).
    :param units: Display units string used in the plots.
    :param savepath: Directory in which the static artefacts are written.
    :param interactive: Build the Plotly interactive figure too.
    :param staticpng: Write per-observation-point PNG files.
    :param staticpdf: Write a combined PDF.
    :param period: ``(cutsdate, cutedate)`` as ``YYYY-MM-DD`` strings, used in filenames.
    :returns: Paths to the PNGs and (optionally) the PDF that were written.
    """
    cutsdate, cutedate = period
    id_compartment = _resolve_compartment_id(twin, compartment_name)
    syear = twin.metadata["start_year"]
    eyear = twin.metadata["end_year"]

    fetch_response = twin.fetch(
        kind="simulation_matrix",
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        syear=syear,
        eyear=eyear,
        id_layer=0,
    )

    regime_response = twin.transform(
        kind="hydrological_regime",
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        data=fetch_response.data,
        dates=fetch_response.dates,
        sdate=syear,
        edate=eyear,
    )

    os.makedirs(savepath, exist_ok=True)

    years = f"{cutsdate}_{cutedate}"
    render_result = twin.render(
        kind="hydrological_regime",
        data=regime_response.data,
        obs_point_names=regime_response.obs_point_names,
        month_labels=regime_response.month_labels,
        var=var_label,
        units=units,
        savepath=savepath,
        interactive=interactive,
        staticpng=staticpng,
        staticpdf=staticpdf,
        years=years,
    )

    artefacts = list(render_result.artefacts)
    png_paths = [p for p in artefacts if p.lower().endswith(".png")]
    pdf_path = next((p for p in artefacts if p.lower().endswith(".pdf")), None)

    return HydrologicalRegimeResult(
        png_paths=png_paths,
        pdf_path=pdf_path,
        savepath=savepath,
    )


def run_spatial_map_watbal(
    twin,
    param: str,
    period: Tuple[str, str],
    frequency: str,
    agg,
    pluriannual: bool,
    id_layer: int,
    target_unit: str = "mm/j",
    layer_name_param: str = None,
    frequency_label: str = None,
    agg_label: str = None,
) -> SpatialMapWatbalResult:
    """Fetch a single-variable WATBAL spatial map.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param param: Water-balance variable (``"rain"``, ``"etr"``, ``"inf"``,
        ``"runoff"``, ``"effective_rainfall"``, ...).
    :param period: ``(cutsdate, cutedate)`` as ``YYYY-MM-DD`` strings; the years
        are used in the composed layer name.
    :param frequency: Aggregation frequency code (``"Y"``, ``"M"``, ``"D"``).
    :param agg: Aggregation function (``"sum"``, ``"mean"``, ``"max"``,
        ``"min"``) or a numeric quantile in ``]0, 1]``.
    :param pluriannual: Whether to compute pluriannual aggregation.
    :param id_layer: Integer index of the WATBAL resolution layer.
    :param target_unit: Unit string passed to the developer fetch; pass
        ``None`` to omit (matches ``effective_rainfall`` parity).
    :param layer_name_param: Override for the layer-name prefix; defaults to
        ``param``. Useful when the dialog displays ``"eff_rain"`` while the
        backend param is ``"effective_rainfall"``.
    :param frequency_label: Human label for the layer name (e.g. ``"Annual"``);
        defaults to ``frequency`` if not provided.
    :param agg_label: Human label for the layer name (e.g. ``"Sum"``); defaults
        to ``str(agg)`` if not provided.
    :returns: The GeoDataFrame plus the composed layer name.
    """
    cutsdate, cutedate = period
    watbal_id = _resolve_compartment_id(twin, "WATBAL")
    syear = twin.metadata["start_year"]
    eyear = twin.metadata["end_year"]

    fetch_kwargs = dict(
        kind="spatial_map",
        id_compartment=watbal_id,
        outtype="MB",
        param=param,
        syear=syear,
        eyear=eyear,
        cutsdate=cutsdate,
        cutedate=cutedate,
        id_layer=id_layer,
        agg=agg,
        frequency=frequency,
        pluriannual=pluriannual,
    )
    if target_unit is not None:
        fetch_kwargs["target_unit"] = target_unit

    response = twin.fetch(**fetch_kwargs)
    gdf = response.gdf

    name_prefix = layer_name_param if layer_name_param is not None else param
    fz_label = frequency_label if frequency_label is not None else frequency
    ag_label = agg_label if agg_label is not None else str(agg)
    wb_unit = "mm" if agg == "sum" else "mm/day"
    layer_name = (
        f"{name_prefix}_{cutsdate[:4]}{cutedate[:4]} {fz_label} {ag_label}[{wb_unit}]"
    )

    return SpatialMapWatbalResult(gdf=gdf, layer_name=layer_name)


def run_spatial_map_aq(
    twin,
    outtype: str,
    param: str,
    layer_id_offset: int,
    mode: dict,
    period: Tuple[str, str],
    frequency: str,
    agg,
    pluriannual: bool,
    save_directory: str = None,
    name_prefix: str = "",
    unit: str = "m",
    frequency_label: str = None,
    agg_label: str = None,
) -> SpatialMapAqResult:
    """Fetch an AQ spatial map (piezometric head, fluxes, recharge, overflow).

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param outtype: HT outtype code (``"H"`` for head, ``"MB"`` for fluxes).
    :param param: HT param code (``"piezhead"``, ``"flux_riv_to_aq"``, ...).
    :param layer_id_offset: Layer-id offset passed to the developer fetch
        (``1`` for piezometric head, ``0`` for fluxes).
    :param mode: Dict produced by the AQ resolution combobox, with keys
        ``kind`` (``"spatial_map"`` or ``"aquifer_outcropping_map"``),
        ``layer`` (resolution name or ``None``), and ``label`` (display name).
    :param period: ``(cutsdate, cutedate)`` as ``YYYY-MM-DD`` strings.
    :param frequency: Aggregation frequency code.
    :param agg: Aggregation function or numeric quantile.
    :param pluriannual: Whether to compute pluriannual aggregation.
    :param save_directory: Directory used when ``mode['kind']`` is
        ``"aquifer_outcropping_map"`` (the developer fetch caches an
        intermediate file there); ignored otherwise.
    :param name_prefix: Layer-name prefix (``"H"``, ``"RivTOAq"``,
        ``"RECHARGE"``, ``"OVERFLOW"``).
    :param unit: Display unit (``"m"``, ``"m³/s"``); cumulative aggregation on a
        rate strips the ``"/s"`` suffix.
    :param frequency_label: Human label for the layer name; defaults to
        ``frequency``.
    :param agg_label: Human label for the layer name; defaults to ``str(agg)``.
    :returns: The GeoDataFrame plus the composed layer name.
    """
    cutsdate, cutedate = period
    aq_id = _resolve_compartment_id(twin, "AQ")
    syear = twin.metadata["start_year"]
    eyear = twin.metadata["end_year"]

    fetch_kwargs = dict(
        kind=mode["kind"],
        id_compartment=aq_id,
        outtype=outtype,
        param=param,
        syear=syear,
        eyear=eyear,
        cutsdate=cutsdate,
        cutedate=cutedate,
        agg=agg,
        frequency=frequency,
        pluriannual=pluriannual,
        layer_id_offset=layer_id_offset,
    )
    if mode["kind"] == "spatial_map":
        fetch_kwargs["layer_names"] = [mode["layer"]]
    else:
        fetch_kwargs["save_directory"] = save_directory

    response = twin.fetch(**fetch_kwargs)
    gdf = response.gdf

    res_name = mode["label"]
    fz_label = frequency_label if frequency_label is not None else frequency
    ag_label = agg_label if agg_label is not None else str(agg)
    display_unit = unit.replace("/s", "") if agg == "sum" and "/s" in unit else unit
    layer_name = f"{name_prefix}_{res_name}_{fz_label}_{ag_label}_[{display_unit}]"

    return SpatialMapAqResult(gdf=gdf, layer_name=layer_name)


def _aggr_label(aggr) -> str:
    """Compose the filename label for an aggregator value.

    - ``None`` -> ``"DAILY"``  (used for Transient regime where no aggregator applies)
    - ``float`` quantile -> ``"Q<value>"``
    - ``str`` (``"mean"``, ``"min"``, ``"max"``, ``"sum"``) -> uppercase
    """
    if aggr is None:
        return "DAILY"
    if isinstance(aggr, float):
        return f"Q{aggr}"
    return str(aggr).upper()


def run_compare_sim_obs(
    twin,
    mode: str,
    compartment_name: str,
    outtype: str,
    param: str,
    ylabel: str,
    obs_unit: str,
    plot_period: Tuple[str, str],
    crit_period: Tuple[str, str],
    directory: str,
    id_layer: int = 0,
    aggr=None,
    regime: str = "Transient",
) -> CompareSimObsResult:
    """Render a sim-vs-obs comparison as PDF, interactive HTML, or CSV data.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param mode: ``"pdf"`` (static, multi-page PDF), ``"interactive"``
        (single HTML written via Plotly), or ``"csv"`` (a daily sim/obs
        :class:`pandas.DataFrame` returned on the result for the frontend to
        persist — the backend writes no file in this mode).
    :param compartment_name: ``"AQ"`` or ``"HYD"``.
    :param outtype: HT outtype code (``"H"`` or ``"Q"``).
    :param param: HT param code (``"piezhead"`` or ``"discharge"``).
    :param ylabel: Y-axis label shown on the plots.
    :param obs_unit: Display unit string for the observations.
    :param plot_period: ``(plotstart, plotend)`` as ``YYYY-MM-DD`` strings.
    :param crit_period: ``(critstart, critend)`` as ``YYYY-MM-DD`` strings.
    :param directory: Output directory (artefacts are written here).
    :param id_layer: Layer index for the developer fetch.
    :param aggr: Aggregator (``None``, a numeric quantile, or
        ``"mean"``/``"min"``/``"max"``).
    :param regime: ``"Steady"`` or ``"Transient"``; affects the interactive
        output filename.
    :returns: Paths to the artefacts produced.
    """
    if mode not in ("pdf", "interactive", "csv"):
        raise ValueError(
            f"mode must be 'pdf', 'interactive' or 'csv', got {mode!r}"
        )

    id_compartment = _resolve_compartment_id(twin, compartment_name)
    syear = twin.metadata["start_year"]
    eyear = twin.metadata["end_year"]
    plotstart, plotend = plot_period
    critstart, critend = crit_period
    aggr_label = _aggr_label(aggr)
    name_file = f"SIM_OBS_{compartment_name}_{aggr_label}"

    if mode == "pdf":
        render_result = twin.render(
            kind="sim_obs_pdf",
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            simsdate=syear,
            simedate=eyear,
            plotstartdate=plotstart,
            plotenddate=plotend,
            id_layer=id_layer,
            directory=directory,
            name_file=name_file,
            ylabel=ylabel,
            obs_unit=obs_unit,
            crit_start=critstart,
            crit_end=critend,
            aggr=aggr,
        )
        artefacts = list(render_result.artefacts)
        pdf_path = next((p for p in artefacts if p.lower().endswith(".pdf")), None)
        return CompareSimObsResult(
            mode="pdf",
            pdf_path=pdf_path,
            output_directory=directory,
        )

    if regime == "Steady":
        out_file_path = os.path.join(directory, f"{name_file}_steady.html")
    else:
        out_file_path = os.path.join(
            directory, f"{name_file}_{critstart}_{critend}.html"
        )

    if mode == "interactive":
        render_result = twin.render(
        kind="sim_obs_interactive",
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        simsdate=syear,
        simedate=eyear,
        plotstart=plotstart,
        plotend=plotend,
        obs_unit=obs_unit,
        ylabel=ylabel,
        df_other_variable=None,
        other_variable_config=None,
        out_file_path=out_file_path,
        crit_start=critstart,
        crit_end=critend,
        aggr=aggr,
    )
        artefacts = list(render_result.artefacts)
        html_path = next((p for p in artefacts if p.lower().endswith(".html")), out_file_path)
        return CompareSimObsResult(
            mode="interactive",
            html_path=html_path,
            output_directory=directory,
        )
    
    if mode == "csv":
        # CSV is built the server-ready way: reuse the sim_obs_bundle fetch
        # (no new render branch, no backend file write), assemble a daily
        # table as data, and let the frontend persist it. No criteria needed.
        bundle_response = twin.fetch(
            kind="sim_obs_bundle",
            id_compartment=id_compartment,
            outtype=outtype,
            param=param,
            syear=syear,
            eyear=eyear,
            plotstart=plotstart,
            plotend=plotend,
            id_layer=id_layer,
            agg=aggr,
            compute_criteria=False,
            obs_unit=obs_unit,
        )
        df = assemble_daily_sim_obs_table(bundle_response)
        return CompareSimObsResult(
            mode="csv",
            csv_data=df,
            output_directory=directory,
        )




DEFAULT_CRITERIA_METRICS = (
    "n_obs", "avg_obs", "avg_sim", "sum_ratio", "std_obs", "std_sim", "std_ratio",
)


def _write_criteria_text_file(path: str, metrics: Sequence[str], rows: Sequence[Tuple[str, str, dict]]) -> None:
    """Write the per-point criteria text file (header + one row per point).

    :param path: Output path.
    :param metrics: Ordered metric keys, used both for header columns and row order.
    :param rows: Iterable of ``(name, point_id, criteria_dict)`` tuples.
    """
    name_w = max(8, max((len(r[0]) for r in rows), default=0) + 2)
    code_w = max(8, max((len(str(r[1])) for r in rows), default=0) + 2)
    col_w  = max(12, max(len(m) for m in metrics) + 2)

    with open(path, "w") as f:
        f.write("NAME".ljust(name_w) + "CODE".ljust(code_w))
        f.write("".join(m.rjust(col_w) for m in metrics) + "\n")
        for name, point_id, crits in rows:
            f.write(str(name).ljust(name_w) + str(point_id).ljust(code_w))
            f.write("".join(f"{crits[k]:>{col_w}.4g}" for k in metrics) + "\n")



def _write_aq_global_and_by_layer(
    path: str,
    global_metrics: dict,
    by_layer: dict,
) -> None:
    """Write the AQ-specific globals + by-layer criteria text file."""
    with open(path, "w") as f:
        f.write("__________________ GLOBALS STATISTICALS CRITERIA __________________\n")
        for crit_name, crit_value in global_metrics.items():
            f.write(f"\t{crit_name} : {crit_value}\n")
        f.write("\n\n\n__________________ STATISTICALS CRITERIA BY AQ LAYERS ________________\n")
        for id_layer in sorted(set(by_layer.keys())):
            layer_crits = by_layer[id_layer]
            f.write("- - - - - - - - - - - - - - - - - - -\n")
            f.write(f"\t\t ID LAYER : {id_layer}\n")
            f.write("- - - - - - - - - - - - - - - - - - -\n")
            for crit_name, crit_value in layer_crits.items():
                f.write(f"\t{crit_name} : {crit_value}\n")


def run_statistical_criteria(
    twin,
    compartment_name: str,
    outtype: str,
    param: str,
    period: Tuple[str, str],
    output_dir: str,
    metrics: Sequence[str] = None,
    id_layer: int = 0,
    aggr=None,
    obs_unit: str = None,
) -> StatisticalCriteriaResult:
    """Compute statistical criteria at observation points and persist them.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param compartment_name: ``"AQ"`` or ``"HYD"``.
    :param outtype: HT outtype code (``"H"`` or ``"Q"``).
    :param param: HT param code (``"piezhead"`` or ``"discharge"``).
    :param period: ``(crit_start, crit_end)`` as ``YYYY-MM-DD`` strings; the
        same period is used for the plot range and the criteria range.
    :param output_dir: Directory in which the criteria text files are
        written.
    :param metrics: User-selected metrics (e.g. ``"kge"``, ``"nash"``,
        ``"rmse"``, ``"pbias"``, ``"avg_ratio"``). The default block
        (``n_obs``, ``avg_obs``, ...) is always appended.
    :param id_layer: Layer index for the developer fetch.
    :param aggr: Aggregator for Steady regime (``None`` in Transient).
    :param obs_unit: Observation unit, used by the developer fetch to convert
        units when the dialog requested ``l/s``.
    :returns: Per-point criteria, the ordered metric list, and the paths of
        the text artefacts.
    """
    id_compartment = _resolve_compartment_id(twin, compartment_name)
    obs_info = twin.get_observation_info(id_compartment)
    if obs_info is None:
        raise ValueError(
            f"Compartment {compartment_name!r} has no observation points; "
            f"cannot compute statistical criteria."
        )

    user_metrics = list(metrics) if metrics else []
    listed_crits = user_metrics + [m for m in DEFAULT_CRITERIA_METRICS if m not in user_metrics]

    crit_start, crit_end = period
    syear = twin.metadata["start_year"]
    eyear = twin.metadata["end_year"]

    bundle_response = twin.fetch(
        kind="sim_obs_bundle",
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        syear=syear,
        eyear=eyear,
        plotstart=crit_start,
        plotend=crit_end,
        id_layer=id_layer,
        agg=aggr,
        compute_criteria=True,
        criteria_metrics=listed_crits,
        crit_start=crit_start,
        crit_end=crit_end,
        obs_unit=obs_unit,
    )

    criteria_response = twin.transform(
        kind="criteria",
        bundle=bundle_response,
        metrics=listed_crits,
    )

    points = []
    rows = []
    for i, _ in enumerate(criteria_response.per_point):
        crits = criteria_response.per_point[i]["criteria"]
        pt_name = obs_info.point_names[i]
        pt_id = obs_info.point_ids[i]
        pt_layer = obs_info.layer_ids[i]
        pt_geom = obs_info.geometries[i]
        points.append(
            CriteriaPointResult(
                name=pt_name,
                point_id=pt_id,
                layer_id=pt_layer,
                geometry=pt_geom,
                criteria=dict(crits),
            )
        )
        rows.append((pt_name, pt_id, crits))

    os.makedirs(output_dir, exist_ok=True)
    txt_path = os.path.join(
        output_dir, f"CRIT_STAT_{param}_{crit_start}{crit_end}.txt"
    )
    _write_criteria_text_file(txt_path, listed_crits, rows)

    aq_layer_txt_path = None
    if compartment_name == "AQ":
        aq_layer_txt_path = os.path.join(
            output_dir,
            f"CRIT_STAT_BY_LAYER_AQ_{crit_start}{crit_end}.txt",
        )
        _write_aq_global_and_by_layer(
            aq_layer_txt_path,
            dict(criteria_response.global_metrics),
            {k: dict(v) for k, v in criteria_response.by_layer.items()},
        )

    return StatisticalCriteriaResult(
        points=points,
        metrics=listed_crits,
        compartment_name=compartment_name,
        period=(crit_start, crit_end),
        txt_path=txt_path,
        aq_layer_txt_path=aq_layer_txt_path,
    )


def _mesh_gdf_for(twin, id_compartment: int, id_layer: int = 0):
    """Return the mesh GeoDataFrame for ``(compartment, layer)`` on a raw twin."""
    compartment = twin.compartments[id_compartment]
    layer_name = compartment.mesh.layers_gis_name[id_layer]
    return compartment.mesh.layer_gdfs[layer_name]


def _cell_id_col_name(twin, id_compartment: int, gdf) -> str:
    """Resolve the cell-id column name (translate integer position to a name)."""
    id_col = twin.config_geom.idColCells[id_compartment]
    if isinstance(id_col, int):
        return gdf.columns[id_col]
    return id_col


def _artefact_basename(compartment: str, param: str, outtype: str, syear, eyear) -> str:
    """Filename root; the parent folder name already carries the area."""
    years = f"{syear}-{eyear}"
    if outtype:
        return f"{compartment}_{param}_{outtype}_{years}"
    return f"{compartment}_{param}_{years}"


def _unit_token(unit: str) -> str:
    """Filesystem-safe token for a unit string (``"m3/s"`` -> ``"m3s"``).

    Used to make Internal Values CSV filenames unit-distinct so an ``m3/s`` run
    and an ``m3/j`` run of the same spec do not overwrite each other.
    """
    return unit.replace("/", "")


def run_mask_internal_values(
    twin,
    polygon,
    polygon_crs,
    specs: Sequence[Tuple[str, str, str, str]],  # (compartment, outtype, param, unit)
    syear,
    eyear,
    output_dir: str,
    temp_dir: str,
    area_name: str,
    write_geopackage: bool = False,
    weighted: bool = True,
) -> MaskInternalValuesResult:
    """Mask compartment cells inside a polygon and persist per-spec time series.

    Generalises the former WATBAL-only ``run_mask_watbal``: instead of a flat
    WATBAL ``params`` list it takes a sequence of ``(compartment, outtype,
    param)`` triples (``specs``). The same masked polygon selects a *different*
    cell set from each compartment's mesh, so the mesh GDF + cell-id column are
    resolved **once per distinct compartment** and the result carries one cells
    GeoDataFrame per compartment (``MaskInternalValuesResult.entries``).

    **Unit (per spec)**: each spec carries its **own** output unit as the
    4th tuple element, so one call may emit different units for different
    params (e.g. HYD Flow in ``"m3/s"`` and HYD Water Height in ``"m"``).
    That per-spec unit is the single source of truth for that spec: it feeds
    the conversion (``target_unit`` through ``twin.mask(kind="area_values",
    ...)``), the CSV / polygon-total filename token, and the stamped
    GeoPackage label (the per-param ``daily_values_unit_override`` mapping),
    so a spec's numbers and its unit label cannot drift apart.

    Two unit **families** are supported (selected by the backend from the
    unit token): *volumetric* — ``"m3/s"`` (CaWaQS-native; 86400 conversion
    short-circuited) and ``"m3/j"`` (``m³/day``; raw ×86400), valid for
    WATBAL water-balance terms, AQ recharge and HYD Flow; and *length* —
    ``"m"`` (raw pass-through) and ``"cm"`` (×100), for HYD Water Height.
    Pairing a param with a unit from the wrong family raises a typed error.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param polygon: Shapely polygon (or MultiPolygon) defining the area.
    :param polygon_crs: CRS string for ``polygon`` (e.g. ``"EPSG:2154"``).
    :param specs: Sequence of ``(compartment, outtype, param, unit)`` tuples,
        e.g. ``("WATBAL", "MB", "rain", "m3/j")``,
        ``("AQ", "MB", "recharge", "m3/j")``,
        ``("HYD", "Q", "discharge", "m3/s")`` or
        ``("HYD", "H", "water_height", "m")``. The compartment MAY be
        ``WATBAL``, ``AQ`` or ``HYD``; the 4th element is that spec's output
        unit (see **Unit (per spec)** above).
    :param syear: Simulation start year.
    :param eyear: Simulation end year.
    :param output_dir: Directory for CSV artefacts.
    :param temp_dir: Directory for numpy binary artefacts.
    :param area_name: Display / filename token for the masked area.
    :param write_geopackage: Selects an exclusive output **mode**:

        * ``True`` (GeoPackage mode): every spec is still fetched (the
          GeoPackage needs the data), but the per-spec CSV, ``.npy`` and
          per-spec ``polygon_total`` CSV are NOT written. A single
          ``<output_dir>/<area>_InternalValues_<syear>_<eyear>.gpkg`` —
          one transportable Internal Values bundle spanning every requested
          compartment: a ``cells_<compartment>`` vector layer per mesh, a
          long-form ``daily_values`` table carrying a ``compartment``
          discriminator (joined to its mesh on ``(compartment, cell_id)``),
          one ``provenance`` row per compartment, and
          ``polygon_total_<compartment>_<param>`` tables when
          ``weighted=True`` — is the sole artefact and the only path in
          ``MaskInternalValuesResult.artefacts``. Silent overwrite.
        * ``False`` (default mode): the per-spec CSV + ``.npy`` (+
          ``polygon_total`` CSVs when ``weighted=True``) are written for every
          compartment in ``specs``, and no GeoPackage is produced.
    :param weighted: When true, opt into area-fraction weighting (uniform
        across every spec in the call):

        * Cells are selected by per-cell intersection area (not by
          centroid containment), via :func:`cells_in_polygon_weighted`.
        * Per-cell time-series are multiplied by their area-fraction
          weight (``polygon.intersection(cell).area / cell.area``).
        * The per-spec CSV carries the weighted contributions (in ``unit``).
        * One extra polygon-total CSV per spec is written:
          ``<output_dir>/<area_name>_<compartment>_<param>_polygon_total_<years>_<unit_token>.csv``
          (two columns: ``date, polygon_total`` in ``unit``).
        * Each per-compartment ``gdf`` carries clipped intersection
          geometries plus a ``weight`` column instead of full cell footprints.

        Default ``False`` preserves today's binary behaviour.
    :returns: A :class:`MaskInternalValuesResult` with one
        :class:`CompartmentCellsEntry` per distinct compartment, the flat
        ``artefacts`` list, and (when ``weighted=True``) the per-spec
        ``polygon_total_paths`` mapping keyed by ``(compartment, param)``.
    """
    import pandas as pd  # noqa: PLC0415 — local import keeps top-of-module light

    specs = [tuple(s) for s in specs]

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    artefacts: list = []
    polygon_total_paths: dict = {}
    years_token = f"{syear}-{eyear}"
    # Distinct compartments in first-seen order; resolve each mesh once.
    compartments = list(dict.fromkeys(comp for comp, *_ in specs))
    comp_resolved = {}
    for comp in compartments:
        comp_id = _resolve_compartment_id(twin, comp)
        mesh_gdf = _mesh_gdf_for(twin, comp_id)
        id_col = _cell_id_col_name(twin, comp_id, mesh_gdf)
        comp_resolved[comp] = {
            "id": comp_id,
            "mesh_gdf": mesh_gdf,
            "id_col": id_col,
            "cells_gdf": None,
            "retained_responses": {},   # param -> response (GeoPackage only)
            "polygon_total_dfs": {},     # param -> df  (GeoPackage only)
        }

    for comp, outtype, param, unit in specs:
        ctx = comp_resolved[comp]
        comp_id = ctx["id"]
        # AQ recharge enters at the cross-layer outcropping free surface, so AQ
        # specs resolve cells against the outcropping mesh (global ``id_abs``);
        # WATBAL keeps the single-layer path → byte-identical (design D2).
        resolution = "outcropping" if comp == "AQ" else "reaches" if comp == "HYD" else "single_layer"
        # Area-fraction weighting only has a physical meaning on volumetric
        # data; a length unit (Water Height in m/cm) can never be weighted.
        # Force the per-spec weighting off for length units so a single
        # dialog-wide "weighted" tick does not push m/cm into the volumetric
        # guard in dispatch. HYD reaches are UNWEIGHTED by design (each reach
        # contributes its raw value, no length-fraction scaling), so force it
        # off there too — this keeps _build_cells_gdf on the unweighted reaches
        # branch (no weight column) and matches dispatch, which also drops the
        # weights for reaches.
        spec_weighted = (
            weighted
            and unit not in _LENGTH_UNITS
            and resolution != "reaches"
        )
        response = twin.mask(
            kind="area_values",
            id_compartment=comp_id,
            outtype=outtype,
            param=param,
            syear=syear,
            eyear=eyear,
            polygon=polygon,
            polygon_crs=polygon_crs,
            target_unit=unit,
            weighted=spec_weighted,
            resolution=resolution,
        )

        if ctx["cells_gdf"] is None:
            ctx["cells_gdf"] = _build_cells_gdf(
                mesh_gdf=ctx["mesh_gdf"],
                id_col=ctx["id_col"],
                response=response,
                polygon=polygon,
                polygon_crs=polygon_crs,
                weighted=spec_weighted,
                twin=twin,
                id_compartment=comp_id,
                resolution=resolution,
            )

        # Exclusive-mode gate (design.md D10): in GeoPackage mode the per-spec
        # CSV / .npy / polygon_total CSV are NOT written — the .gpkg is the sole
        # artefact. The fetch above still ran because the GeoPackage needs the
        # data; only the disk writes below are suppressed.
        if not write_geopackage:
            # The unit token keeps unit-distinct runs of the same spec from
            # overwriting each other; CSV and .npy share the basename so the
            # pair stays matched.
            base = f"{_artefact_basename(comp, param, outtype, syear, eyear)}_{_unit_token(unit)}"
            csv_path = os.path.join(output_dir, f"{base}.csv")
            npy_path = os.path.join(temp_dir, f"{base}.npy")
            df = pd.DataFrame(
                response.data.T,
                index=pd.Index(response.dates, name="date"),
                columns=[f"cell_{i}" for i in range(response.data.shape[0])],
            )
            df.to_csv(csv_path)
            # Privileged .npy write routed through the L2 export gate.
            twin.export(kind="npy", path=npy_path, data=response.data)
            artefacts.append(csv_path)
            artefacts.append(npy_path)
        ctx["retained_responses"][param] = response

        if weighted:
            polygon_total = response.data.sum(axis=0)
            total_df = pd.DataFrame(
                {"polygon_total": polygon_total},
                index=pd.Index(response.dates, name="date"),
            )
            # The polygon totals always feed the GeoPackage writer (as
            # polygon_total_<param> tables); the standalone CSV is written only
            # in default mode.
            ctx["polygon_total_dfs"][param] = total_df.reset_index()
            if not write_geopackage:
                total_path = os.path.join(
                    output_dir,
                    f"{area_name}_{comp}_{param}_polygon_total_{years_token}_{_unit_token(unit)}.csv",
                )
                total_df.to_csv(total_path)
                artefacts.append(total_path)
                polygon_total_paths[(comp, param)] = total_path

    for comp in compartments:
        ctx = comp_resolved[comp]
        if ctx["cells_gdf"] is None:
            # No specs requested for this compartment (only possible when
            # specs is empty): build a footprint-only cells GDF via the
            # centroid-in selection so the dialog can still render it.
            cells_response = twin.mask(
                kind="polygon_cells",
                id_compartment=ctx["id"],
                polygon=polygon,
                polygon_crs=polygon_crs,
            )
            ctx["cells_gdf"] = (
                ctx["mesh_gdf"].set_index(ctx["id_col"])
                .loc[list(cells_response.cell_ids)]
                .reset_index()
                .rename(columns={ctx["id_col"]: "cell_id"})
            )

    if write_geopackage:
        # One multi-layer Internal Values bundle spanning every requested
        # compartment: a cells_<compartment> layer per mesh, a
        # compartment-keyed daily_values table, and one provenance row per
        # compartment. The per-compartment data is already assembled in
        # comp_resolved; the path/provenance/unit shaping now lives in the L3
        # ``build_compartment_bundle`` reached via the ``assemble`` verb, and the
        # disk write stays behind the ``export`` gate. assemble() is shape-only —
        # nothing is written until export() runs.
        compartment_blocks = {
            comp: (
                comp_resolved[comp]["cells_gdf"],
                comp_resolved[comp]["retained_responses"],
                comp_resolved[comp]["polygon_total_dfs"] if weighted else None,
            )
            for comp in compartments
        }
        bundle = twin.assemble(
            kind="compartment_bundle",
            label="InternalValues",
            compartment_blocks=compartment_blocks,
            output_dir=output_dir,
            area_name=area_name,
            syear=syear,
            eyear=eyear,
            polygon=polygon,
            polygon_crs=polygon_crs,
            weighted=weighted,
            source_run=getattr(twin, "out_caw_directory", "") or "",
        )
        # Privileged GeoPackage write routed through the L2 export gate.
        twin.export(
            kind="geopackage",
            path=bundle.gpkg_path,
            data=bundle.compartment_blocks,
            options={
                "provenance_rows": bundle.provenance_rows,
                "unit_override": bundle.unit_override,
            },
        )
        artefacts.append(bundle.gpkg_path)

    entries = [
        CompartmentCellsEntry(
            compartment=comp,
            gdf=comp_resolved[comp]["cells_gdf"],
            layer_name=f"{area_name}_{comp}_cells",
        )
        for comp in compartments
    ]

    return MaskInternalValuesResult(
        entries=entries,
        artefacts=artefacts,
        polygon_total_paths=polygon_total_paths if weighted else None,
    )

def _build_cells_gdf(
    mesh_gdf,
    id_col,
    response,
    polygon,
    polygon_crs,
    weighted: bool,
    twin,
    id_compartment,
    resolution: str = "single_layer",
):
    # FIXME (misplaced): this mixes selection (twin.mask /
    # _build_outcropping_mesh_gdf — orchestration, stays here) with pure
    # GeoDataFrame assembly (gpd join + weight col — a services-layer op).
    # TODO: split — keep the twin.* selection inline in run_mask_internal_values
    # and extract the pure geopandas assembly into services/ (no twin, no dispatch).
    """Assemble the cells GeoDataFrame for one compartment in
    ``run_mask_internal_values``.

    - ``weighted=False`` → full cell footprints joined on the per-param
      response's cell_ids; no ``weight`` column.
    - ``weighted=True`` → clipped intersection geometries pulled directly
      from ``response.clipped_geometries``, with a per-row ``weight``
      column. Row order matches the per-cell response data — the dialog
      can join cells_gdf to response.data by row position.

    ``resolution="outcropping"`` (AQ recharge) builds the unweighted gdf from
    the cross-layer outcropping mesh keyed on the global ``id_abs`` carried in
    ``response.meta["cell_ids"]``, so the cells gdf reflects the same
    cross-layer selection (and global ids) as the area-values data. The
    weighted path is resolution-agnostic — its geometries and ids already come
    straight from the (outcropping-resolved) response.
    """
    import geopandas as gpd  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    if weighted:
        # Dispatcher meta carries 'cell_ids' on the target_unit path; weights
        # and clipped_geometries are populated by the weighted branch.
        meta_cell_ids = list((response.meta or {}).get("cell_ids", []))
        weights = response.weights if response.weights is not None else []
        clipped = (
            response.clipped_geometries
            if response.clipped_geometries is not None
            else []
        )
        df = pd.DataFrame(
            {
                "cell_id": meta_cell_ids,
                "weight": list(weights),
            }
        )
        return gpd.GeoDataFrame(df, geometry=list(clipped), crs=mesh_gdf.crs)

    if resolution == "reaches":
        # HYD reaches (unweighted by design): the dispatcher already selected the
        # internal + boundary reaches and produced row-aligned boundary-clipped
        # geometries. Reuse them directly so the cells gdf matches the area-values
        # rows (the centroid ``polygon_cells`` fallback below would re-select a
        # different set and break alignment). Reaches carry NO length-fraction
        # weight, so ``response.weights`` is None here and no ``weight`` column is
        # emitted — each reach contributes its raw value.
        #
        # cell_id is emitted as the user-facing GIS id (design D4 Option A): the
        # dispatcher put a row-aligned ``cell_gis_ids`` in meta beside ``cell_ids``
        # (ABS). This is a value substitution, not a lookup — no DataFrame logic in
        # L1 (golden rule). When the corresp file is missing id_gis == id_abs, so
        # the fallback to cell_ids below is a no-op.
        meta = response.meta or {}
        meta_cell_gis_ids = meta.get("cell_gis_ids")
        if meta_cell_gis_ids is None:
            meta_cell_gis_ids = meta.get("cell_ids", [])
        clipped = (
            response.clipped_geometries
            if response.clipped_geometries is not None
            else []
        )
        df = pd.DataFrame({"cell_id": list(meta_cell_gis_ids)})
        return gpd.GeoDataFrame(df, geometry=list(clipped), crs=mesh_gdf.crs)

    if resolution == "outcropping":
        # Selection already happened against the outcropping mesh (global
        # id_abs in response.meta["cell_ids"]); join footprints from that same
        # outcropping gdf so the cells gdf matches the cross-layer data.
        outcropping_gdf = twin._build_outcropping_mesh_gdf(id_compartment)
        meta_cell_ids = list((response.meta or {}).get("cell_ids", []))
        return (
            outcropping_gdf.set_index("id_abs")
            .loc[meta_cell_ids]
            .reset_index()
            .rename(columns={"id_abs": "cell_id"})
        )

    cells_response = twin.mask(
        kind="polygon_cells",
        id_compartment=id_compartment,
        polygon=polygon,
        polygon_crs=polygon_crs,
    )
    return (
        mesh_gdf.set_index(id_col)
        .loc[list(cells_response.cell_ids)]
        .reset_index()
        .rename(columns={id_col: "cell_id"})
    )


def run_mask_hyd_boundary(
    twin,
    polygon,
    polygon_crs,
    syear,
    eyear,
    output_dir: str,
    area_name: str,
) -> MaskHydBoundaryResult:
    """Mask HYD reaches on the polygon boundary + inside, and persist boundary fluxes.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param polygon: Shapely polygon (or MultiPolygon).
    :param polygon_crs: CRS string for ``polygon``.
    :param syear: Simulation start year.
    :param eyear: Simulation end year.
    :param output_dir: Directory for the per-reach signed-Q CSV.
    :param area_name: Display / filename token for the masked area.
    :returns: Boundary reaches gdf, inside reaches gdf, boundary-crossing
        points gdf, plus the CSV artefact path (when fluxes are non-empty).
    """
    import geopandas as gpd  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    from shapely.geometry import MultiPolygon  # noqa: PLC0415

    hyd_id = _resolve_compartment_id(twin, "HYD")

    boundary_resp = twin.mask(
        kind="boundary_hyd",
        id_compartment=hyd_id,
        polygon=polygon,
        polygon_crs=polygon_crs,
    )
    inside_resp = twin.mask(
        kind="polygon_cells",
        id_compartment=hyd_id,
        polygon=polygon,
        polygon_crs=polygon_crs,
    )
    q_response = twin.fetch(
        kind="simulation_matrix",
        id_compartment=hyd_id,
        outtype="Q",
        param="discharge",
        syear=syear,
        eyear=eyear,
        id_layer=0,
    )
    flux_resp = twin.mask(
        kind="boundary_hyd_flux",
        id_compartment=hyd_id,
        polygon=polygon,
        polygon_crs=polygon_crs,
        syear=syear,
        eyear=eyear,
        q_response=q_response,
    )

    network_gdf = _mesh_gdf_for(twin, hyd_id)
    id_col = _cell_id_col_name(twin, hyd_id, network_gdf)
    all_reach_ids = sorted(set(boundary_resp.reach_ids) | set(inside_resp.cell_ids))
    boundary_set = set(boundary_resp.reach_ids)
    inside_gdf = network_gdf[network_gdf[id_col].isin(all_reach_ids)].copy()
    if not inside_gdf.empty:
        inside_gdf["is_boundary"] = inside_gdf[id_col].isin(boundary_set)
    inside_layer_name = f"{area_name}_HYD_reaches"

    boundary_gdf = network_gdf[network_gdf[id_col].isin(boundary_resp.reach_ids)].copy()

    components = (
        list(polygon.geoms) if isinstance(polygon, MultiPolygon) else [polygon]
    )
    crossing_reach_ids = []
    crossing_points = []
    for reach_id, reach_geom in zip(boundary_resp.reach_ids, boundary_resp.geometries):
        for component in components:
            intersection = reach_geom.intersection(component.exterior)
            if intersection.is_empty:
                continue
            if intersection.geom_type == "Point":
                crossing_reach_ids.append(reach_id)
                crossing_points.append(intersection)
            elif intersection.geom_type == "MultiPoint":
                for pt in intersection.geoms:
                    crossing_reach_ids.append(reach_id)
                    crossing_points.append(pt)

    if crossing_points:
        flux_gdf = gpd.GeoDataFrame(
            {"reach_id": crossing_reach_ids},
            geometry=crossing_points,
            crs=polygon_crs,
        )
        flux_layer_name = f"{area_name}_HYD_boundary_points"
    else:
        flux_gdf = None
        flux_layer_name = None

    artefacts = []
    if flux_resp.reach_ids:
        os.makedirs(output_dir, exist_ok=True)
        cols = {
            f"reach_{rid}_Q_m3s": flux_resp.Q[i, :]
            for i, rid in enumerate(flux_resp.reach_ids)
        }
        csv_df = pd.DataFrame(cols, index=pd.Index(flux_resp.dates, name="date"))
        base = _artefact_basename("HYD", "boundary", "Q", syear, eyear)
        csv_path = os.path.join(output_dir, f"{base}.csv")
        csv_df.to_csv(csv_path)
        artefacts.append(csv_path)

    return MaskHydBoundaryResult(
        boundary_gdf=boundary_gdf,
        inside_gdf=inside_gdf,
        flux_gdf=flux_gdf,
        layer_names=(inside_layer_name, flux_layer_name, None),
        artefacts=artefacts,
    )


def run_mask_aq_boundary(
    twin,
    polygon,
    polygon_crs,
    syear,
    eyear,
    output_dir: str,
    area_name: str,
    write_geopackage: bool = False,
    temp_dir: str = None,
    unit: str = "m3/j",
) -> MaskAqBoundaryResult:
    """Mask AQ cells touching the polygon boundary and persist face-flux time series.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param polygon: Shapely polygon (or MultiPolygon).
    :param polygon_crs: CRS string for ``polygon``.
    :param syear: Simulation start year.
    :param eyear: Simulation end year.
    :param output_dir: Directory for the mode-dependent artefact (the per-(cell,
        dir) flux CSV in default mode, or the ``.gpkg`` in GeoPackage mode).
    :param area_name: Display / filename token for the masked area.
    :param write_geopackage: Selects one of two mutually **exclusive** output
        modes (matching ``run_mask_internal_values`` — the ``.gpkg`` is written
        *instead of* the loose CSV, never alongside it):

        * ``False`` (default mode): when fluxes are non-empty a single loose
          per-(cell, direction) face-flux CSV is written (values in the chosen
          ``unit``) and **no** GeoPackage is produced. This is the only mode that
          preserves the per-face **gross** detail (each face's own series).
        * ``True`` (GeoPackage mode): the single transportable bundle is written at
          ``<output_dir>/<area_name>_AqBoundary_<syear>_<eyear>.gpkg`` as the
          **sole** artefact — the loose face-flux CSV is **not** written. The
          bundle holds one ``cells_AQ_layer<id>`` vector layer **per aquifer layer
          the polygon reached** (one feature per boundary cell of that layer,
          carrying its merged boundary-edge geometry, a ``cell_id`` column, and a
          ``faces`` column of comma-separated cardinal directions — e.g.
          ``"north,west"`` — geometrically identical to the matching registered
          QGIS borders layer), a long-form values table (``daily_values`` for the
          rate tokens, ``monthly_values`` for the ``m3`` monthly-total mode; one
          row block per layer, ``compartment="AQ_layer<id>"``, ``param="boundary_flux"``)
          holding **one net daily-flux series per boundary cell** (the
          per-direction face series summed into a single net series, in the chosen
          ``unit``, row-aligned to its ``cells_AQ_layer<id>`` layer by ``cell_id``)
          with a matching ``faces`` column annotating which directions contributed,
          and a ``provenance`` table (one row per layer block, carrying the sign
          convention). The ``.gpkg`` path is appended to
          ``MaskAqBoundaryResult.artefacts``.

        The GeoPackage carries the per-cell **net** exchange (a corner cell's
        faces may have opposite signs, so the row is a net, not a gross) plus the
        ``faces`` annotation saying which directions contributed; the per-face
        gross detail is intentionally not preserved in GeoPackage mode and is
        available only in default (CSV) mode.
    :param temp_dir: Accepted for signature parity with the other mask
        operations; the GeoPackage path uses ``output_dir`` only, so this is
        currently unused here.
    :param unit: Output unit token for the boundary face fluxes (default
        ``"m3/j"``, preserving the prior ``m³/day`` behaviour). Accepted tokens:

        * ``"m3/j"`` (``m³/day``; a flow **rate** = raw CaWaQS ``m³/s`` × 86400);
        * ``"m3/mois"`` (``m³/month``, an *average-month* flow **rate** = raw ×
          2_629_800) — both rate tokens are pure magnitude rescales that keep the
          time axis at one row per simulated day (**not** a calendar re-aggregation);
        * ``"m3"`` (``m³``, a calendar-month total **VOLUME**) — this token
          re-bins the time axis daily→monthly and emits one row per ``(year,
          month)`` holding the total volume that crossed during that month (Σ over
          the month's simulated days of ``daily_m³/s × 86400``). The daily→monthly
          sum is done by the L2 ``temporal_aggregate`` verb this function calls
          (never inline here — CLAUDE.md "L1 only orchestrates"); a partial first
          or last month totals only its simulated days.

        The token is the single source of truth for the numeric conversion/
        aggregation, the loose-CSV column suffix (``_m3d`` / ``_m3mois`` /
        ``_m3month``), the GeoPackage values-table name (``daily_values`` /
        ``monthly_values``) and its ``unit`` label, **and** the
        time-axis grid (daily for rate tokens, monthly ``YYYY-MM`` for ``m3``), so
        the per-cell values, their declared unit and their date index can never
        diverge. The conversion/aggregation is applied identically to the loose
        CSV per-direction series and the GeoPackage per-cell net (both go through
        the same ``_flux_series`` helper), so the two surfaces can never disagree.
    :returns: A :class:`MaskAqBoundaryResult` whose ``entries`` carry one
        per-aquifer-layer borders gdf (each with ``cell_id``, ``faces`` and
        geometry — produced identically in both modes, so the registered QGIS
        layers show the cardinal faces regardless of ``write_geopackage``) + layer
        name, plus the single mode-dependent artefact path: the loose CSV in
        default mode, or the ``.gpkg`` in GeoPackage mode (never both). The fluxes
        are written in the chosen ``unit`` and both output surfaces ship the sign
        convention (positive = flux into the cell): the loose CSV as a commented
        header line, the GeoPackage in its ``provenance`` table.
    """
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415

    aq_id = _resolve_compartment_id(twin, "AQ")

    from HydrologicalTwinAlphaSeries.config.constants import (  # noqa: PLC0415
        AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE,
        AQ_BOUNDARY_FLUX_MONTHLY_VOLUME_SEMANTICS,
        AQ_BOUNDARY_FLUX_SIGN_CONVENTION,
        AQ_FACE_DIRECTIONS,
        _VOLUMETRIC_UNIT_CSV_SUFFIX,
    )

    # Resolve the CSV column suffix from the token here so an unknown unit fails
    # loudly before any disk write (the L2 rescale verb guards the factor lookup
    # symmetrically). The token drives suffix + label + factor — one source of
    # truth, so values and their declared unit can never diverge.
    if unit not in _VOLUMETRIC_UNIT_CSV_SUFFIX:
        raise ValueError(
            f"run_mask_aq_boundary got unsupported unit={unit!r}; expected one of "
            f"{sorted(_VOLUMETRIC_UNIT_CSV_SUFFIX)}."
        )
    csv_suffix = _VOLUMETRIC_UNIT_CSV_SUFFIX[unit]

    # The token also decides the TIME AXIS, not just the magnitude: the rate
    # tokens (``m3/j`` / ``m3/mois``) are scalar rescales that keep the daily grid;
    # the ``m3`` token is a calendar-month total VOLUME that re-bins daily→monthly.
    # ``aggregating`` gates that one branch once, here, so the two flux-build sites
    # below (loose CSV + GeoPackage net) can never re-bin differently.
    aggregating = unit == "m3"

    def _flux_series(arr):
        """Convert ONE daily per-direction ``m³/s`` series to the chosen unit.

        Returns ``(values, index)`` — the transformed series and the date index
        it lives on. For rate tokens this is the scalar ``volumetric_rescale`` on
        the unchanged daily index (``flux_resp.dates``); for ``m3`` it is the L2
        ``temporal_aggregate`` verb, which re-bins to monthly and hands back its
        own ``YYYY-MM`` index. Both branches only *call* a lower-layer verb and
        pick which returned index to persist — no ``×86400``, grouping or
        month-length arithmetic lives here (CLAUDE.md "L1 only orchestrates").
        """
        if aggregating:
            return twin.transform(
                kind="temporal_aggregate",
                arr=arr,
                dates=flux_resp.dates,
                frequency="monthly",
                agg_dimension="sum",
            )
        return (
            twin.transform(kind="volumetric_rescale", arr=arr, target_unit=unit),
            flux_resp.dates,
        )

    id_layers = [li.id_layer for li in twin.get_all_layers(aq_id)]
    face_orientations = twin.mask(
        kind="boundary_aq",
        id_compartment=aq_id,
        polygon=polygon,
        polygon_crs=polygon_crs,
        id_layers=id_layers,
    )
    face_responses = {
        direction: twin.fetch(
            kind="simulation_matrix",
            id_compartment=aq_id,
            outtype="MB",
            param=param,
            syear=syear,
            eyear=eyear,
        )
        for direction, param in AQ_FACE_DIRECTIONS.items()
    }
    flux_resp = twin.mask(
        kind="boundary_aq_flux",
        id_compartment=aq_id,
        polygon=polygon,
        polygon_crs=polygon_crs,
        syear=syear,
        eyear=eyear,
        face_responses=face_responses,
        face_orientations=face_orientations,
    )

    # Group the merged boundary edges into one ready-to-register GeoDataFrame per
    # aquifer layer the polygon reached. The grouping + GeoDataFrame construction
    # lives in the L2 assemble verb (backed by a pure L3 shaper), so this L1
    # orchestration builds no GeoDataFrame inline — see the "L1 only orchestrates"
    # golden rule in CLAUDE.md. The same per-layer gdfs feed both the registered
    # QGIS layers (below) and the GeoPackage ``cells_AQ_layer<id>`` blocks.
    aq_layers = twin.assemble(
        kind="boundary_aq_layers",
        edge_geometries=face_orientations.edge_geometries,
        cell_layer_ids=face_orientations.cell_layer_ids,
        crs=polygon_crs,
        face_directions=face_orientations.face_directions,
        # Same L3 formatting pass also emits the per-cell coarse-cell provenance
        # (``outside_ids_by_cell``) from the boundary_aq source map, so L1 forwards
        # it into the GeoPackage below without shaping any string itself.
        face_sources=face_orientations.face_sources,
    )
    entries = [
        AqBoundaryLayerEntry(
            id_layer=id_layer,
            gdf=gdf,
            layer_name=f"{area_name}_AQ_layer{id_layer}_boundary",
        )
        for id_layer, gdf in aq_layers.entries
    ]

    # True IFF at least one boundary face was sourced from smaller outside
    # neighbours (an EXT_cell coarse-inside face → non-empty ``outside_ids``).
    # Gates whether the coarse-cell source note is shipped into the two provenance
    # surfaces below (CSV header + GeoPackage provenance row), so the note appears
    # only when a value actually came from an outside neighbour. The per-cell
    # ``outside_ids`` strings themselves are L3-formatted (aq_layers), not here.
    has_coarse_source = any(aq_layers.outside_ids_by_cell.values())

    artefacts = []
    # Exclusive output mode (design D6): the loose per-(cell, direction) face-flux
    # CSV is the DEFAULT-mode artefact only. GeoPackage mode writes the .gpkg as
    # the sole artefact and suppresses this CSV — an XOR matching
    # run_mask_internal_values. The face-flux fetch above still runs
    # unconditionally because the GeoPackage net path needs the same data.
    if flux_resp.fluxes and not write_geopackage:
        os.makedirs(output_dir, exist_ok=True)
        cols = {}
        # For the ``m3`` token every column carries the SAME monthly index (all
        # per-direction series are aggregated over the same ``flux_resp.dates``);
        # capture it once for the DataFrame index. For rate tokens it stays the
        # daily ``flux_resp.dates`` — either way it comes back from ``_flux_series``
        # so the index and the values can never disagree on the time grid.
        row_index = flux_resp.dates
        for cell_id, dir_fluxes in flux_resp.fluxes.items():
            for direction, arr in dir_fluxes.items():
                # Transform m³/s → chosen unit via the L2 verb (single source; the
                # SAME ``_flux_series`` the GeoPackage net path uses). Suffix derives
                # from the token, so two runs differing only in unit don't collide.
                series, row_index = _flux_series(arr)
                cols[f"{cell_id}_{direction}_{csv_suffix}"] = series
        csv_df = pd.DataFrame(cols, index=pd.Index(row_index, name="date"))
        base = _artefact_basename("AQ", "boundary", "flux", syear, eyear)
        csv_path = os.path.join(output_dir, f"{base}.csv")
        # Ship the sign convention as a commented header line ahead of the data
        # rows (pandas.read_csv(comment="#") round-trips it cleanly). Sourced from
        # the one shared constant so the code comment and the file cannot drift.
        # When any face was sourced as EXT_cell (a coarse-inside side read from
        # smaller outside neighbours), add the coarse-cell source note plus the
        # per-cell ``outside_ids`` mapping so a ``<cell>_<dir>`` column holding a
        # negated outside sum is self-describing (design D6). Both extra lines are
        # sourced from the same L3-formatted map / shared constant, never inline
        # text, so the header and the file cannot drift.
        with open(csv_path, "w", newline="") as fh:
            fh.write(f"# {AQ_BOUNDARY_FLUX_SIGN_CONVENTION}\n")
            if has_coarse_source:
                fh.write(f"# {AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE}\n")
                for cid, out_ids in aq_layers.outside_ids_by_cell.items():
                    if out_ids:
                        fh.write(f"# outside_ids: {cid} <- {out_ids}\n")
            csv_df.to_csv(fh)
        artefacts.append(csv_path)

    # GeoPackage mode (opt-in, exclusive — design D6): reuse the generic
    # compartment_bundle assemble + geopackage export verbs to emit a single
    # transportable bundle as the SOLE artefact (the loose CSV above is suppressed).
    # The ragged ``{cell → {direction → series}}`` flux dict is flattened to one
    # NET daily series per boundary cell (sum over that cell's face directions).
    # The geometry surface is split per aquifer layer: each per-layer gdf (the
    # SAME object registered as a QGIS layer above) becomes one ``AQ_layer<id>``
    # block, so the writer emits a ``cells_AQ_layer<id>`` geometry layer per layer
    # — geometrically identical to the matching QGIS borders layer by
    # construction. The net-flux matrix for each block is row-aligned to that
    # layer's gdf by reading the per-cell net series back in the gdf's own
    # ``cell_id`` order. ``daily_values`` rows follow the block key, so they carry
    # ``compartment="AQ_layer<id>"`` (the per-layer split applies to the flux
    # rows too, keyed by ``cell_id`` within each layer). The empty-boundary guard
    # (no .gpkg when no fluxes) is the GeoPackage-mode counterpart of the
    # default-mode loose-CSV guard above; together they are an exclusive XOR.
    if write_geopackage and flux_resp.fluxes:
        # Per-cell net = sum over that cell's face directions of the SAME
        # per-direction series the loose CSV builds via ``_flux_series``. For the
        # ``m3`` token each per-direction series is already a monthly total, and
        # sum-of-monthly-sums = monthly-sum-of-the-net, so summing the aggregated
        # series is the correct net monthly volume (order is immaterial). The
        # shared time index (daily for rate tokens, monthly ``YYYY-MM`` for ``m3``)
        # comes back from ``_flux_series`` so the net values and the persisted
        # index can never disagree on the grid.
        net_by_cell = {}
        flux_index = flux_resp.dates
        for cell_id, dir_fluxes in flux_resp.fluxes.items():
            net = None
            for arr in dir_fluxes.values():
                series, flux_index = _flux_series(arr)
                net = series if net is None else net + series
            net_by_cell[cell_id] = np.asarray(net, dtype=float)
        # Bare matrices wrapped in a minimal ``.data`` / ``.dates`` duck-type so the
        # L3 ``build_compartment_bundle`` (which reads ``response.data`` /
        # ``response.dates``) can consume them without a new L3 response type.
        # ``.meta=None`` is supplied because the assembler also reads
        # ``response.meta`` to harvest a per-param unit — leaving it None makes it
        # skip ``boundary_flux`` there, so the explicit unit_override below is the
        # single source of the daily_values ``unit`` column.
        compartment_blocks = {}
        for entry in entries:
            layer_cell_ids = list(entry.gdf["cell_id"])
            net_matrix = np.vstack(
                [net_by_cell[cid] for cid in layer_cell_ids]
            )  # (n_layer_cells, n_periods), row-aligned to entry.gdf
            # ``dates=`` carries the monthly ``YYYY-MM`` index for ``m3`` and the
            # daily index otherwise — the writer stamps it onto the values-table
            # date column, so monthly rows are labelled by their month.
            resp_shim = SimpleNamespace(
                data=net_matrix, dates=flux_index, meta=None
            )
            compartment_blocks[f"AQ_layer{entry.id_layer}"] = (
                entry.gdf,
                {"boundary_flux": resp_shim},
                None,
            )
        bundle = twin.assemble(
            kind="compartment_bundle",
            label="AqBoundary",
            compartment_blocks=compartment_blocks,
            output_dir=output_dir,
            area_name=area_name,
            syear=syear,
            eyear=eyear,
            polygon=polygon,
            polygon_crs=polygon_crs,
            weighted=False,
            source_run=getattr(twin, "out_caw_directory", "") or "",
            # Ship the sign convention into every provenance row from the one
            # shared constant (so the code comment and the .gpkg cannot drift). For
            # the ``m3`` monthly-total mode, also ship the volume/partial-month
            # semantics (design D6) so the ``monthly_values`` rows stay
            # self-describing — again from a single shared constant, not inline text.
            provenance_extra={
                "sign_convention": AQ_BOUNDARY_FLUX_SIGN_CONVENTION,
                **(
                    {"boundary_flux_semantics": AQ_BOUNDARY_FLUX_MONTHLY_VOLUME_SEMANTICS}
                    if aggregating
                    else {}
                ),
                # Ship the coarse-cell source note into every provenance row only
                # when a coarse-inside face was actually sourced from smaller
                # outside neighbours (design D6). Same single-constant discipline
                # as the sign convention, so the .gpkg and the code cannot drift.
                **(
                    {"coarse_cell_source": AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE}
                    if has_coarse_source
                    else {}
                ),
            },
        )
        # The shim carries no ``meta["target_unit"]``, so the assembler leaves
        # ``unit_override`` empty for ``boundary_flux``; supply the chosen token
        # explicitly here so the daily_values ``unit`` column matches the rescaled
        # net values (single source of truth for value + label).
        twin.export(
            kind="geopackage",
            path=bundle.gpkg_path,
            data=bundle.compartment_blocks,
            options={
                "provenance_rows": bundle.provenance_rows,
                "unit_override": {"boundary_flux": unit},
                # Annotate each daily_values row with its cell's cardinal faces.
                # The map is produced at the single L3 formatting site (the
                # assemble verb) and forwarded as-is — L1 builds no dict — so the
                # geometry and daily_values faces strings agree per cell_id.
                "daily_values_faces": aq_layers.faces_by_cell,
                # Per-face structure spread across the seven fixed columns
                # (n_faces + faceN_orient / faceN_outid). Produced at the same
                # single L3 formatting site and forwarded as-is — L1 builds no
                # dict (golden rule; design D5) — so the writer materialises the
                # seven columns identically on the geometry layer and daily_values.
                # Passed unconditionally like ``daily_values_faces`` (every
                # boundary cell has a face structure); the whole block is already
                # gated by ``write_geopackage and flux_resp.fluxes``, so it fires
                # only when boundary cells exist.
                "daily_values_face_slots": aq_layers.face_slots_by_cell,
                # Same L3-formatted provenance for coarse cells: the comma-joined
                # smaller-outside-neighbour ids a coarse cell's value was sourced
                # from (empty for fine/equal cells), forwarded as-is so the
                # daily_values ``outside_ids`` column is self-describing (design D6).
                # Gated by ``has_coarse_source`` exactly like the CSV header line and
                # the provenance ``coarse_cell_source`` note above, so the three
                # surfaces stay consistent: with no EXT_cell face the column is
                # omitted, keeping all-INT_cell output unchanged.
                **(
                    {"daily_values_outside_ids": aq_layers.outside_ids_by_cell}
                    if has_coarse_source
                    else {}
                ),
                # In the monthly-total (``m3``) mode the values table holds one
                # row per calendar month, not per day, so name it accordingly;
                # the daily-grid tokens keep the L3 default ``daily_values``.
                **(
                    {"values_table_name": "monthly_values"} if aggregating else {}
                ),
            },
        )
        artefacts.append(bundle.gpkg_path)

    return MaskAqBoundaryResult(
        entries=entries,
        flux_gdf=None,
        artefacts=artefacts,
    )
