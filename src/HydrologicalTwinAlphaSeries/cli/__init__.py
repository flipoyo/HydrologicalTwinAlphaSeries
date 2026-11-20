"""cli — the ``htas`` command line, the L0 adapter ring above L1 and L2.

Ring: L0. It only collects arguments and prints; every command calls one
:class:`HydrologicalTwinClient` method (the mirror runs one way). ``COMMANDS``
is the one registry: help, the typo hint and the tests all read it.
Run as ``pixi run htas <command> [<subcommand>] [--option …]``.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .. import __build__, __version__
from . import operations, runner, twin

COMMANDS: dict[str, dict[str | None, str]] = {**twin.COMMANDS, **operations.COMMANDS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="htas",
        description="HydrologicalTwinAlphaSeries CLI. Start with 'detect run' on a CaWaQS "
        "OUT_CAW directory, then 'describe', then run an operation. Use 'htas <command> --help' "
        "for examples.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} (build {__build__})")
    subparsers = parser.add_subparsers(dest="command")
    twin.register_parsers(subparsers)
    operations.register_parsers(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return runner.run(build_parser(), COMMANDS, argv)


__all__ = ["COMMANDS", "build_parser", "main"]
