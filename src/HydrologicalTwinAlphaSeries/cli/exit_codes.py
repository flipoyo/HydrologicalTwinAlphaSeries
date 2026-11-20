"""exit_codes — what an ``htas`` exit code means (ComplexGitSync's three codes).

Ring: L0 (CLI adapter). ``0`` the command did what was asked; ``1`` it ran and
the answer is no (a twin in the wrong state); ``2`` it could not run (bad
arguments, a missing or unreadable file, a directory that is not a CaWaQS run).
:func:`exit_code_for` returns ``None`` for anything it does not recognise, so a
programming defect reaches the user as a traceback.
"""

from __future__ import annotations

import tomllib

from ..ht.client import InvalidStateError

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_UNUSABLE = 2


def exit_code_for(exc: BaseException) -> int | None:
    if isinstance(exc, InvalidStateError):
        return EXIT_REFUSED
    if isinstance(exc, (OSError, ValueError, KeyError, tomllib.TOMLDecodeError)):
        # DetectionError and CRS errors are ValueErrors; missing files are OSErrors.
        return EXIT_UNUSABLE
    return None


def diagnostic(exc: BaseException, command: str | None = None, prog: str = "htas") -> str:
    name = f"{prog} {command}" if command else prog
    message = str(exc).strip() or exc.__class__.__name__
    return f"{name}: {message}"


__all__ = ["EXIT_OK", "EXIT_REFUSED", "EXIT_UNUSABLE", "diagnostic", "exit_code_for"]
