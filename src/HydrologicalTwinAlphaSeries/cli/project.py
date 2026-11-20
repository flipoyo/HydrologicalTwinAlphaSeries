"""project — the ``htas.toml`` project file, and the twin built from it.

Ring: L0. The file is the counterpart of a ``.cgs``: where the CaWaQS output,
the observations and the geometry config are, which layers sit in which files.
Command-line options override the file, key by key. Nothing here computes: it
reads arguments, writes the file ``detect`` fills, and calls the client.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

from ..config import ConfigGeometry, ConfigProject
from ..ht.client import HydrologicalTwinClient
from ..services.public import FileGeoProvider

DEFAULT_PROJECT_FILE = "htas.toml"

_SCALAR_KEYS = (
    "project_name", "out_caw", "obs_dir", "geometry_config", "start_year", "end_year", "regime",
)


def add_twin_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("twin (override the project file)")
    group.add_argument("--project", metavar="FILE", help=f"project file (default ./{DEFAULT_PROJECT_FILE} if present)")
    group.add_argument("--out-caw", metavar="DIR", help="CaWaQS OUT_CAW directory")
    group.add_argument("--obs-dir", metavar="DIR", help="DATA_OBS directory")
    group.add_argument("--geometry-config", metavar="JSON", help="geometry config JSON")
    group.add_argument("--years", nargs=2, type=int, metavar=("START", "END"), help="simulation years")
    group.add_argument("--layer", action="append", default=[], metavar="NAME=PATH", help="a layer file; repeatable")


def read_project(path: str | None) -> dict[str, Any]:
    if path is None:
        default = Path(DEFAULT_PROJECT_FILE)
        if not default.is_file():
            return {}
        path = str(default)
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(f"project file not found: {file}")
    return tomllib.loads(file.read_text(encoding="utf-8"))


def _quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_quote(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def write_project(path: str, data: dict[str, Any]) -> None:
    """Merge *data* into the project file at *path* (existing keys are kept unless replaced)."""
    file = Path(path)
    merged = tomllib.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
    for key, value in data.items():
        if isinstance(value, dict):
            merged.setdefault(key, {}).update(value)
        elif value is not None:
            merged[key] = value
    tables = {k: v for k, v in merged.items() if isinstance(v, dict)}
    lines = [f"{k} = {_quote(v)}" for k, v in merged.items() if not isinstance(v, dict)]
    for name, table in tables.items():
        lines += ["", f"[{name}]"] + [f"{_quote(k)} = {_quote(v)}" for k, v in table.items()]
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve(args: argparse.Namespace) -> dict[str, Any]:
    """The project file with every option layered over it."""
    settings = read_project(args.project)
    for key in ("out_caw", "obs_dir", "geometry_config"):
        if getattr(args, key, None):
            settings[key] = getattr(args, key)
    if getattr(args, "years", None):
        settings["start_year"], settings["end_year"] = args.years
    layers = dict(settings.get("layers", {}))
    for item in getattr(args, "layer", []):
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            raise ValueError(f"--layer expects NAME=PATH, got: {item!r}")
        layers[name] = path
    settings["layers"] = layers
    return settings


def build_client(settings: dict[str, Any]) -> HydrologicalTwinClient:
    for key in ("out_caw", "geometry_config", "start_year", "end_year"):
        if settings.get(key) in (None, ""):
            raise ValueError(
                f"missing '{key}': give it as an option or in the project file "
                f"(htas detect run … --write {DEFAULT_PROJECT_FILE})"
            )
    config_geom = ConfigGeometry.fromJsonFile(settings["geometry_config"])
    config_proj = ConfigProject.fromDict({
        "json_path_geometries": settings["geometry_config"],
        "projectName": settings.get("project_name", ""),
        "cawOutDirectory": settings["out_caw"],
        "startSim": settings["start_year"],
        "endSim": settings["end_year"],
        "obsDirectory": settings.get("obs_dir", ""),
        "regime": settings.get("regime", "Transient"),
    })
    return HydrologicalTwinClient.build(
        {
            "project_name": settings.get("project_name", ""),
            # every client operation reads the simulated years from the metadata
            "start_year": settings["start_year"],
            "end_year": settings["end_year"],
        },
        configure_kwargs={
            "config_geom": config_geom,
            "config_proj": config_proj,
            "out_caw_directory": settings["out_caw"],
            "obs_directory": settings.get("obs_dir", ""),
        },
        load_kwargs={"geo_provider": FileGeoProvider(settings["layers"])},
    )
