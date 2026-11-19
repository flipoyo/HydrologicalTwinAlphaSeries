"""suggest — "did you mean ...?" for a mistyped ``htas`` command.

Ring: L0. Argparse parses as usual; on its usage error (exit 2) one hint line
is added on stderr. The hint never rewrites arguments and never runs anything.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Iterable, Sequence

_CLOSE_ENOUGH = 0.6


def closest_command(typed: str, known: Iterable[str]) -> str | None:
    matches = difflib.get_close_matches(typed, list(known), n=1, cutoff=_CLOSE_ENOUGH)
    return matches[0] if matches else None


def command_token(argv: Sequence[str]) -> str | None:
    for token in argv:
        if token == "--":
            return None
        if not token.startswith("-"):
            return token
    return None


def suggestion_line(argv: Sequence[str], known: Iterable[str]) -> str | None:
    typed = command_token(argv)
    if typed is None or typed in set(known):
        return None
    guess = closest_command(typed, known)
    return f"htas: did you mean '{guess}'?" if guess else None


def parse_args_with_hint(
    parser: argparse.ArgumentParser, argv: Sequence[str] | None, known: Iterable[str]
) -> argparse.Namespace:
    try:
        return parser.parse_args(argv)
    except SystemExit as request:
        if request.code == 2:
            hint = suggestion_line(sys.argv[1:] if argv is None else argv, known)
            if hint:
                print(hint, file=sys.stderr)
        raise


__all__ = ["closest_command", "command_token", "parse_args_with_hint", "suggestion_line"]
