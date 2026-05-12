"""Orchestration layer for the HydrologicalTwinClient.

Each ``run_<name>`` function takes a configured :class:`HydrologicalTwin` as
its first positional argument and a small set of user-facing keyword
arguments. The fetch -> transform -> render chaining for a given dialog
operation lives here and nowhere else.

This module has zero ``qgis.*`` / ``PyQt5`` / ``processing`` imports — it is
usable from a notebook or a future HTTP server.
"""

from __future__ import annotations

import os
from typing import Sequence, Tuple

import numpy as np

from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    HydrologicalRegimeResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
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
    """Render a sim-vs-obs comparison plot, either as PDF or interactive HTML.

    :param twin: A configured-and-loaded :class:`HydrologicalTwin`.
    :param mode: ``"pdf"`` (static, multi-page PDF) or ``"interactive"``
        (single HTML written via Plotly).
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
    if mode not in ("pdf", "interactive"):
        raise ValueError(f"mode must be 'pdf' or 'interactive', got {mode!r}")

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
