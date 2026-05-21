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
    """Pixi config in pyproject.toml must stay well-formed and not duplicate [project] metadata."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    pixi = data["tool"]["pixi"]

    workspace = pixi["workspace"]
    # name, version and authors must NOT be duplicated in [tool.pixi.workspace]:
    # pixi inherits them from the standard [project] table.
    assert "name" not in workspace, (
        "Remove 'name' from [tool.pixi.workspace]; it is inherited from [project]"
    )
    assert "version" not in workspace, (
        "Remove 'version' from [tool.pixi.workspace]; it is inherited from [project]"
    )
    assert "authors" not in workspace, (
        "Remove 'authors' from [tool.pixi.workspace]; it is inherited from [project]"
    )
    # pixi-only settings that [project] cannot express:
    assert workspace["channels"] == ["conda-forge"]
    assert workspace["platforms"] == ["linux-64"]

    tasks = pixi["tasks"]
    assert tasks["run"] == "python -m HydrologicalTwinAlphaSeries"
    assert tasks["test"] == "pytest"
    assert tasks["lint"] == "ruff check src tests"
    assert tasks["dev-setup"] == "pre-commit install"

    dependencies = pixi["dependencies"]
    assert dependencies["python"] == "3.11.*"
    assert dependencies["pytest"] == ">=8,<9"
    assert dependencies["ruff"] == ">=0.12,<1"
    assert dependencies["pre-commit"] == ">=3.7"

    assert pixi["pypi-dependencies"]["HydrologicalTwinAlphaSeries"] == {
        "path": ".",
        "editable": True,
    }
