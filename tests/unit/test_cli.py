"""The htas CLI: registry, grammar, help, exit codes, project file, mirror rule."""

import argparse
import ast
import json
from pathlib import Path

import pytest

from HydrologicalTwinAlphaSeries.cli import COMMANDS, build_parser, main
from HydrologicalTwinAlphaSeries.cli import project as cli_project
from HydrologicalTwinAlphaSeries.ht.client import HydrologicalTwinClient
from HydrologicalTwinAlphaSeries.services.public import FileGeoProvider

SRC = Path(__file__).resolve().parents[2] / "src" / "HydrologicalTwinAlphaSeries"


def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def test_every_registry_entry_mirrors_a_client_method():
    for command, subs in COMMANDS.items():
        for method in subs.values():
            assert callable(getattr(HydrologicalTwinClient, method)), (command, method)


def test_parser_matches_registry_and_has_handlers():
    top = _subparsers(build_parser())
    assert set(top) == set(COMMANDS)
    for command, subs in COMMANDS.items():
        children = _subparsers(top[command])
        if None in subs:  # a command acts or has subcommands, never both
            assert len(subs) == 1 and not children
        else:
            assert set(children) == set(subs)
            for child in children.values():
                assert child.get_default("handler") is not None


def test_grammar_plain_words():
    for command, subs in COMMANDS.items():
        assert command.isalpha()
        for sub in subs:
            assert sub is None or sub.isalpha()


@pytest.mark.parametrize("argv", [[], ["detect"], ["detect", "run"], ["describe"]])
def test_help_exits_zero(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--help"])
    assert exc.value.code == 0


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "build" in capsys.readouterr().out


def test_no_command_prints_help_and_succeeds(capsys):
    assert main([]) == 0
    assert "detect" in capsys.readouterr().out


def test_command_without_subcommand_refuses(capsys):
    assert main(["detect"]) == 2
    assert "run" in capsys.readouterr().out


def test_typo_gets_a_hint(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["descibe"])
    assert exc.value.code == 2
    assert "did you mean 'describe'" in capsys.readouterr().err


def _make_out_caw(root: Path) -> Path:
    folder = root / "Output_AQ"
    folder.mkdir(parents=True)
    from HydrologicalTwinAlphaSeries.config.constants import out_caw_folder_by_name

    out = root / "OUT"
    (out / out_caw_folder_by_name["AQ"]).mkdir(parents=True)
    (out / out_caw_folder_by_name["AQ"] / "AQ_PRESS.20000001.bin").write_text("")
    return out


def test_detect_run_writes_project_and_json(tmp_path, capsys):
    out = _make_out_caw(tmp_path)
    target = tmp_path / "htas.toml"
    assert main(["detect", "run", str(out), "--write", str(target), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["compartments"] == ["AQ"]
    stored = cli_project.read_project(str(target))
    assert stored["out_caw"] == str(out) and stored["compartments"] == ["AQ"]


def test_detect_run_missing_directory_exits_two(tmp_path, capsys):
    assert main(["detect", "run", str(tmp_path / "nope")]) == 2
    assert capsys.readouterr().err.startswith("htas detect:")


def test_detect_neighbors_merges_into_project(tmp_path):
    proj = tmp_path / "p" / "case.qgz"
    proj.parent.mkdir()
    proj.write_text("")
    (tmp_path / "DATA_OBS").mkdir()
    target = tmp_path / "htas.toml"
    cli_project.write_project(str(target), {"out_caw": "/x"})
    assert main(["detect", "neighbors", str(proj), "--write", str(target)]) == 0
    stored = cli_project.read_project(str(target))
    assert stored["out_caw"] == "/x" and stored["obs_dir"].endswith("DATA_OBS")


def test_describe_without_inputs_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["describe"]) == 2
    assert "missing" in capsys.readouterr().err


def test_options_override_project_file(tmp_path):
    f = tmp_path / "htas.toml"
    cli_project.write_project(str(f), {"out_caw": "/a", "layers": {"L": "/l.gpkg"}})
    args = build_parser().parse_args(
        ["describe", "--project", str(f), "--out-caw", "/b", "--years", "2000", "2003", "--layer", "M=/m.gpkg"]
    )
    s = cli_project.resolve(args)
    assert s["out_caw"] == "/b" and s["start_year"] == 2000
    assert s["layers"] == {"L": "/l.gpkg", "M": "/m.gpkg"}


def test_bad_layer_option_rejected():
    args = build_parser().parse_args(["describe", "--layer", "nopath"])
    with pytest.raises(ValueError):
        cli_project.resolve(args)


def test_file_geo_provider_errors(tmp_path):
    provider = FileGeoProvider({"A": tmp_path / "missing.gpkg"})
    with pytest.raises(ValueError):
        provider.get_layer("B")
    with pytest.raises(FileNotFoundError):
        provider.get_layer("A")


def test_cli_imports_stay_in_bounds():
    for file in (SRC / "cli").glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(("qgis", "PyQt")), (file, name)
            if isinstance(node, ast.ImportFrom) and node.level >= 2:
                mod = node.module or ""
                assert mod.split(".")[0] in {"", "config", "ht", "services"}, (file, mod)
                if mod.startswith("ht"):
                    assert mod == "ht.client", (file, mod)
                if mod.startswith("services"):
                    assert mod == "services.public", (file, mod)
