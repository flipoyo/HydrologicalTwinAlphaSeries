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

from .api_types import BudgetBarplotResult, HydrologicalRegimeResult


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
