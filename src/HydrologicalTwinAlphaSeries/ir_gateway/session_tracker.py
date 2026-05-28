"""SessionTracker — enforces the 3-export-per-session limit.

Provides an atomic, server-side export counter keyed by
session_id + user_id + simulation_id + analytical_context_id.
"""

from __future__ import annotations

import threading
from typing import Dict, Tuple

# Session key: (session_id, user_id, simulation_id, analytical_context_id)
SessionKey = Tuple[str, str, str, str]

MAX_EXPORTS_PER_SESSION = 3


class ExportLimitExceeded(Exception):
    """Raised when the per-session export limit is exceeded."""


class SessionTracker:
    """Server-side session export counter.

    Enforces a maximum of 3 spatio-temporal IR exports per session.
    The counter increment is atomic (thread-safe via lock).

    In production, this should be backed by Redis or a database.
    This implementation uses an in-memory store suitable for
    single-process deployments and testing.
    """

    def __init__(self) -> None:
        self._counts: Dict[SessionKey, int] = {}
        self._lock = threading.Lock()

    def check_and_increment(
        self,
        session_id: str,
        user_id: str,
        simulation_id: str,
        analytical_context_id: str,
    ) -> int:
        """Check export count and atomically increment if allowed.

        Returns the new export index (1-based).
        Raises ExportLimitExceeded if the limit would be exceeded.
        """
        key: SessionKey = (session_id, user_id, simulation_id, analytical_context_id)
        with self._lock:
            current = self._counts.get(key, 0)
            if current >= MAX_EXPORTS_PER_SESSION:
                raise ExportLimitExceeded(
                    f"Export limit ({MAX_EXPORTS_PER_SESSION}) exceeded for session"
                )
            self._counts[key] = current + 1
            return current + 1

    def get_count(
        self,
        session_id: str,
        user_id: str,
        simulation_id: str,
        analytical_context_id: str,
    ) -> int:
        """Return current export count for a session (without incrementing)."""
        key: SessionKey = (session_id, user_id, simulation_id, analytical_context_id)
        with self._lock:
            return self._counts.get(key, 0)

    def reset(
        self,
        session_id: str,
        user_id: str,
        simulation_id: str,
        analytical_context_id: str,
    ) -> None:
        """Reset the counter for a session. Intended for testing only."""
        key: SessionKey = (session_id, user_id, simulation_id, analytical_context_id)
        with self._lock:
            self._counts.pop(key, None)
