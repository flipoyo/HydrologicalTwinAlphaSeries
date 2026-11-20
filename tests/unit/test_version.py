"""Verify that the package version is accessible and consistent."""

import importlib.util
import re
import subprocess
import sys
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
    assert tasks["check-build-version"] == "python scripts/check_build_version.py --range"
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


BUMP_SCRIPT = ROOT / ".agent" / ".local" / ".dev" / "scripts" / "bump_version.py"
_SEMVER = re.compile(r"(?<![\d.])\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?(?!\d|\.\d)")
_HISTORICAL = re.compile(r"(?:since|from)\W{0,3}(?:texttt\W{0,2})?$", re.IGNORECASE)


def _bump_script():
    if not BUMP_SCRIPT.is_file():
        pytest.skip("the .dev mount is not present")
    spec = importlib.util.spec_from_file_location("htas_bump_version", BUMP_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _htas_versions(current: str) -> set[str]:
    """The current version and every version a commit subject ever named."""
    versions = {current}
    done = subprocess.run(["git", "log", "--format=%s"], cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode == 0:
        versions |= set(re.findall(r"(?:HydrologicalTwinAlphaSeries|htas)-(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)", done.stdout))
    return versions


def _documents() -> list[Path]:
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "tutorials").glob("*.md"))]
    docs += sorted((ROOT / "docs" / "hydrological_twin").rglob("*.tex"))
    return [path for path in docs if path.is_file()]


def test_version_targets_all_hold_the_current_version():
    """Every file `bump-version` writes states the version in `pixi.toml`."""
    script = _bump_script()
    current = _toml("pixi.toml")["workspace"]["version"]
    for path, pattern in script.TARGETS:
        if not path.is_file():
            pytest.skip(f"{path.relative_to(ROOT)} is not mounted")
        found = pattern.search(path.read_text(encoding="utf-8"))
        assert found, f"{path.relative_to(ROOT)}: the version field is not where bump-version looks"
        assert found.group(2) == current, f"{path.relative_to(ROOT)} states {found.group(2)}, pixi.toml says {current}"


def test_version_mirrors():
    """No document states an HTAS version that `bump-version` does not write.

    A literal equal to the current version or to a version HTAS was released
    as is a copy the bump would leave behind. Only a bump target (written by
    the script) or a historical mention (after "since" or "from") may hold
    one: everything else says `pixi run htas --version`. Other numbers
    (CaWaQS's versions, section numbers) are not HTAS versions and pass.
    """
    script = _bump_script()
    versions = _htas_versions(_toml("pixi.toml")["workspace"]["version"])
    targets = {path: pattern for path, pattern in script.TARGETS}
    stray = []
    for path in _documents():
        text = path.read_text(encoding="utf-8", errors="replace")
        if path in targets:
            text = targets[path].sub(lambda m: m.group(1) + m.group(3), text)
        for found in _SEMVER.finditer(text):
            if found.group(0) not in versions or _HISTORICAL.search(text[max(0, found.start() - 24) : found.start()]):
                continue
            line = text.count("\n", 0, found.start()) + 1
            stray.append(f"{path.relative_to(ROOT)}:{line}: {found.group(0)}")
    assert not stray, "a literal HTAS version outside the bump-version targets (add a target, or point at `pixi run htas --version`):\n" + "\n".join(stray)
