"""The user guide names every command and every option of ``htas`` and ``htas-dev``.

The guide is the command reference. A command, a subcommand, an option or a
kind that the parsers have and ``HTAS_user_guide.tex`` does not name fails here.
"""

import argparse
from pathlib import Path

import pytest

from HydrologicalTwinAlphaSeries.cli import COMMANDS, build_parser, dev
from HydrologicalTwinAlphaSeries.ht.developer import KINDS

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "hydrological_twin" / "HTAS_user_guide.tex"


@pytest.fixture(scope="module")
def guide() -> str:
    if not GUIDE.is_file():
        pytest.skip("docs/hydrological_twin is not checked out")
    return GUIDE.read_text().replace("\\_", "_")


def _children(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def test_guide_names_every_htas_command_and_subcommand(guide):
    for command, subs in COMMANDS.items():
        for sub in subs:
            assert f"htas {command} {sub}" in guide if sub else f"htas {command}" in guide, (command, sub)


def test_guide_names_every_htas_option(guide):
    missing = []
    for command, group in _children(build_parser()).items():
        for sub, parser in (_children(group) or {None: group}).items():
            for action in parser._actions:
                for flag in action.option_strings:
                    if flag.startswith("--") and flag not in guide and flag != "--help":
                        missing.append((command, sub, flag))
    assert not missing, missing


def test_guide_names_every_htas_dev_verb_and_kind(guide):
    for verb, kinds in KINDS.items():
        assert f"htas-dev {verb}" in guide, verb
        for kind in kinds:
            assert kind.replace("_", "-") in guide, (verb, kind)
    assert set(dev.COMMANDS) == set(KINDS)
