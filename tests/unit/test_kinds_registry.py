"""The kinds registry (``ht/developer/kinds.py``) and the ladders of ``dispatch.py`` agree."""

import ast
from pathlib import Path

from HydrologicalTwinAlphaSeries.ht.developer import KINDS, REQUESTS, HydrologicalTwin
from HydrologicalTwinAlphaSeries.ht.developer.api_types import MINIMUM_STATE, DescribeRequest

DISPATCH = (
    Path(__file__).resolve().parents[2]
    / "src" / "HydrologicalTwinAlphaSeries" / "ht" / "developer" / "dispatch.py"
)
#: Aliases a ladder accepts for a kind, which the registry does not list.
ALIASES = {"render": {"budget", "regime"}}


def _ladder_kinds() -> dict[str, set[str]]:
    """verb -> the kinds its top-level ``if kind == ...`` / ``elif`` chains test."""
    out: dict[str, set[str]] = {}
    for fn in ast.parse(DISPATCH.read_text()).body:
        if not isinstance(fn, ast.FunctionDef) or fn.name.startswith("_"):
            continue
        found: set[str] = set()
        for node in fn.body:
            while isinstance(node, ast.If):
                cmp = node.test
                if isinstance(cmp, ast.Compare) and isinstance(cmp.comparators[0], ast.Constant):
                    found.add(cmp.comparators[0].value)
                node = node.orelse[0] if node.orelse else None
        out[fn.name] = found
    return out


def test_registry_equals_the_dispatch_ladders():
    ladders = _ladder_kinds()
    for verb, kinds in KINDS.items():
        assert set(kinds) == ladders[verb] - ALIASES.get(verb, set()), verb


def test_registry_verbs_are_facade_verbs_with_a_request():
    assert set(KINDS) == set(REQUESTS)
    assert set(KINDS) <= set(MINIMUM_STATE)
    for verb, request in REQUESTS.items():
        assert callable(getattr(HydrologicalTwin, verb))
        assert request(kind=KINDS[verb][0]).kind == KINDS[verb][0]


def test_describe_catalog_comes_from_the_registry():
    twin = HydrologicalTwin()
    twin._state = twin._state.__class__.LOADED  # a loaded twin with no compartment
    got = twin._build_catalog(DescribeRequest())
    assert got.extract_kinds == list(KINDS["fetch"])
    assert got.mask_kinds == list(KINDS["mask"])
    assert got.transform_kinds == list(KINDS["transform"])
    assert got.assemble_kinds == list(KINDS["assemble"])
    assert got.render_kinds == list(KINDS["render"])
    assert got.export_formats == list(KINDS["export"])
