"""runner — parse, dispatch and map errors to exit codes, for ``htas`` and ``htas-dev``.

Ring: L0. Both command lines run the same way: argparse parses (a typo gets a
hint), the handler runs, and an exception becomes one diagnostic line and the
exit code ``exit_codes`` gives it. Anything unexpected is re-raised.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence

from . import suggest
from .exit_codes import EXIT_OK, EXIT_UNUSABLE, diagnostic, exit_code_for


def run(
    parser: argparse.ArgumentParser, known: Iterable[str], argv: Sequence[str] | None = None
) -> int:
    args = suggest.parse_args_with_hint(parser, argv, known)
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
        print(diagnostic(exc, args.command, parser.prog), file=sys.stderr)
        return code


__all__ = ["run"]
