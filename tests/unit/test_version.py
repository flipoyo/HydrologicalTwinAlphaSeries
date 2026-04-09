"""Verify that the package version is accessible and consistent."""

from importlib.metadata import version
from pathlib import Path

import tomllib

import HydrologicalTwinAlphaSeries


def _pyproject_version() -> str:
    """Read the canonical version from pyproject.toml."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    return data["project"]["version"]


def test_version_attribute_exists():
    """__version__ must be a non-empty string."""
    assert hasattr(HydrologicalTwinAlphaSeries, "__version__")
    assert isinstance(HydrologicalTwinAlphaSeries.__version__, str)
    assert HydrologicalTwinAlphaSeries.__version__


def test_version_matches_metadata():
    """__version__ must equal importlib.metadata.version()."""
    assert HydrologicalTwinAlphaSeries.__version__ == version("HydrologicalTwinAlphaSeries")


def test_pixi_version_matches_pyproject():
    """pixi.toml version must stay in sync with pyproject.toml."""
    pyproject_ver = _pyproject_version()
    pixi_toml = Path(__file__).resolve().parents[2] / "pixi.toml"
    pixi_data = tomllib.loads(pixi_toml.read_text())
    pixi_ver = pixi_data["workspace"]["version"]
    assert pyproject_ver == pixi_ver, (
        f"Version mismatch: pyproject.toml={pyproject_ver!r} vs pixi.toml={pixi_ver!r}"
    )
