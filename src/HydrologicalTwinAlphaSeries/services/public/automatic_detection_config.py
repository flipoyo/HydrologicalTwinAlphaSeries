"""Automatic detection of CaWaQS project settings from filesystem conventions.

Pure-Python module: no QGIS, no PyQt. Importable from notebooks, server-side
processes, and the QGIS plugin alike. All inputs are plain strings; all
outputs are plain dicts.

Exposed:
    - detect_from_out_caw(out_caw_directory)
    - detect_project_neighbors(project_file_path)
    - DetectionError
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from HydrologicalTwinAlphaSeries.config.constants import (
    out_caw_folder_by_name as COMPARTMENT_FOLDERS,
)

_YEAR_TOKEN = re.compile(r"^[A-Z]+_[A-Z]+\.(\d{8})\.bin$")
_STEADY_TOKEN = re.compile(r"^[A-Z]+_[A-Z]+\.00\.bin$")


class DetectionError(ValueError):
    """Raised when the OUT_CAW folder cannot be interpreted as a CaWaQS run."""


def detect_from_out_caw(out_caw_directory: str) -> dict:
    """Discover CaWaQS simulation metadata from an output directory.

    Returns a dict with keys:
        compartments: list[str] - subset of {"AQ", "HYD", "WATBAL", "NSAT"}
        s_year: int             - start year (lowest YYYY observed)
        e_year: int             - end year (highest YYYY+1 observed)
        regime: str             - "Transient" or "Steady"
        warnings: list[str]     - non-fatal anomalies

    Raises DetectionError if the directory is missing or contains no
    recognizable Output_<MODULE>/ subfolders.
    """
    root = Path(out_caw_directory)
    if not root.is_dir():
        raise DetectionError(
            f"OUT_CAW directory does not exist or is not a directory: {out_caw_directory}"
        )

    compartments: list[str] = []
    year_ranges: dict[str, tuple[int, int]] = {}
    has_steady = False
    has_transient = False
    warnings: list[str] = []

    for module, folder_name in COMPARTMENT_FOLDERS.items():
        folder = root / folder_name
        if not folder.is_dir():
            continue
        compartments.append(module)

        years: list[int] = []
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if _STEADY_TOKEN.match(name):
                has_steady = True
                continue
            m = _YEAR_TOKEN.match(name)
            if m:
                token = m.group(1)
                start = int(token[:4])
                end = int(token[4:])
                if end == start + 1:
                    years.append(start)
                    has_transient = True

        if years:
            year_ranges[module] = (min(years), max(years) + 1)

    if not compartments:
        raise DetectionError(
            f"No Output_<MODULE>/ subfolders found in {out_caw_directory}. "
            "Expected at least one of: " + ", ".join(COMPARTMENT_FOLDERS.values())
        )

    if year_ranges:
        starts = {module: rng[0] for module, rng in year_ranges.items()}
        ends = {module: rng[1] for module, rng in year_ranges.items()}
        s_year = min(starts.values())
        e_year = max(ends.values())
        if len(set(starts.values())) > 1 or len(set(ends.values())) > 1:
            warnings.append(
                "Compartments disagree on year range: "
                + ", ".join(f"{m}={year_ranges[m][0]}-{year_ranges[m][1]}" for m in year_ranges)
                + f". Using widest range {s_year}-{e_year}."
            )
    else:
        s_year = 1970
        e_year = 2022

    if has_steady and not has_transient:
        regime = "Steady"
    else:
        regime = "Transient"
        if has_steady and has_transient:
            warnings.append(
                "Folder contains both steady (.00.bin) and transient yearly binaries; "
                "classified as Transient."
            )

    return {
        "compartments": compartments,
        "s_year": s_year,
        "e_year": e_year,
        "regime": regime,
        "warnings": warnings,
    }


def detect_project_neighbors(
    project_file_path: Optional[str],
) -> dict:
    """Best-effort lookup of QGIS project neighbors.

    Given the path to a .qgz/.qgs file (or None), search nearby directories
    for a geometry config JSON and a DATA_OBS/ directory.

    Returns a dict with keys (each may independently be None):
        geometry_config_path: str | None - path to config_geometries_*.json
        obs_directory: str | None        - path to DATA_OBS/
        project_name: str | None         - derived project name
    """
    result: dict = {
        "geometry_config_path": None,
        "obs_directory": None,
        "project_name": None,
    }

    if not project_file_path:
        return result

    project_file = Path(project_file_path)
    if not project_file.exists():
        return result

    project_dir = project_file.parent

    geometry_matches = sorted(
        project_dir.glob("config_geometries_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if geometry_matches:
        result["geometry_config_path"] = str(geometry_matches[0])

    for candidate in (project_dir, project_dir.parent, project_dir.parent.parent):
        data_obs = candidate / "DATA_OBS"
        if data_obs.is_dir():
            result["obs_directory"] = str(data_obs)
            break

    if result["obs_directory"]:
        obs_path = Path(result["obs_directory"])
        result["project_name"] = obs_path.parent.name
    else:
        result["project_name"] = project_dir.parent.name or project_dir.name

    return result
