"""dev — ``htas-dev <verb> <kind>``: the developer verbs of ``HydrologicalTwin``.

Ring: L0, the second console script (HtasCli D1 (a)). One command per
dispatching verb, one subcommand per ``kind`` of ``ht.developer.KINDS``, the
kind written with hyphens (``simulation_matrix`` is ``simulation-matrix``).
Every command calls one ``HydrologicalTwin`` verb with one request, and the
registry and the options are generated, so a new kind or a new request field
reaches the command line in the same change:

- each field of the verb's request dataclass is an option named after it
  (``id_compartment`` is ``--id-compartment``); one left out is not passed;
- a field that is a number, text, a flag or a list is parsed; any other (an
  array, a mapping, a frame) is read from a file, ``--NAME-file``: ``.npy``,
  ``.json``, or a vector file;
- ``--polygon FILE`` and ``--polygon-crs`` read a polygon as ``htas mask`` does;
- ``--output DIR`` writes the arrays and tables of the result (a long array is
  only a shape in ``--json``), so a result can feed the next command.

A kind that needs a result object from an earlier step (a simulation–observation
bundle, aquifer inputs) cannot be fed from files.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import typing
from pathlib import Path
from typing import Any, Union

import numpy as np

from ..ht.developer import KINDS, REQUESTS
from ..services.public import FileGeoProvider
from . import operations, project, runner
from .twin import emit

#: verb -> {hyphenated kind -> the HydrologicalTwin verb it calls}.
COMMANDS: dict[str, dict[str | None, str]] = {
    verb: {kind.replace("_", "-"): verb for kind in kinds} for verb, kinds in KINDS.items()
}

SUMMARIES = {
    "fetch": "read data out of the twin",
    "mask": "select by a polygon",
    "transform": "compute on fetched data",
    "assemble": "shape computed blocks into a payload to write",
    "render": "draw figures",
    "export": "write a data file",
}

EXAMPLES = {
    "fetch": "htas-dev fetch simulation-matrix --id-compartment 1 --outtype MB --param recharge "
    "--syear 2000 --eyear 2010 --output out",
    "mask": "htas-dev mask polygon-cells --id-compartment 1 --polygon area.gpkg",
    "transform": "htas-dev transform temporal-aggregation --data-file out/data.npy "
    "--dates-file out/dates.npy --frequency Monthly --agg-dimension mean --output out2",
    "assemble": "htas-dev assemble boundary-aq-layers --crs-file crs.json --edge-geometries-file e.json",
    "render": "htas-dev render budget-barplot --data-file data.json --output-folder out "
    "--output-name budget --plot-title Budget",
    "export": "htas-dev export npy --path out/recharge.npy --data-file out/data.npy",
}

#: Flags the twin options already use: a request field of that name gets a prefix.
_RESERVED = {"--project", "--out-caw", "--obs-dir", "--geometry-config", "--years", "--layer",
             "--json", "--output", "--help"}
#: Request fields read as a polygon, not from a file.
_POLYGON = {"polygon", "polygon_crs"}


def _scalar(text: str) -> Any:
    try:
        return float(text)
    except ValueError:
        return text


def _plain(hint: Any) -> Any:
    """A request field's type reduced to int, float, str, bool, ``("list", t)``,
    ``"scalar"`` (text or number) or ``None`` (read it from a file)."""
    origin = typing.get_origin(hint)
    if origin is Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return _plain(args[0])
        return "scalar" if set(args) == {str, float} else None
    if origin is list:
        inner = _plain(typing.get_args(hint)[0]) if typing.get_args(hint) else None
        return ("list", inner) if inner in (int, float, str) else None
    return hint if hint in (int, float, str, bool) else None


def _flag(name: str) -> str:
    flag = "--" + name.replace("_", "-")
    return "--request-" + flag[2:] if flag in _RESERVED else flag


def _dest(name: str) -> str:
    """Where argparse stores the field: the name, unless a twin option already uses it."""
    return "request_" + name if "--" + name.replace("_", "-") in _RESERVED else name


def _add_field_options(parser: argparse.ArgumentParser, request: type) -> None:
    hints = typing.get_type_hints(request)
    for field in dataclasses.fields(request):
        name = field.name
        if name == "kind":
            continue
        if name in _POLYGON:
            continue
        kind = _plain(hints[name])
        flag = _flag(name)
        if kind is bool:
            parser.add_argument(flag, dest=_dest(name), action=argparse.BooleanOptionalAction, default=None)
        elif isinstance(kind, tuple):
            parser.add_argument(flag, dest=_dest(name), nargs="+", type=kind[1], default=None)
        elif kind == "scalar":
            parser.add_argument(flag, dest=_dest(name), type=_scalar, default=None)
        elif kind is not None:
            parser.add_argument(flag, dest=_dest(name), type=kind, default=None)
        else:
            parser.add_argument(
                flag + "-file", dest=_dest(name) + "_file", metavar="FILE", default=None,
                help=".npy, .json or a vector file",
            )
    if {"polygon", "polygon_crs"} <= {f.name for f in dataclasses.fields(request)}:
        parser.add_argument("--polygon", metavar="FILE",
                            help="vector file holding the polygon(s); all features are merged")
        parser.add_argument("--polygon-crs", metavar="CRS", help="default: the file's own CRS")


def _load(path: str) -> Any:
    suffix = Path(path).suffix.lower()
    if suffix == ".npy":
        return np.load(path, allow_pickle=False)
    if suffix == ".json":
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if suffix in (".gpkg", ".shp", ".geojson"):
        return FileGeoProvider({"layer": path}).get_layer("layer")
    raise ValueError(f"cannot read {path}: expected .npy, .json, .gpkg, .shp or .geojson")


def _is_array(hint: Any) -> bool:
    """Whether a request field is an ``np.ndarray`` (alone or optional)."""
    return np.ndarray in (hint, *typing.get_args(hint))


def _is_mapping(hint: Any) -> bool:
    import collections.abc

    members = (hint, *typing.get_args(hint))
    return any(typing.get_origin(m) in (dict, collections.abc.Mapping) or m is dict for m in members)


def _coerce(name: str, hint: Any, value: Any, path: str) -> Any:
    """A value read from a file, as the field's type wants it.

    A JSON list for an array field, or a list of numbers for an untyped one such as
    ``data``, becomes an array (dates written as text become dates); a JSON value for
    a mapping field must be an object."""
    if (_is_array(hint) or hint is typing.Any) and isinstance(value, list):
        array = np.asarray(value)
        if hint is typing.Any:  # an untyped field (``data``): an array only when it is numbers
            return array if array.dtype.kind in "iufb" else value
        if array.dtype.kind in "US":
            try:
                array = array.astype("datetime64[D]")
            except ValueError as exc:
                raise ValueError(f"{path}: --{name.replace('_', '-')} holds text that is not dates") from exc
        return array
    if _is_mapping(hint) and not isinstance(value, dict):
        raise ValueError(f"{path}: --{name.replace('_', '-')} expects a JSON object")
    return value


def _request_kwargs(args: argparse.Namespace, request: type) -> dict[str, Any]:
    out: dict[str, Any] = {}
    hints = typing.get_type_hints(request)
    for field in dataclasses.fields(request):
        name = field.name
        if name == "kind" or name in _POLYGON:
            continue
        dest = _dest(name)
        if getattr(args, dest, None) is not None:
            out[name] = getattr(args, dest)
        elif getattr(args, dest + "_file", None):
            path = getattr(args, dest + "_file")
            out[name] = _coerce(name, hints[name], _load(path), path)
    if getattr(args, "polygon", None):
        out["polygon"], out["polygon_crs"] = operations.read_polygon(args)
    return out


def _write(result: Any, directory: str) -> list[str]:
    """The arrays and tables of a result, one file each, in *directory*."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    named = (
        {f.name: getattr(result, f.name) for f in dataclasses.fields(result)}
        if dataclasses.is_dataclass(result) and not isinstance(result, type)
        else {"result": result}
    )
    written = []
    for name, value in named.items():
        if hasattr(value, "to_file") and hasattr(value, "geometry"):  # a GeoDataFrame
            path = target / f"{name}.gpkg"
            value.to_file(path, layer=name, driver="GPKG")
        elif hasattr(value, "to_csv"):  # a DataFrame
            path = target / f"{name}.csv"
            value.to_csv(path)
        elif isinstance(value, np.ndarray) and value.dtype != object:
            path = target / f"{name}.npy"
            np.save(path, value)
        else:
            continue
        written.append(str(path))
    return written


def _run(args: argparse.Namespace) -> int:
    verb, kind = args.command, args.request_kind
    twin = project.build_twin(project.resolve(args))
    request = REQUESTS[verb](kind=kind, **_request_kwargs(args, REQUESTS[verb]))
    result = getattr(twin, verb)(request=request)
    written = _write(result, args.output) if args.output else []
    report = operations.emit_report(result) if hasattr(result, "__dataclass_fields__") else [
        f"result: {type(result).__name__}"
    ]
    emit(args, {"result": result, "written": written}, report + [f"wrote {p}" for p in written])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="htas-dev",
        description="The developer verbs of HydrologicalTwin, one command per verb and one "
        "subcommand per kind (hyphens for underscores). Use 'htas-dev <verb> --help' for an example.",
    )
    parser.add_argument("--version", action="version", version=_version())
    subparsers = parser.add_subparsers(dest="command")
    for verb, subs in COMMANDS.items():
        group = subparsers.add_parser(
            verb, help=SUMMARIES[verb], epilog="example:\n  " + EXAMPLES[verb],
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        group.set_defaults(handler=None, parser=group)
        sub = group.add_subparsers(dest="subcommand")
        for name in subs:
            child = sub.add_parser(name, help=f"{verb} kind {name.replace('-', '_')}")
            _add_field_options(child, REQUESTS[verb])
            project.add_twin_options(child)
            child.add_argument("--output", metavar="DIR",
                               help="write the arrays and tables of the result here")
            child.add_argument("--json", action="store_true")
            child.set_defaults(handler=_run, request_kind=name.replace("-", "_"))
    return parser


def _version() -> str:
    from .. import __build__, __version__

    return f"%(prog)s {__version__} (build {__build__})"


def main(argv: typing.Sequence[str] | None = None) -> int:
    return runner.run(build_parser(), COMMANDS, argv)


__all__ = ["COMMANDS", "build_parser", "main"]


if __name__ == "__main__":  # python -m HydrologicalTwinAlphaSeries.cli.dev
    raise SystemExit(main())
