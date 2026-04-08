from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Dict


class HTPersistenceMixin:
    """Basic pickle-based persistence for HydrologicalTwin.

    HydrologicalTwin should inherit from this mixin to support:

    - `.to_pickle(path)` : store a snapshot on disk
    - `.from_pickle(path)` : recover an instance

    This enables a simple "bancarisation" system and fast re-instantiation.
    """

    def to_pickle(self, path: str | Path) -> None:
        path = Path(path)
        payload: Dict[str, Any] = {
            "schema_version": "0.1.0",
            "class": self.__class__.__name__,
            "data": self,
        }
        with path.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def from_pickle(cls, path: str | Path):
        path = Path(path)
        with path.open("rb") as f:
            payload = pickle.load(f)
        obj = payload["data"]
        if not isinstance(obj, cls):
            raise TypeError(
                f"Expected {cls.__name__} in pickle, got {type(obj).__name__}"
            )
        return obj
