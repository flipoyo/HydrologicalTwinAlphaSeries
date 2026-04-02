from __future__ import annotations

from types import FunctionType
from typing import Any

PUBLIC_ACCESS_ATTR = "__hydrological_twin_public_access__"
PUBLIC_METHODS_ATTR = "__hydrological_twin_public_methods__"
ACCESS_POLICY_ATTR = "__hydrological_twin_access_policy__"


def _unwrap_descriptor(member: Any) -> FunctionType | None:
    if isinstance(member, (staticmethod, classmethod)):
        member = member.__func__
    if isinstance(member, FunctionType):
        return member
    return None


def public_access(member: Any) -> Any:
    """Mark a method as part of the public facade contract."""
    func = _unwrap_descriptor(member)
    if func is None:
        raise TypeError("@public_access can only be applied to methods.")
    setattr(func, PUBLIC_ACCESS_ATTR, True)
    return member


def private_access(cls: type) -> type:
    """Make a class private-by-default and require explicit public markers."""
    public_methods: list[str] = []
    missing_annotations: list[str] = []

    for name, member in cls.__dict__.items():
        func = _unwrap_descriptor(member)
        if func is None or name.startswith("_"):
            continue
        if getattr(func, PUBLIC_ACCESS_ATTR, False):
            public_methods.append(name)
            continue
        missing_annotations.append(name)

    if missing_annotations:
        missing = ", ".join(sorted(missing_annotations))
        raise TypeError(
            f"{cls.__name__} uses @private_access but has undecorated public methods: {missing}. "
            "Mark public facade methods with @public_access or rename "
            "internal helpers with a leading underscore."
        )

    setattr(cls, ACCESS_POLICY_ATTR, "private_by_default")
    setattr(cls, PUBLIC_METHODS_ATTR, tuple(sorted(public_methods)))
    return cls


def list_public_methods(cls: type) -> tuple[str, ...]:
    """Return the explicitly declared public methods for a private-by-default class."""
    return tuple(getattr(cls, PUBLIC_METHODS_ATTR, ()))
