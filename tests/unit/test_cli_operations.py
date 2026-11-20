"""The htas operation commands: one per client operation, arguments collected and passed on."""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.cli import COMMANDS, main
from HydrologicalTwinAlphaSeries.cli import project as cli_project
from HydrologicalTwinAlphaSeries.ht.client import HydrologicalTwinClient
from HydrologicalTwinAlphaSeries.ht.client.api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    SpatialMapWatbalResult,
)

#: The client methods that are not operations: construction and detection.
NOT_OPERATIONS = {
    "build", "configure", "load", "describe", "is_ready",
    "detect_from_out_caw", "detect_project_neighbors",
}
PERIOD = ["2000-01-01", "2010-12-31"]
TWIN = ["--out-caw", "/o", "--geometry-config", "/g.json", "--years", "2000", "2010"]


def _operations() -> set[str]:
    names = {n for n in dir(HydrologicalTwinClient) if not n.startswith("_")}
    return names - NOT_OPERATIONS


def test_every_client_operation_has_a_command():
    mirrored = {m for subs in COMMANDS.values() for m in subs.values()}
    assert _operations() <= mirrored, sorted(_operations() - mirrored)


class _Client:
    """Stands in for the client: records the call, returns what the test sets."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            return self.result

        return call


@pytest.fixture
def client(monkeypatch):
    holder = {}

    def build(settings):
        holder["settings"] = settings
        return holder["client"]

    monkeypatch.setattr(cli_project, "build_client", build)
    holder["client"] = _Client(BudgetBarplotResult(png_path="/out/b.png", csv_path="/out/b.csv"))
    return holder


def test_budget_barplot_passes_the_keywords(client, capsys):
    argv = ["budget", "barplot", "--period", *PERIOD, "--frequency", "Y", "--agg", "sum",
            "--output-dir", "/out", *TWIN]
    assert main(argv) == 0
    (name, kwargs), = client["client"].calls
    assert name == "budget_barplot"
    assert kwargs == {"period": tuple(PERIOD), "frequency": "Y", "agg": "sum",
                      "pluriannual": False, "output_dir": "/out"}
    assert "png_path: /out/b.png" in capsys.readouterr().out


def test_quantile_agg_is_a_number(client):
    main(["budget", "barplot", "--period", *PERIOD, "--frequency", "M", "--agg", "0.9",
          "--output-dir", "/o", *TWIN])
    assert client["client"].calls[0][1]["agg"] == 0.9


def test_json_output_parses(client, capsys):
    main(["budget", "barplot", "--period", *PERIOD, "--frequency", "Y", "--agg", "sum",
          "--output-dir", "/out", "--json", *TWIN])
    data = json.loads(capsys.readouterr().out)
    assert data["result"]["png_path"] == "/out/b.png"


def test_required_option_missing_exits_two(client, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["budget", "barplot", "--frequency", "Y", *TWIN])
    assert exc.value.code == 2
    assert "--period" in capsys.readouterr().err


def test_tristate_flag_is_passed_only_when_given(client):
    base = ["regime", "show", "--compartment", "HYD", "--outtype", "Q", "--param", "discharge",
            "--var-label", "Q", "--units", "m3/s", "--savepath", "/s", *TWIN]
    main(base)
    assert "interactive" not in client["client"].calls[0][1]
    main([*base, "--interactive", "--no-staticpdf"])
    kwargs = client["client"].calls[1][1]
    assert kwargs["interactive"] is True and kwargs["staticpdf"] is False
    assert kwargs["compartment_name"] == "HYD"


def test_map_aq_mode_from_pairs_and_file(client, tmp_path):
    base = ["map", "aq", "--outtype", "H", "--param", "piezhead", "--layer-id-offset", "1",
            "--period", *PERIOD, "--frequency", "Y", "--agg", "mean", *TWIN]
    client["client"].result = SpatialMapWatbalResult(gdf=gpd.GeoDataFrame(), layer_name="L")
    main([*base, "--mode", "kind=spatial_map", "--mode", "layer=L1", "--mode", "label=2020"])
    assert client["client"].calls[0][1]["mode"] == {"kind": "spatial_map", "layer": "L1", "label": "2020"}
    mode_file = tmp_path / "mode.json"
    mode_file.write_text('{"kind": "aquifer_outcropping_map", "layer": "L1"}')
    main([*base, "--mode-file", str(mode_file), "--mode", "label=Out"])
    assert client["client"].calls[1][1]["mode"] == {
        "kind": "aquifer_outcropping_map", "layer": "L1", "label": "Out"}
    assert main(base) == 2  # no mode at all
    assert main([*base, "--mode", "kind=spatial_map", "--mode", "label=Head"]) == 2  # no layer
    assert main([*base, "--mode", "kind=aquifer_outcropping_map"]) == 2  # no label
    assert main([*base, "--mode", "kind=aquifer_outcropping_map", "--mode", "layer=null",
                 "--mode", "label=Out"]) == 0
    assert client["client"].calls[-1][1]["mode"]["layer"] is None


def test_map_output_writes_a_geopackage(client, tmp_path):
    gdf = gpd.GeoDataFrame({"v": [1.0]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:2154")
    client["client"].result = SpatialMapWatbalResult(gdf=gdf, layer_name="rain")
    target = tmp_path / "rain.gpkg"
    assert main(["map", "watbal", "--param", "rain", "--period", *PERIOD, "--frequency", "Y",
                 "--agg", "sum", "--id-layer", "0", "--output", str(target), *TWIN]) == 0
    assert gpd.read_file(target, layer="rain").shape[0] == 1


def test_csv_file_needs_csv_mode(client, tmp_path, capsys):
    client["client"].result = CompareSimObsResult(
        mode="pdf", pdf_path="/d/x.pdf", html_path=None, csv_data=None, output_directory="/d")
    assert main(["compare", "simobs", "--mode", "pdf", "--compartment", "HYD", "--outtype", "Q",
                 "--param", "discharge", "--ylabel", "Q", "--obs-unit", "m3/s",
                 "--plot-period", *PERIOD, "--crit-period", *PERIOD, "--directory", "/d",
                 "--csv-file", str(tmp_path / "t.csv"), *TWIN]) == 2
    assert "--mode csv" in capsys.readouterr().err


def test_compare_csv_file(client, tmp_path):
    frame = pd.DataFrame({"sim": [1.0], "obs": [2.0]})
    client["client"].result = CompareSimObsResult(
        mode="csv", pdf_path=None, html_path=None, csv_data=frame, output_directory="/d")
    target = tmp_path / "t.csv"
    assert main(["compare", "simobs", "--mode", "csv", "--compartment", "HYD", "--outtype", "Q",
                 "--param", "discharge", "--ylabel", "Q", "--obs-unit", "m3/s",
                 "--plot-period", *PERIOD, "--crit-period", *PERIOD, "--directory", "/d",
                 "--csv-file", str(target), *TWIN]) == 0
    assert pd.read_csv(target, index_col=0).shape == (1, 2)


def _polygon(tmp_path: Path, crs="EPSG:2154") -> str:
    path = tmp_path / "area.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 2, 2), box(5, 5, 6, 6)], crs=crs).to_file(path, driver="GPKG")
    return str(path)


def test_mask_internal_specs_polygon_and_years(client, tmp_path):
    client["client"].result = BudgetBarplotResult(png_path=None, csv_path=None)
    specs_file = tmp_path / "specs.json"
    specs_file.write_text('[["HYD", "Q", "discharge", "m3/s"]]')
    argv = ["mask", "internal", "--polygon", _polygon(tmp_path), "--spec", "AQ:MB:recharge:m3/j",
            "--specs-file", str(specs_file), "--output-dir", "/o", "--temp-dir", "/t",
            "--area-name", "basin", "--no-weighted", *TWIN]
    assert main(argv) == 0
    kwargs = client["client"].calls[0][1]
    assert kwargs["specs"] == [("HYD", "Q", "discharge", "m3/s"), ("AQ", "MB", "recharge", "m3/j")]
    assert (kwargs["syear"], kwargs["eyear"]) == (2000, 2010)
    assert kwargs["polygon_crs"] == "EPSG:2154" and kwargs["weighted"] is False
    assert kwargs["polygon"].geom_type == "MultiPolygon"  # the two features, merged


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_mask_bad_spec_and_missing_crs_exit_two(client, tmp_path, capsys):
    common = ["--output-dir", "/o", "--temp-dir", "/t", "--area-name", "a", *TWIN]
    assert main(["mask", "internal", "--polygon", _polygon(tmp_path), "--spec", "AQ:MB", *common]) == 2
    nocrs = tmp_path / "nocrs.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)]).to_file(nocrs, driver="GPKG")
    assert main(["mask", "hyd", "--polygon", str(nocrs), "--output-dir", "/o", "--area-name", "a", *TWIN]) == 2
    assert "--polygon-crs" in capsys.readouterr().err
    assert main(["mask", "hyd", "--polygon", str(nocrs), "--polygon-crs", "EPSG:2154",
                 "--output-dir", "/o", "--area-name", "a", *TWIN]) == 0


def test_build_client_puts_the_years_in_the_metadata(monkeypatch):
    """audit #15: every client operation reads these two keys from the metadata."""
    seen = {}

    def build(metadata, **_):
        seen.update(metadata)
        return object()

    monkeypatch.setattr(cli_project.ConfigGeometry, "fromJsonFile", staticmethod(lambda p: object()))
    monkeypatch.setattr(cli_project.ConfigProject, "fromDict", staticmethod(lambda d: object()))
    monkeypatch.setattr(cli_project.HydrologicalTwinClient, "build", staticmethod(build))
    cli_project.build_client({"out_caw": "/o", "geometry_config": "/g", "start_year": 2000,
                              "end_year": 2010, "layers": {}})
    assert seen["start_year"] == 2000 and seen["end_year"] == 2010
