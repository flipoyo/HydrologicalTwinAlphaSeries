"""cli — the ``htas`` command line, the L0 adapter ring above L1 and L2.

Ring: L0. It only collects arguments and prints; every command calls one
:class:`HydrologicalTwinClient` method (the mirror runs one way). ``COMMANDS``
is the one registry: help, the typo hint and the tests all read it.
Run as ``pixi run htas <command> [<subcommand>] [--option …]``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .. import __build__, __version__
from . import operations, suggest, twin
from .exit_codes import EXIT_OK, EXIT_UNUSABLE, diagnostic, exit_code_for

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
    parser = build_parser()
    args = suggest.parse_args_with_hint(parser, argv, COMMANDS)
    handler = getattr(args, "handler", None)
    if handler is None:
        # No command: show help and succeed. A command without its subcommand
        # refuses, listing the subcommands.
        (getattr(args, "parser", None) or parser).print_help()
        return EXIT_OK if args.command is None else EXIT_UNUSABLE
    try:
        return handler(args)
    except Exception as exc:  # noqa: BLE001 - mapped below, re-raised if unexpected
        code = exit_code_for(exc)
        if code is None:
            raise
        print(diagnostic(exc, args.command), file=sys.stderr)
        return code


__all__ = ["COMMANDS", "build_parser", "main"]
