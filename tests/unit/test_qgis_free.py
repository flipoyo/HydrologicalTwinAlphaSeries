"""The QGIS-free guard: no module under ``src/`` imports QGIS or PyQt.

HTAS is the backend CaWaQS-ViZ consumes; it runs without QGIS
(``AdditionalSpecs.md`` §5). This guard used to be a ``grep`` in CI; it is
now part of ``pixi run test``, the gate the agent runs before every commit.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "HydrologicalTwinAlphaSeries"
FORBIDDEN = ("qgis", "PyQt", "PyQt5", "PyQt6")


def _imported_modules(path: Path) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
    return modules


def test_no_qgis_or_pyqt_import_under_src():
    offenders = [
        f"{path.relative_to(PKG)}: {module}"
        for path in sorted(PKG.rglob("*.py"))
        for module in _imported_modules(path)
        if module.split(".")[0] in FORBIDDEN
    ]
    assert not offenders, f"QGIS or PyQt imported under src/: {offenders}"
