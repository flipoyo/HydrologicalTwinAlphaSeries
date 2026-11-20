"""htas-dev: one command per verb and kind, generated from the registry; every field an option."""

import argparse
import dataclasses
import json

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from HydrologicalTwinAlphaSeries.cli import dev
from HydrologicalTwinAlphaSeries.cli import project as cli_project
from HydrologicalTwinAlphaSeries.cli.dev import COMMANDS, build_parser, main
from HydrologicalTwinAlphaSeries.ht.developer import KINDS, REQUESTS
from HydrologicalTwinAlphaSeries.ht.developer.api_types import ValuesResponse

TWIN = ["--out-caw", "/o", "--geometry-config", "/g.json", "--years", "2000", "2010"]


def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def test_every_registry_kind_has_a_command_and_back():
    top = _subparsers(build_parser())
    assert set(top) == set(KINDS) == set(COMMANDS)
    for verb, kinds in KINDS.items():
        children = _subparsers(top[verb])
        assert set(children) == {k.replace("_", "-") for k in kinds}
        for child in children.values():
            assert child.get_default("handler") is not None
        for name, mirrored in COMMANDS[verb].items():
            assert mirrored == verb and "_" not in name


def test_every_request_field_is_an_option():
    for verb, request in REQUESTS.items():
        child = next(iter(_subparsers(_subparsers(build_parser())[verb]).values()))
        dests = {a.dest for a in child._actions}
        for field in dataclasses.fields(request):
            if field.name in {"kind", "polygon", "polygon_crs"}:
                continue
            dest = dev._dest(field.name)
            assert dest in dests or dest + "_file" in dests, (verb, field.name)


@pytest.mark.parametrize("verb", list(KINDS))
def test_help_exits_zero(verb):
    kind = KINDS[verb][0].replace("_", "-")
    for argv in ([verb, "--help"], [verb, kind, "--help"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0


class _Twin:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __getattr__(self, verb):
        def call(request):
            self.calls.append((verb, request))
            return self.result

        return call


@pytest.fixture
def twin(monkeypatch):
    holder = {"twin": _Twin(ValuesResponse(data=np.arange(6.0).reshape(2, 3),
                                           dates=np.array(["2000-01-01", "2000-01-02"], "datetime64[D]"),
                                           meta={"a": 1}))}
    monkeypatch.setattr(cli_project, "build_twin", lambda settings: holder["twin"])
    return holder


def test_fetch_builds_the_request_from_the_options(twin, capsys):
    argv = ["fetch", "simulation-matrix", "--id-compartment", "1", "--outtype", "MB",
            "--param", "recharge", "--syear", "2000", "--eyear", "2010", "--pluriannual", *TWIN]
    assert main(argv) == 0
    (verb, request), = twin["twin"].calls
    assert verb == "fetch" and request.kind == "simulation_matrix"
    assert (request.id_compartment, request.outtype, request.syear) == (1, "MB", 2000)
    assert request.pluriannual is True and request.cutsdate is None  # left out: the default
    assert "data: 2 rows" in capsys.readouterr().out


def test_agg_is_text_or_a_quantile_and_lists_parse(twin):
    main(["fetch", "spatial-map", "--agg", "0.9", "--cell-ids", "1", "2", *TWIN])
    request = twin["twin"].calls[0][1]
    assert request.agg == 0.9 and request.cell_ids == [1, 2]


def test_output_writes_arrays_and_json_shows_shapes(twin, tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["fetch", "simulation-matrix", "--output", str(out), "--json", *TWIN]) == 0
    assert np.load(out / "data.npy").shape == (2, 3)
    assert np.load(out / "dates.npy").shape == (2,)
    data = json.loads(capsys.readouterr().out)
    assert len(data["written"]) == 2 and data["result"]["meta"] == {"a": 1}


def test_files_feed_array_fields_and_reserved_names_are_prefixed(twin, tmp_path):
    np.save(tmp_path / "d.npy", np.ones((2, 2)))
    (tmp_path / "o.json").write_text('{"unit_override": {}}')
    main(["transform", "temporal-aggregation", "--data-file", str(tmp_path / "d.npy"),
          "--frequency", "Monthly", "--agg-dimension", "mean", *TWIN])
    request = twin["twin"].calls[0][1]
    assert request.data.shape == (2, 2) and request.agg_dimension == "mean"
    main(["export", "geopackage", "--path", "/p.gpkg", "--options-file", str(tmp_path / "o.json"), *TWIN])
    assert twin["twin"].calls[1][1].options == {"unit_override": {}}
    main(["render", "budget-barplot", "--request-years", "2000-2010", *TWIN])
    assert twin["twin"].calls[2][1].years == "2000-2010"  # --years stayed the twin's own


def test_polygon_is_read_like_htas_mask(twin, tmp_path):
    path = tmp_path / "a.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1), box(3, 3, 4, 4)], crs="EPSG:2154").to_file(path, driver="GPKG")
    main(["mask", "polygon-cells", "--id-compartment", "1", "--polygon", str(path), *TWIN])
    request = twin["twin"].calls[0][1]
    assert request.polygon.geom_type == "MultiPolygon" and request.polygon_crs == "EPSG:2154"


def test_unreadable_file_and_verb_error_exit_two(twin, tmp_path, capsys):
    assert main(["transform", "criteria", "--bundle-file", str(tmp_path / "b.txt"), *TWIN]) == 2
    assert "cannot read" in capsys.readouterr().err.replace("htas-dev transform: ", "")

    def boom(request):
        raise ValueError("'mask(kind=area_values)' requires 'cell_ids' or 'polygon'")

    twin["twin"].mask = boom
    assert main(["mask", "area-values", *TWIN]) == 2
    assert capsys.readouterr().err.startswith("htas-dev mask:")


def test_json_lists_become_arrays_and_dates(twin, tmp_path):
    (tmp_path / "d.json").write_text("[1.0, 2.0]")
    (tmp_path / "t.json").write_text('["2000-01-01", "2000-01-02"]')
    main(["transform", "temporal-aggregation", "--data-file", str(tmp_path / "d.json"),
          "--dates-file", str(tmp_path / "t.json"), *TWIN])
    request = twin["twin"].calls[0][1]
    assert isinstance(request.data, np.ndarray) and request.data.tolist() == [1.0, 2.0]
    assert request.dates.dtype == np.dtype("datetime64[D]") and request.dates.shape == (2,)


def test_bad_json_for_the_field_exits_two(twin, tmp_path, capsys):
    (tmp_path / "l.json").write_text("[1, 2]")
    assert main(["export", "npy", "--options-file", str(tmp_path / "l.json"), *TWIN]) == 2
    assert "expects a JSON object" in capsys.readouterr().err
    (tmp_path / "x.json").write_text('["not a date"]')
    assert main(["transform", "temporal-aggregation", "--dates-file", str(tmp_path / "x.json"), *TWIN]) == 2
    assert "not dates" in capsys.readouterr().err


def test_typo_gets_a_hint(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["fech"])
    assert exc.value.code == 2 and "htas-dev: did you mean 'fetch'" in capsys.readouterr().err
