"""Verify that the package version is accessible and consistent."""

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

import HydrologicalTwinAlphaSeries

ROOT = Path(__file__).resolve().parents[2]


def _toml(name: str) -> dict:
    return tomllib.loads((ROOT / name).read_text())


def test_version_attribute_exists():
    """__version__ must be a non-empty string."""
    assert hasattr(HydrologicalTwinAlphaSeries, "__version__")
    assert isinstance(HydrologicalTwinAlphaSeries.__version__, str)
    assert HydrologicalTwinAlphaSeries.__version__


def test_version_matches_metadata():
    """__version__ must equal importlib.metadata.version()."""
    assert HydrologicalTwinAlphaSeries.__version__ == version("HydrologicalTwinAlphaSeries")


def test_pixi_and_pyproject_versions_agree():
    """pixi.toml is what cgitsync reads; pyproject.toml carries the build's copy."""
    assert _toml("pixi.toml")["workspace"]["version"] == _toml("pyproject.toml")["project"]["version"]


def test_pyproject_holds_no_pixi_tables():
    """Pixi is configured in pixi.toml only."""
    assert "pixi" not in _toml("pyproject.toml").get("tool", {})


def test_pixi_tasks_and_python_floor():
    pixi = _toml("pixi.toml")
    tasks = pixi["tasks"]
    assert tasks["run"] == "python -m HydrologicalTwinAlphaSeries"
    assert tasks["test"] == "pytest"
    assert tasks["lint"] == "ruff check src tests"
    assert tasks["bump-version"] == "python .agent/.local/.dev/scripts/bump_version.py"
    assert tasks["bump-build"] == "python scripts/bump_build.py"
    assert pixi["dependencies"]["python"] == "3.11.*"
    assert _toml("pyproject.toml")["project"]["requires-python"] == ">=3.11"


def test_build_counter_shape():
    """__build__ is a YYYY.XX counter, separate from the SemVer."""
    assert re.fullmatch(r"\d{4}\.\d{2}", HydrologicalTwinAlphaSeries.__build__)


def test_user_guide_version_matches():
    guide = ROOT / "docs" / "hydrological_twin" / "HTAS_user_guide.tex"
    if not guide.is_file():
        pytest.skip("docs/hydrological_twin is not mounted")
    found = re.search(r"^\\def\\version\{([^}]+)\}", guide.read_text(), re.MULTILINE)
    assert found and found.group(1) == _toml("pixi.toml")["workspace"]["version"]
