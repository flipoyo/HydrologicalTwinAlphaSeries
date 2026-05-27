from pathlib import Path

import pytest

from HydrologicalTwinAlphaSeries.services.public.automatic_detection_config import (
    COMPARTMENT_FOLDERS,
    DetectionError,
    detect_from_out_caw,
    detect_project_neighbors,
)


def _make_transient_run(
    root: Path,
    modules: tuple[str, ...] = ("AQ", "HYD", "WATBAL", "NSAT"),
    s_year: int = 1989,
    e_year: int = 2023,
) -> None:
    """Build an OUT_CAW tree with yearly binaries spanning [s_year, e_year)."""
    var_per_module = {"AQ": "H", "HYD": "Q", "WATBAL": "MB", "NSAT": "MB"}
    name_on_disk = {"AQ": "AQ", "HYD": "HYD", "WATBAL": "WATBAL", "NSAT": "NONSAT"}
    for module in modules:
        folder = root / COMPARTMENT_FOLDERS[module]
        folder.mkdir(parents=True, exist_ok=True)
        for y in range(s_year, e_year):
            (folder / f"{name_on_disk[module]}_{var_per_module[module]}.{y}{y+1}.bin").touch()


def test_transient_run_all_four_compartments(tmp_path):
    _make_transient_run(tmp_path)

    result = detect_from_out_caw(str(tmp_path))

    assert result["compartments"] == ["AQ", "HYD", "WATBAL", "NSAT"]
    assert result["s_year"] == 1989
    assert result["e_year"] == 2023
    assert result["regime"] == "Transient"
    assert result["warnings"] == []


def test_steady_run(tmp_path):
    aq = tmp_path / "Output_AQ"
    aq.mkdir()
    (aq / "AQ_H.00.bin").touch()
    (aq / "AQ_MB.00.bin").touch()

    result = detect_from_out_caw(str(tmp_path))

    assert result["compartments"] == ["AQ"]
    assert result["regime"] == "Steady"


def test_partial_compartments(tmp_path):
    _make_transient_run(tmp_path, modules=("AQ", "HYD"))

    result = detect_from_out_caw(str(tmp_path))

    assert result["compartments"] == ["AQ", "HYD"]
    assert result["regime"] == "Transient"


def test_empty_folder_raises(tmp_path):
    with pytest.raises(DetectionError):
        detect_from_out_caw(str(tmp_path))


def test_non_existent_directory_raises(tmp_path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(DetectionError):
        detect_from_out_caw(str(missing))


def test_year_range_disagreement_warns(tmp_path):
    _make_transient_run(tmp_path, modules=("AQ",), s_year=1989, e_year=2023)
    _make_transient_run(tmp_path, modules=("HYD",), s_year=1989, e_year=2020)

    result = detect_from_out_caw(str(tmp_path))

    assert result["s_year"] == 1989
    assert result["e_year"] == 2023
    assert len(result["warnings"]) == 1
    assert "disagree" in result["warnings"][0].lower()


def test_project_neighbors_none_returns_all_none(tmp_path):
    result = detect_project_neighbors(None)

    assert result == {
        "geometry_config_path": None,
        "obs_directory": None,
        "project_name": None,
    }


def test_project_neighbors_picks_most_recent_geometry_config(tmp_path):
    project_dir = tmp_path / "Projet_SIG"
    project_dir.mkdir()
    project_file = project_dir / "project.qgz"
    project_file.touch()

    older = project_dir / "config_geometries_cwv.json"
    older.touch()
    older_stat = older.stat()
    import os
    os.utime(older, (older_stat.st_atime, older_stat.st_mtime - 1000))

    newer = project_dir / "config_geometries_CVZ.json"
    newer.touch()

    result = detect_project_neighbors(str(project_file))

    assert result["geometry_config_path"] == str(newer)


def test_project_neighbors_finds_sibling_data_obs(tmp_path):
    parent = tmp_path / "SEINE_3C_v2025"
    parent.mkdir()
    project_dir = parent / "Projet_SIG"
    project_dir.mkdir()
    project_file = project_dir / "project.qgz"
    project_file.touch()
    (project_dir / "config_geometries_CVZ.json").touch()

    data_obs = parent / "DATA_OBS"
    data_obs.mkdir()

    result = detect_project_neighbors(str(project_file))

    assert result["geometry_config_path"].endswith("config_geometries_CVZ.json")
    assert result["obs_directory"] == str(data_obs)
    assert result["project_name"] == "SEINE_3C_v2025"


def test_project_neighbors_existing_file_no_neighbors(tmp_path):
    project_file = tmp_path / "lone.qgz"
    project_file.touch()

    result = detect_project_neighbors(str(project_file))

    assert result["geometry_config_path"] is None
    assert result["obs_directory"] is None
