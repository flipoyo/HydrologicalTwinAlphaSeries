import pandas as pd
import pytest

from HydrologicalTwinAlphaSeries.services.Renderer import Renderer


def test_plot_budget_barplot_writes_png_without_show(tmp_path, monkeypatch):
    def _fail_show(self):
        raise AssertionError("Plotly show() must not be called")

    monkeypatch.setattr("plotly.graph_objects.Figure.show", _fail_show)

    artefacts = Renderer.plot_budget_barplot(
        data_dict={"rain": ([1.0, 2.0], ["2000", "2001"], "rain")},
        plot_title="Budget",
        output_folder=str(tmp_path),
        output_name="budget",
    )

    assert artefacts == [str(tmp_path / "budget.png")]
    assert (tmp_path / "budget.png").exists()


def test_plot_budget_barplot_requires_output_file_parameters():
    with pytest.raises(ValueError, match="produce a file"):
        Renderer.plot_budget_barplot(
            data_dict={"rain": ([1.0], ["2000"], "rain")},
            plot_title="Budget",
        )


def test_render_simobs_interactive_writes_html_without_show(tmp_path, monkeypatch):
    def _fail_show(self):
        raise AssertionError("Plotly show() must not be called")

    monkeypatch.setattr("plotly.graph_objects.Figure.show", _fail_show)

    df = pd.DataFrame(
        {"sim": [1.0, 2.0], "obs": [1.5, 2.5]},
        index=pd.to_datetime(["2000-01-01", "2000-01-02"]),
    )
    output_path = tmp_path / "sim_obs.html"

    artefacts = Renderer.render_simobs_interactive(
        sim_obs_data=[(df, "Point A")],
        ylabel="Level",
        out_file_path=str(output_path),
    )

    assert artefacts == [str(output_path)]
    assert output_path.exists()


def test_render_simobs_interactive_requires_output_file():
    df = pd.DataFrame(
        {"sim": [1.0], "obs": [1.5]},
        index=pd.to_datetime(["2000-01-01"]),
    )

    with pytest.raises(ValueError, match="out_file_path"):
        Renderer.render_simobs_interactive(
            sim_obs_data=[(df, "Point A")],
            ylabel="Level",
        )
