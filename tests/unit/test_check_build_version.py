"""scripts/check_build_version.py fails on a commit that moves __build__ and not the version."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("htas_check_build_version", ROOT / "scripts" / "check_build_version.py")
check = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check
_spec.loader.exec_module(check)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, build: str, version: str) -> None:
    init = repo / check.INIT_PATH
    init.parent.mkdir(parents=True, exist_ok=True)
    init.write_text(f'__build__ = "{build}"\n')
    (repo / check.PIXI_PATH).write_text(f'[workspace]\nversion = "{version}"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"{build} {version}")


def test_build_bump_without_version_bump_is_reported(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "2026.01", "1.0.0")
    _commit(tmp_path, "2026.02", "1.0.0")
    assert len(check.violations(tmp_path, "HEAD~1..HEAD")) == 1


def test_build_bump_with_version_bump_passes(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "2026.01", "1.0.0")
    _commit(tmp_path, "2026.02", "1.0.1")
    assert check.violations(tmp_path, "HEAD~1..HEAD") == []
