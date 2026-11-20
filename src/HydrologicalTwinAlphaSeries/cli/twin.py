"""twin — the twin commands: ``detect run``, ``detect neighbors``, ``describe``.

Ring: L0. Each handler calls one :class:`HydrologicalTwinClient` method and
prints; ``--json`` prints the returned structure.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from typing import Any

from ..ht.client import HydrologicalTwinClient
from . import project

#: command -> {subcommand or None -> HydrologicalTwinClient method it mirrors}.
COMMANDS: dict[str, dict[str | None, str]] = {
    "detect": {"run": "detect_from_out_caw", "neighbors": "detect_project_neighbors"},
    "describe": {None: "describe"},
}

SUMMARIES = {
    "detect": "detect a project's settings from files",
    "describe": "load the twin and describe its compartments",
}

EXAMPLES = {
    ("detect", "run"): "htas detect run /data/OUT_CAW --write htas.toml",
    ("detect", "neighbors"): "htas detect neighbors /data/project.qgz --write htas.toml",
    ("describe", None): "htas describe --project htas.toml --json",
}


#: Arrays longer than this appear in ``--json`` as their shape only.
_MAX_ARRAY = 1000


def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "columns") and hasattr(value, "__len__"):  # a (Geo)DataFrame: its shape
        return {"rows": len(value), "columns": [str(c) for c in value.columns]}
    if hasattr(value, "tolist"):
        if getattr(value, "size", 0) > _MAX_ARRAY:  # a long array: its shape, not its content
            return {"shape": list(value.shape), "dtype": str(value.dtype)}
        return value.tolist()
    if hasattr(value, "value") and not isinstance(value, (str, int, float)):
        return value.value
    return value


def emit(args: argparse.Namespace, payload: Any, report: list[str]) -> None:
    if args.json:
        print(json.dumps(_to_jsonable(payload), indent=2, default=str))
    else:
        print("\n".join(report))


def _detect_run(args: argparse.Namespace) -> int:
    found = HydrologicalTwinClient.detect_from_out_caw(args.out_caw_directory)
    report = [
        f"compartments: {', '.join(found['compartments'])}",
        f"years: {found['s_year']}-{found['e_year']}  regime: {found['regime']}",
    ] + [f"warning: {w}" for w in found["warnings"]]
    if args.write:
        project.write_project(args.write, {
            "out_caw": args.out_caw_directory,
            "compartments": found["compartments"],
            "start_year": found["s_year"],
            "end_year": found["e_year"],
            "regime": found["regime"],
        })
        report.append(f"wrote {args.write}")
    emit(args, {**found, "written": args.write}, report)
    return 0


def _detect_neighbors(args: argparse.Namespace) -> int:
    found = HydrologicalTwinClient.detect_project_neighbors(args.qgis_project)
    report = [f"{k}: {v if v is not None else '-'}" for k, v in found.items()]
    if args.write:
        project.write_project(args.write, {
            "geometry_config": found["geometry_config_path"],
            "obs_dir": found["obs_directory"],
            "project_name": found["project_name"],
        })
        report.append(f"wrote {args.write}")
    emit(args, {**found, "written": args.write}, report)
    return 0


def _describe(args: argparse.Namespace) -> int:
    client = project.build_client(project.resolve(args))
    description = client.describe()
    report = [f"state: {description.state}", f"compartments: {description.n_compartments}"] + [
        f"  {c.id_compartment} {c.name}: {c.n_layers} layer(s), {c.n_cells} cells"
        for c in description.compartments
    ]
    emit(args, description, report)
    return 0


def register_parsers(subparsers: argparse._SubParsersAction) -> None:
    detect = subparsers.add_parser(
        "detect", help=SUMMARIES["detect"],
        epilog="examples:\n  " + EXAMPLES[("detect", "run")] + "\n  " + EXAMPLES[("detect", "neighbors")],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    detect.set_defaults(handler=None, parser=detect)
    sub = detect.add_subparsers(dest="subcommand")
    run = sub.add_parser("run", help="read an OUT_CAW directory", epilog="example: " + EXAMPLES[("detect", "run")])
    run.add_argument("out_caw_directory", metavar="OUT_CAW")
    run.add_argument("--write", metavar="FILE", help="write or update this project file")
    run.add_argument("--json", action="store_true")
    run.set_defaults(handler=_detect_run)
    nb = sub.add_parser("neighbors", help="find files next to a QGIS project", epilog="example: " + EXAMPLES[("detect", "neighbors")])
    nb.add_argument("qgis_project", metavar="QGIS_PROJECT")
    nb.add_argument("--write", metavar="FILE", help="write or update this project file")
    nb.add_argument("--json", action="store_true")
    nb.set_defaults(handler=_detect_neighbors)

    describe = subparsers.add_parser("describe", help=SUMMARIES["describe"], epilog="example: " + EXAMPLES[("describe", None)])
    project.add_twin_options(describe)
    describe.add_argument("--json", action="store_true")
    describe.set_defaults(handler=_describe)
