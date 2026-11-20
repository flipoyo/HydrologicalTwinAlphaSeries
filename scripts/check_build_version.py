"""Check that every commit moving ``__build__`` also raises the version.

The rule (``Versioning.md``, *Who bumps what*): every ``bump-build`` is
followed by ``bump-version``, ``patch`` at least, in the same change. Nothing
enforced it. This reads the commits of a range and writes nothing: it
verifies and never decides.

The build counter is ``__build__`` in ``src/HydrologicalTwinAlphaSeries/__init__.py``;
the version is ``[workspace].version`` in ``pixi.toml`` (``__version__`` is
read from the install metadata, so it is not in the source).

Usage::

    python scripts/check_build_version.py --range <base>..<head>

Only the range is judged. Older history predates the rule and rewriting it is
forbidden, so a range is always named explicitly.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

INIT_PATH = "src/HydrologicalTwinAlphaSeries/__init__.py"
PIXI_PATH = "pixi.toml"
_BUILD_RE = re.compile(r'^__build__\s*=\s*"([^"]+)"', re.MULTILINE)


def _git(repo: Path, *args: str) -> str | None:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    return completed.stdout if completed.returncode == 0 else None


def _build(text: str | None) -> str | None:
    found = _BUILD_RE.search(text) if text is not None else None
    return found.group(1) if found else None


def _version(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        return str(tomllib.loads(text)["workspace"]["version"])
    except (tomllib.TOMLDecodeError, KeyError):
        return None


def _semver_key(version: str) -> tuple:
    core, _, pre = version.partition("-")
    numbers = tuple(int(part) for part in core.split(".") if part.isdigit())
    return (numbers, pre == "", pre)


def violations(repo: Path, revision_range: str) -> list[str]:
    """One line per commit in *revision_range* that moves the build without raising the version."""
    commits = (_git(repo, "rev-list", "--reverse", "--no-merges", revision_range) or "").split()
    found: list[str] = []
    for sha in commits:
        before_build = _build(_git(repo, "show", f"{sha}^:{INIT_PATH}"))
        after_build = _build(_git(repo, "show", f"{sha}:{INIT_PATH}"))
        if before_build is None or after_build is None or before_build == after_build:
            continue
        before_version = _version(_git(repo, "show", f"{sha}^:{PIXI_PATH}"))
        after_version = _version(_git(repo, "show", f"{sha}:{PIXI_PATH}"))
        if before_version is None or after_version is None:
            continue
        if _semver_key(after_version) <= _semver_key(before_version):
            found.append(
                f"{sha[:12]}: __build__ {before_build} -> {after_build} but the version "
                f"{before_version} -> {after_version} (a build bump needs bump-version patch at least)"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", required=True, dest="revision_range", help="a git revision range, e.g. origin/main..HEAD")
    args = parser.parse_args(argv)
    found = violations(Path.cwd(), args.revision_range)
    for line in found:
        print(line)
    if found:
        print(f"{len(found)} commit(s) moved the build counter without raising the version", file=sys.stderr)
        return 1
    print("every build bump in the range comes with a version bump")
    return 0


if __name__ == "__main__":
    sys.exit(main())
