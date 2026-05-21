"""
Renderer module — pure rendering methods for CaWaQS-Viz.

All methods are stateless: they receive pre-computed data and produce plots.
No I/O (file reading/caching) happens here.
"""

import os
import time
from typing import Any, List, Tuple, Union

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from plotly.subplots import make_subplots


class Renderer:

    # ------------------------------------------------------------------
    # 1. Budget bar plot
    # ------------------------------------------------------------------
    @staticmethod
    def plot_budget_barplot(
        data_dict: dict,
        plot_title: str,
        output_folder: str = None,
        output_name: str = None,
        yaxis_unit: str = 'mm',
    ):
        """
        Plot interannual Budget bar chart (Plotly interactive + Matplotlib static).

        :param data_dict: Dict {var_name: (data_array, date_labels, param_name)}
        :param plot_title: Title of the plot
        :param output_folder: Directory for static image
        :param output_name: Name of saving file (without extension)
        """
        if not output_folder or not output_name:
            raise ValueError(
                "Budget rendering requires 'output_folder' and 'output_name' to produce a file."
            )

        colors = ["midnightblue", "forestgreen", "deepskyblue", "skyblue"]
        artefacts = []

        variables = list(data_dict.keys())
        first_key = variables[0]
        date_labels = data_dict[first_key][1]

        # --- Plotly interactive ---
        fig = go.Figure()

        data_sums = []
        for i, var in enumerate(variables):
            data_array, labels, _ = data_dict[var]

            if not np.array_equal(labels, date_labels):
                print(f"Warning: Date labels mismatch for {var}")

            fig.add_trace(go.Bar(
                x=date_labels,
                y=data_array,
                name=var,
                marker_color=colors[i % len(colors)]
            ))

            data_sums.append(np.sum(data_array))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            title=plot_title,
            xaxis_title='',
            yaxis_title=f'<b>Water level</b><br>[{yaxis_unit}]',
            xaxis=dict(type='category', showgrid=True, gridwidth=1, gridcolor='rgba(0,0,0,0.1)'),
            yaxis=dict(showgrid=True, gridwidth=1, gridcolor='rgba(0,0,0,0.1)'),
            legend_title_text='Water Balance variables'
        )

        text = "".join([
            f"<b>{var}</b> : {round(value, 1)} {yaxis_unit}<br>"
            for var, value in zip(variables, data_sums)
        ])
        fig.add_annotation(
            text=text, x=1, y=1,
            xref='paper', yref='paper', showarrow=False
        )

        # --- Matplotlib static ---
        fig_mpl, ax = plt.subplots(figsize=(12, 6))
        width = 0.8 / len(variables)
        x_pos = np.arange(len(date_labels))

        for i, var in enumerate(variables):
            data_array = data_dict[var][0]
            offset = width * i - (width * len(variables) / 2) + width / 2
            ax.bar(
                x_pos + offset,
                data_array,
                width=width,
                label=var,
                color=colors[i % len(colors)]
            )

        ax.set_xlabel('')
        ax.set_ylabel(f'Water level\n[{yaxis_unit}]')
        ax.set_title(plot_title)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(date_labels, rotation=45, ha='right')
        ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15),
                  fancybox=True, shadow=True, ncol=len(variables))
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.set_axisbelow(True)

        save_path = os.path.join(output_folder, output_name + '.png')
        plt.savefig(save_path, dpi=200, bbox_inches='tight')
        artefacts.append(save_path)
        print(f"Saved static plot to: {save_path}")

        plt.close(fig_mpl)
        return artefacts

    # ------------------------------------------------------------------
    # 2. Hydrological regime
    # ------------------------------------------------------------------
    @staticmethod
    def plot_hydrological_regime(
        data: np.ndarray,
        obs_point_names: list,
        month_labels: np.ndarray,
        var: str,
        units: str,
        savepath: str,
        interactive: bool = False,
        staticpng: bool = True,
        staticpdf: bool = True,
        years: Union[str, None] = None,
        **kwargs: Any,
    ):
        """
        Plot interannual hydrological regime.

        :param data: interannual data array (n_months x n_obs_points)
        :param obs_point_names: list of observation point names
        :param month_labels: array of month labels
        :param var: Variable name (e.g. 'Discharge')
        :param units: Variable units
        :param savepath: Directory to save static plots
        :param interactive: Whether to prepare the interactive plot
        :param staticpng: Whether to save static PNG files
        :param staticpdf: Whether to save static PDF file
        :param years: Year range string for filename
        """
        legacy_interactive = kwargs.pop("interractiv", None)
        if legacy_interactive is not None:
            interactive = legacy_interactive
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        if not staticpng and not staticpdf:
            raise ValueError(
                "Hydrological regime rendering requires at least one static file output."
            )

        artefacts = []

        if interactive is True:
            fig = go.Figure()

            traces = [
                go.Bar(x=month_labels, y=data[:, i], name=obs_point_names[i])
                for i in range(len(obs_point_names))
            ]

            buttons = [
                dict(
                    args=[{"y": [data[:, i]], "name": obs_point_names[i]}],
                    label=obs_point_names[i],
                    method="restyle",
                )
                for i in range(len(obs_point_names))
            ]

            fig.add_trace(traces[0])

            fig.update_layout(
                width=1000, height=700, autosize=True,
                template="plotly_white",
                xaxis=dict(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)"),
                yaxis=dict(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)"),
            )

            fig.update_yaxes(
                title_text=f"<b>Hydrological Regime - {var}</b><br>[{units}]"
            )
            fig.update_xaxes(title_text="")

            fig.update_layout(
                updatemenus=[
                    dict(
                        buttons=buttons,
                        direction="down",
                        pad={"r": 10, "t": 10},
                        showactive=True,
                        x=0.1, xanchor="left",
                        y=1.1, yanchor="top",
                    )
                ]
            )
        if staticpng is True:
            for i, mp in enumerate(obs_point_names):
                fig = plt.figure(figsize=(15, 10))
                ax = plt.gca()

                if var == 'Discharge':
                    units_label = "$[m^3.s^{-1}]$"
                else:
                    units_label = "$[m\\ above\\ sea\\ level]$"

                ax.bar(month_labels, data[:, i], color='royalblue')
                ax.set_ylabel(f'{var} {units_label}')
                ax.set_title(f'{var} - {mp}')

                savepath_file = os.path.join(savepath, f'{var}_{mp}_{years}.png')

                ax.grid(True, linestyle='--', alpha=0.7)
                ax.set_axisbelow(True)

                if var != "Discharge":
                    y_min = np.min(data[:, i])
                    y_max = np.max(data[:, i])
                    ax.set_ylim(y_min - 0.05 * abs(y_min), y_max + 0.05 * abs(y_max))

                fig.savefig(savepath_file, dpi=200, bbox_inches='tight')
                plt.close(fig)
                artefacts.append(savepath_file)
                print(f"Saved PNG: {savepath_file}")

        if staticpdf is True:
            savepath_file = os.path.join(savepath, f'{var}_{years}.pdf')
            with PdfPages(savepath_file) as pdf:
                for i, mp in enumerate(obs_point_names):
                    print(f'OBSERVATION POINT : {mp}')

                    fig = plt.figure(figsize=(15, 10))
                    ax = plt.gca()

                    if var == 'Discharge':
                        units_label = "$[m^3.s^{-1}]$"
                    else:
                        units_label = "$[m\\ above\\ sea\\ level]$"

                    ax.bar(month_labels, data[:, i], color='royalblue')
                    ax.set_ylabel(f'{var} {units_label}')
                    ax.set_title(f'{var} - {mp}')

                    ax.grid(True, linestyle='--', alpha=0.7)
                    ax.set_axisbelow(True)

                    if var != "Discharge":
                        y_min = np.min(data[:, i])
                        y_max = np.max(data[:, i])
                        ax.set_ylim(y_min - 0.05 * abs(y_min), y_max + 0.05 * abs(y_max))

                    pdf.savefig(fig, orientation="portrait")
                    plt.close(fig)

            print(f"Saved PDF: {savepath_file}")
            artefacts.append(savepath_file)

        return artefacts

    # ------------------------------------------------------------------
    # 3. Plot sim only (helper for render_simobs_pdf)
    # ------------------------------------------------------------------
    @staticmethod
    def plot_sim(
        df_sim: pd.DataFrame,
        point_name: str,
        point_id_cell: int,
        point_id_layer: int,
        ylabel: str,
    ) -> plt.Figure:
        """
        Plot simulated-only time series.

        :param df_sim: DataFrame with 'sim' column
        :param point_name: Name of the extraction point
        :param point_id_cell: Cell ID
        :param point_id_layer: Layer ID
        :param ylabel: Y-axis label
        :return: matplotlib figure
        """
        df_sim.index = pd.to_datetime(df_sim.index)

        fig, ax = plt.subplots()

        df_sim["sim"].plot(
            ax=ax, color="red", legend="Simulated", linewidth=0.5
        )

        title = (
            f"{point_name} - {point_id_cell}\n"
            f"(id caw cell : {point_id_cell}, id_layer : {point_id_layer})"
        )
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(ylabel)

        ax.grid(True, linestyle="--", alpha=0.7)
        ax.legend(loc='upper left')

        return fig

    # ------------------------------------------------------------------
    # 4. Plot sim+obs (helper for render_simobs_pdf)
    # ------------------------------------------------------------------
    @staticmethod
    def plot_sim_obs(
        df_sim_obs: pd.DataFrame,
        obs_point_name: str,
        obs_point_id_cell: int,
        obs_point_id_layer: int,
        ylabel: str,
        criteria: dict = None,
        crit_start: Union[str, None] = None,
        crit_end: Union[str, None] = None,
    ) -> plt.Figure:
        """
        Plot daily simulated and observed time series with performance statistics.

        Unit conversion is handled upstream in _prepare_sim_obs_data.

        :param df_sim_obs: DataFrame with 'sim' and 'obs' columns (already unit-converted)
        :param obs_point_name: Observation point name
        :param obs_point_id_cell: Cell ID
        :param obs_point_id_layer: Layer ID
        :param ylabel: Y-axis label
        :param criteria: Pre-computed performance criteria dict (e.g. {'nash': 0.85, ...})
        :param crit_start: Start date for criteria period display
        :param crit_end: End date for criteria period display
        :return: matplotlib figure
        """
        df_sim_obs.index = pd.to_datetime(df_sim_obs.index)

        fig, ax = plt.subplots()

        # Plot obs values
        df_sim_obs["obs"].plot(
            ax=ax,
            color="green",
            marker="o",
            linestyle="",
            legend="Observed",
            markersize=0.8,
        )

        # Plot sim values
        df_sim_obs["sim"].plot(
            ax=ax, color="red", legend="Simulated", linewidth=0.5
        )

        title = (
            f"{obs_point_name} - {obs_point_id_cell}\n"
            f"(id caw cell : {obs_point_id_cell}, id_layer : {obs_point_id_layer})"
        )
        ax.set_title(title, fontsize=10)

        if criteria is not None:
            period_str = ""
            if crit_start is not None and crit_end is not None:
                period_str = f"PERIOD : {crit_start} to {crit_end}\n"
            crits_text = period_str + "".join(
                [f"{key}: {round(value, 2)}\n" for key, value in criteria.items()]
            )
            ax.text(
                0.95, 0.95, crits_text,
                transform=ax.transAxes,
                ha="right", va="top",
                fontsize=8,
                multialignment="right",
                usetex=False,
            )

        ax.set_ylabel(ylabel)

        ax.grid(True, linestyle="--", alpha=0.7)
        ax.legend(loc='upper left')

        return fig

    # ------------------------------------------------------------------
    # 5. Render sim/obs PDF (pure rendering, receives pre-read data)
    # ------------------------------------------------------------------
    @staticmethod
    def render_simobs_pdf(
        simdf: pd.DataFrame,
        obs_df: pd.DataFrame,
        obs_points: list,
        ext_points: list,
        pdf_file_path: str,
        ylabel: str,
        crit_start: str = None,
        crit_end: str = None,
        plotstartdate: str = None,
        plotenddate: str = None,
    ) -> List[str]:
        """
        Render sim/obs comparison to a multi-page PDF.

        Unit conversion is handled upstream in _prepare_sim_obs_data.

        :param simdf: Simulation DataFrame (index=dates, columns=cell_ids as int,
            already unit-converted)
        :param obs_df: Observation DataFrame (index=dates, columns=obs_point_ids,
            already unit-converted) or None
        :param obs_points: List of dicts with keys: name, id_cell, id_layer, id_point, criteria
        :param ext_points: List of dicts with keys: name, id_cell, id_layer
        :param pdf_file_path: Full path for the output PDF
        :param ylabel: Y-axis label
        :param crit_start: Start date for criteria period display
        :param crit_end: End date for criteria period display
        :param plotstartdate: Start date for plot range
        :param plotenddate: End date for plot range
        """
        stime = time.time()
        print('PLOTTING PDF')

        with PdfPages(pdf_file_path) as pdf:
            if obs_points is not None and obs_points != []:
                for obs_point in obs_points:
                    print(f'OBSERVATION POINT : {obs_point}')

                    sim = simdf[[obs_point['id_cell']]]
                    sim.columns = ['sim']

                    if obs_df is not None and obs_point['id_point'] in obs_df.columns:
                        obs = obs_df[[obs_point['id_point']]]
                        obs.columns = ['obs']
                    else:
                        obs = pd.DataFrame(index=sim.index, columns=['obs'])
                        obs['obs'] = np.NaN
                        print(
                            f"Warning : {obs_point['id_point']} hasn't been found "
                            "in observation data folder."
                        )

                    df_sim_obs = pd.concat([sim, obs], axis=1)

                    if plotstartdate and plotenddate:
                        df_sim_obs_to_plot = df_sim_obs.loc[plotstartdate:plotenddate]
                    else:
                        df_sim_obs_to_plot = df_sim_obs

                    fig = Renderer.plot_sim_obs(
                        df_sim_obs=df_sim_obs_to_plot,
                        obs_point_name=obs_point['name'],
                        obs_point_id_cell=obs_point['id_cell'],
                        obs_point_id_layer=obs_point['id_layer'],
                        ylabel=ylabel,
                        criteria=obs_point.get('criteria'),
                        crit_start=crit_start,
                        crit_end=crit_end,
                    )

                    if fig is not None:
                        pdf.savefig(fig, orientation="portrait")
                        plt.close(fig)
                    else:
                        print(f"No figure was generated for observation point {obs_point['name']}")

            if ext_points is not None and ext_points != []:
                for ext_point in ext_points:
                    print(f'EXTRACTION POINT : {ext_point}')

                    sim = simdf[[ext_point['id_cell']]]
                    sim.columns = ['sim']

                    fig = Renderer.plot_sim(
                        df_sim=sim,
                        point_name=ext_point['name'],
                        point_id_cell=ext_point['id_cell'],
                        point_id_layer=ext_point['id_layer'],
                        ylabel=ylabel,
                    )

                    if fig is not None:
                        pdf.savefig(fig, orientation="portrait")
                        plt.close(fig)
                    else:
                        print(f"No figure was generated for extraction point {ext_point['name']}")

            etime = time.time()
            print(f"WRITING PLOT PDF : {etime - stime} seconds")

        return [pdf_file_path]

    # ------------------------------------------------------------------
    # 6. Render sim/obs interactive (Plotly, receives pre-read data)
    # ------------------------------------------------------------------
    @staticmethod
    def render_simobs_interactive(
        sim_obs_data: List[Tuple[pd.DataFrame, str]],
        ylabel: str,
        df_other_variable: pd.DataFrame = None,
        other_variable_config: dict = None,
        out_file_path: str = None,
        crit_start: str = None,
        crit_end: str = None,
        criteria_per_point: list = None,
    ) -> List[str]:
        """
        Render interactive sim/obs comparison using Plotly.

        :param sim_obs_data: List of (df_sim_obs, obs_point_name) tuples.
            Each df_sim_obs has 'sim' and 'obs' columns, datetime index.
        :param ylabel: Y-axis label
        :param df_other_variable: Optional additional variable DataFrame
        :param other_variable_config: Config dict for other variables
        :param out_file_path: Optional HTML output path
        :param crit_start: Start date for criteria calculation
        :param crit_end: End date for criteria calculation
        """
        if out_file_path is None:
            raise ValueError(
                "Interactive sim/obs rendering requires 'out_file_path' to produce a file."
            )

        print("Plotting graph with plotly ...", flush=True)

        if df_other_variable is None:
            rows = 1
        else:
            rows = 2

        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True)
        annotations = []

        # LaTeX label mapping for criteria keys
        _crit_labels = {
            "n_obs": "N_{obs}",
            "avg_ratio": "\\overline{x_s}/\\overline{x_o}",
            "pbias": "PBIAS",
            "std_ratio": "\\left(\\frac{{\\mu_s}}{{\\mu_o}}\\right)",
            "rmse": "RMSE",
            "nash": "NASH",
            "kge": "KGE",
        }

        for n_obs, (df_sim_obs_mp, obs_name) in enumerate(sim_obs_data):
            # Build annotation text from pre-computed criteria
            crits = criteria_per_point[n_obs] if criteria_per_point else None

            if crits is not None and crit_start is not None and crit_end is not None:
                text = "$ Period : " + crit_start + " to " + crit_end + "\\\\"
                for key, value in crits.items():
                    label = _crit_labels.get(key, key)
                    text += label + " : " + str(round(value, 2)) + "\\\\"
                text += "$"
            else:
                text = ""

            annotations.append(
                dict(
                    text=text,
                    x=1, y=1,
                    xref="paper", yref="paper",
                    showarrow=False,
                    align="left",
                    font=dict(size=16),
                )
            )

            # Add traces
            fig.add_trace(
                go.Scatter(
                    x=df_sim_obs_mp.index,
                    y=df_sim_obs_mp["sim"],
                    mode="lines",
                    name="Simulated",
                    line=dict(color="red", width=0.8),
                    visible=n_obs < 1,
                ),
                row=1, col=1
            )

            fig.add_trace(
                go.Scatter(
                    x=df_sim_obs_mp.index,
                    y=df_sim_obs_mp["obs"],
                    mode="markers",
                    name="Observed",
                    marker=dict(color="green", size=5),
                    visible=n_obs < 1,
                ),
                row=1, col=1
            )

            # Adding other variables if provided
            if df_other_variable is not None:
                for v in df_other_variable.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=df_other_variable.index,
                            y=df_other_variable[v],
                            mode=other_variable_config[v]['kind'],
                            name=other_variable_config[v]['legend'],
                        ),
                        row=2, col=1
                    )

        n_obs_points = len(sim_obs_data)

        # Update layout
        fig.update_layout(
            xaxis_title="",
            yaxis_title=ylabel,
            width=1500, height=900,
            autosize=True,
            template="plotly_white",
            xaxis=dict(
                showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)",
                title=dict(font=dict(size=18)), tickfont=dict(size=16),
            ),
            yaxis=dict(
                showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)",
                title=dict(font=dict(size=18)), tickfont=dict(size=16),
            ),
            annotations=[annotations[0]] if annotations else [],
        )

        # Create dropdown buttons
        obs_names = [item[1] for item in sim_obs_data]
        dropdown_buttons = [
            {
                "label": obs_names[obs_point_index],
                "method": "update",
                "args": [
                    {
                        "visible": [
                            True
                            if j == obs_point_index * 2
                            or j == obs_point_index * 2 + 1
                            else False
                            for j in range(n_obs_points * 2)
                        ]
                    },
                    {"annotations": [annotations[obs_point_index]]},
                ],
            }
            for obs_point_index in range(n_obs_points)
        ]

        fig.update_layout(
            width=1500, height=900,
            updatemenus=[
                {
                    "buttons": dropdown_buttons,
                    "direction": "down",
                    "showactive": True,
                    "x": 0.1, "xanchor": "left",
                    "y": 1.1, "yanchor": "top",
                },
            ],
        )

        fig.write_html(out_file_path, include_plotlyjs='cdn', full_html=True)

        print("Done", flush=True)
        return [out_file_path]
