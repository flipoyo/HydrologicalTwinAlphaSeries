"""operations — the general commands: one per ``HydrologicalTwinClient`` operation.

Ring: L0. Each command builds the twin from the project file and its options
(``project.build_client``), calls the one client method it mirrors with the
keyword arguments its options name, and prints the typed result. Options are
named after the Python keyword (``--output-dir`` for ``output_dir``). The
simulated years of the mask commands come from the project file or
``--years``. A command only collects arguments: nothing is computed here, and
no default is added that the client does not already hold.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any

from ..services.public import FileGeoProvider
from . import project
from .twin import emit

#: command -> {subcommand -> HydrologicalTwinClient method it mirrors}.
COMMANDS: dict[str, dict[str | None, str]] = {
    "budget": {"barplot": "budget_barplot"},
    "regime": {"show": "hydrological_regime"},
    "map": {"watbal": "spatial_map_watbal", "aq": "spatial_map_aq"},
    "compare": {"simobs": "compare_sim_obs"},
    "criteria": {"compute": "statistical_criteria"},
    "mask": {
        "internal": "mask_internal_values",
        "hyd": "mask_hyd_boundary",
        "aq": "mask_aq_boundary",
    },
}

SUMMARIES = {
    "budget": "water-balance budget plots",
    "regime": "hydrological regime plots",
    "map": "spatial maps",
    "compare": "simulation against observations",
    "criteria": "statistical criteria at observation points",
    "mask": "select a domain by a polygon",
}

EXAMPLES = {
    ("budget", "barplot"): "htas budget barplot --period 2000-01-01 2010-12-31 --frequency Y "
    "--agg sum --output-dir out",
    ("regime", "show"): "htas regime show --compartment HYD --outtype Q --param discharge "
    "--var-label Discharge --units m3/s --savepath out/regime",
    ("map", "watbal"): "htas map watbal --param rain --period 2000-01-01 2010-12-31 "
    "--frequency Y --agg sum --id-layer 0 --output rain.gpkg",
    ("map", "aq"): "htas map aq --outtype H --param piezhead --layer-id-offset 1 "
    "--mode kind=spatial_map --mode layer=Layer1 --mode label=Head --period 2000-01-01 2010-12-31 "
    "--frequency Y --agg mean --output head.gpkg",
    ("compare", "simobs"): "htas compare simobs --mode pdf --compartment HYD --outtype Q "
    "--param discharge --ylabel Discharge --obs-unit m3/s "
    "--plot-period 2000-01-01 2010-12-31 --crit-period 2000-01-01 2010-12-31 --directory out",
    ("criteria", "compute"): "htas criteria compute --compartment HYD --outtype Q "
    "--param discharge --period 2000-01-01 2010-12-31 --output-dir out",
    ("mask", "internal"): "htas mask internal --polygon area.gpkg --spec AQ:MB:recharge:m3/j "
    "--output-dir out --temp-dir tmp --area-name basin",
    ("mask", "hyd"): "htas mask hyd --polygon area.gpkg --output-dir out --area-name basin",
    ("mask", "aq"): "htas mask aq --polygon area.gpkg --output-dir out --area-name basin",
}

def _scalar(text: str) -> Any:
    """A number stays a number (a quantile), anything else is text."""
    try:
        return float(text)
    except ValueError:
        return text


def _value(text: str) -> Any:
    """``null`` is ``None``; everything else stays text (a label ``2020`` is not a number)."""
    return None if text == "null" else text


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _mode(args: argparse.Namespace) -> dict:
    mode = dict(_read_json(args.mode_file)) if args.mode_file else {}
    for item in args.mode:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"--mode expects KEY=VALUE, got: {item!r}")
        mode[key] = _value(value)
    if not mode:
        raise ValueError("give the mode with --mode KEY=VALUE (repeatable) or --mode-file")
    needed = ["kind", "label"] + (["layer"] if mode.get("kind") == "spatial_map" else [])
    missing = [key for key in needed if key not in mode]
    if missing:
        raise ValueError(f"the mode needs {', '.join(missing)} (kind=spatial_map also needs layer)")
    return mode


def _specs(args: argparse.Namespace) -> list[tuple[str, str, str, str]]:
    specs = [tuple(spec) for spec in _read_json(args.specs_file)] if args.specs_file else []
    for item in args.spec:
        parts = item.split(":")
        if len(parts) != 4 or not all(parts):
            raise ValueError(f"--spec expects COMPARTMENT:OUTTYPE:PARAM:UNIT, got: {item!r}")
        specs.append(tuple(parts))
    if not specs:
        raise ValueError("give the specs with --spec (repeatable) or --specs-file")
    return specs


def read_polygon(args: argparse.Namespace) -> tuple[Any, str]:
    """The polygon of ``--polygon FILE`` (all its features, merged) and its CRS."""
    gdf = FileGeoProvider({"polygon": args.polygon}).get_layer("polygon")
    crs = args.polygon_crs or (gdf.crs.to_string() if gdf.crs is not None else None)
    if not crs:
        raise ValueError(f"{args.polygon} has no CRS: give --polygon-crs")
    geometry = gdf.geometry
    return (geometry.union_all() if hasattr(geometry, "union_all") else geometry.unary_union), crs


# --------------------------------------------------------------------- options
#: (flags, argparse keyword arguments). ``dest`` is the client keyword unless
#: ``_KWARG`` maps it. Required keyword arguments of the client are required here.
_PERIOD = {"nargs": 2, "metavar": ("START", "END"), "help": "YYYY-MM-DD YYYY-MM-DD"}
_BOOL = {"action": argparse.BooleanOptionalAction, "default": None}

_OPTIONS: dict[tuple[str, str], list[tuple[tuple[str, ...], dict[str, Any]]]] = {
    ("budget", "barplot"): [
        (("--period",), {**_PERIOD, "required": True}),
        (("--frequency",), {"required": True, "help": "Y, M or D"}),
        (("--agg",), {"required": True, "type": _scalar, "help": "sum, mean, max, min"}),
        (("--pluriannual",), {"action": "store_true", "help": "aggregate over the years"}),
        (("--output-dir",), {"required": True}),
        (("--variables",), {"nargs": "+", "help": "water-balance variables"}),
        (("--frequency-label",), {}),
        (("--agg-label",), {}),
    ],
    ("regime", "show"): [
        (("--compartment",), {"dest": "compartment_name", "required": True}),
        (("--outtype",), {"required": True}),
        (("--param",), {"required": True}),
        (("--var-label",), {"required": True}),
        (("--units",), {"required": True}),
        (("--savepath",), {"required": True}),
        (("--interactive",), _BOOL),
        (("--staticpng",), _BOOL),
        (("--staticpdf",), _BOOL),
        (("--period",), _PERIOD),
    ],
    ("map", "watbal"): [
        (("--param",), {"required": True}),
        (("--period",), {**_PERIOD, "required": True}),
        (("--frequency",), {"required": True}),
        (("--agg",), {"required": True, "type": _scalar}),
        (("--pluriannual",), {"action": "store_true"}),
        (("--id-layer",), {"type": int, "required": True}),
        (("--target-unit",), {}),
        (("--layer-name-param",), {}),
        (("--frequency-label",), {}),
        (("--agg-label",), {}),
    ],
    ("map", "aq"): [
        (("--outtype",), {"required": True}),
        (("--param",), {"required": True}),
        (("--layer-id-offset",), {"type": int, "required": True}),
        (("--mode",), {"action": "append", "default": [], "metavar": "KEY=VALUE",
                       "help": "kind, layer and label of the AQ resolution; repeatable"}),
        (("--mode-file",), {"metavar": "JSON", "help": "the mode as a JSON object"}),
        (("--period",), {**_PERIOD, "required": True}),
        (("--frequency",), {"required": True}),
        (("--agg",), {"required": True, "type": _scalar}),
        (("--pluriannual",), {"action": "store_true"}),
        (("--save-directory",), {}),
        (("--name-prefix",), {}),
        (("--unit",), {}),
        (("--frequency-label",), {}),
        (("--agg-label",), {}),
    ],
    ("compare", "simobs"): [
        (("--mode",), {"required": True, "choices": ["pdf", "interactive", "csv"]}),
        (("--compartment",), {"dest": "compartment_name", "required": True}),
        (("--outtype",), {"required": True}),
        (("--param",), {"required": True}),
        (("--ylabel",), {"required": True}),
        (("--obs-unit",), {"required": True}),
        (("--plot-period",), {**_PERIOD, "required": True}),
        (("--crit-period",), {**_PERIOD, "required": True}),
        (("--directory",), {"required": True}),
        (("--id-layer",), {"type": int}),
        (("--aggr",), {"type": _scalar}),
        (("--regime",), {"choices": ["Steady", "Transient"]}),
    ],
    ("criteria", "compute"): [
        (("--compartment",), {"dest": "compartment_name", "required": True}),
        (("--outtype",), {"required": True}),
        (("--param",), {"required": True}),
        (("--period",), {**_PERIOD, "required": True}),
        (("--output-dir",), {"required": True}),
        (("--metrics",), {"nargs": "+"}),
        (("--id-layer",), {"type": int}),
        (("--aggr",), {"type": _scalar}),
        (("--obs-unit",), {}),
    ],
    ("mask", "internal"): [
        (("--spec",), {"action": "append", "default": [], "metavar": "COMPARTMENT:OUTTYPE:PARAM:UNIT",
                       "help": "one series to extract; repeatable"}),
        (("--specs-file",), {"metavar": "JSON", "help": "the specs as a JSON list of 4-element lists"}),
        (("--output-dir",), {"required": True}),
        (("--temp-dir",), {"required": True}),
        (("--area-name",), {"required": True}),
        (("--write-geopackage",), _BOOL),
        (("--weighted",), _BOOL),
    ],
    ("mask", "hyd"): [
        (("--output-dir",), {"required": True}),
        (("--area-name",), {"required": True}),
    ],
    ("mask", "aq"): [
        (("--output-dir",), {"required": True}),
        (("--area-name",), {"required": True}),
        (("--write-geopackage",), {"action": "store_true", "default": None}),
        (("--temp-dir",), {}),
        (("--unit",), {"help": "m3/j or m3/mois"}),
    ],
}

#: Options that are not client keywords: input files, and where to save a result
#: that the client returns in memory.
_NOT_KWARGS = {
    "project", "out_caw", "obs_dir", "geometry_config", "years", "layer", "json",
    "handler", "parser", "command", "subcommand", "mode_file", "specs_file", "spec",
    "polygon", "polygon_crs", "output", "csv_file",
}


def _kwargs(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    """The client keywords the options name; an option left out is not passed."""
    out = {k: v for k, v in vars(args).items() if k not in _NOT_KWARGS and v is not None}
    for key in ("period", "plot_period", "crit_period"):
        if key in out:
            out[key] = tuple(out[key])
    if (args.command, args.subcommand) == ("map", "aq"):
        out["mode"] = _mode(args)
    if args.command == "mask":
        out["syear"], out["eyear"] = settings["start_year"], settings["end_year"]
        out["polygon"], out["polygon_crs"] = read_polygon(args)
    if (args.command, args.subcommand) == ("mask", "internal"):
        out["specs"] = _specs(args)
    return out


def _save_frame(frame: Any, path: str, layer: str | None = None) -> str:
    if layer is not None:  # a GeoDataFrame: a GeoPackage
        frame.to_file(path, layer=layer, driver="GPKG")
    else:
        frame.to_csv(path)
    return path


def _run(args: argparse.Namespace) -> int:
    settings = project.resolve(args)
    client = project.build_client(settings)
    method = COMMANDS[args.command][args.subcommand]
    result = getattr(client, method)(**_kwargs(args, settings))
    written = []
    if getattr(args, "csv_file", None) and getattr(result, "csv_data", None) is None:
        raise ValueError("--csv-file needs --mode csv")
    if getattr(args, "output", None):  # the map commands return a layer in memory
        written.append(_save_frame(result.gdf, args.output, result.layer_name))
    if getattr(args, "csv_file", None) and result.csv_data is not None:
        written.append(_save_frame(result.csv_data, args.csv_file))
    report = emit_report(result) + [f"wrote {path}" for path in written]
    emit(args, {"result": result, "written": written}, report)
    return 0


def emit_report(result: Any) -> list[str]:
    """One line per field of a typed result: paths and counts, never the data."""
    lines = []
    for field in dataclasses.fields(result):
        value = getattr(result, field.name)
        framed = hasattr(value, "shape") or hasattr(value, "columns")
        if value is None or (not framed and isinstance(value, (list, tuple, dict)) and not value):
            continue
        if framed:
            lines.append(f"{field.name}: {len(value)} rows")
        elif isinstance(value, (list, tuple)):
            lines.append(f"{field.name}: {len(value)} item(s)")
            lines += [f"  {item}" for item in value if isinstance(item, (str, Path))]
        else:
            lines.append(f"{field.name}: {value}")
    return lines


def _add_options(parser: argparse.ArgumentParser, key: tuple[str, str]) -> None:
    for flags, kwargs in _OPTIONS[key]:
        parser.add_argument(*flags, **kwargs)
    if key[0] == "mask":
        parser.add_argument("--polygon", required=True, metavar="FILE",
                            help="vector file holding the polygon(s); all features are merged")
        parser.add_argument("--polygon-crs", metavar="CRS", help="default: the file's own CRS")
    if key[0] == "map":
        parser.add_argument("--output", metavar="GPKG", help="write the map to this GeoPackage")
    if key == ("compare", "simobs"):
        parser.add_argument("--csv-file", metavar="FILE", help="write the csv mode's table here")
    project.add_twin_options(parser)
    parser.add_argument("--json", action="store_true")


def register_parsers(subparsers: argparse._SubParsersAction) -> None:
    for command, subs in COMMANDS.items():
        group = subparsers.add_parser(
            command, help=SUMMARIES[command],
            epilog="examples:\n  " + "\n  ".join(EXAMPLES[(command, s)] for s in subs),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        group.set_defaults(handler=None, parser=group)
        sub = group.add_subparsers(dest="subcommand")
        for name, method in subs.items():
            child = sub.add_parser(
                name, help=method.replace("_", " "),
                epilog="example: " + EXAMPLES[(command, name)],
            )
            _add_options(child, (command, name))
            child.set_defaults(handler=_run)
