"""Logical data resources attached to Twin Git repositories.

``DataAsset`` describes how a data resource is identified and materialised
inside a Twin Operating Space without coupling HydrologicalTwinAlphaSeries to
DVC, a storage backend, or a particular scientific file format.

The Git repository remains the access and versioning boundary.  ``DataAsset``
only describes the resource carried by that repository; it deliberately does
not contain credentials or user access-control information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class DataAsset:
    """Logical data resource declared by a data Git repository.

    Parameters
    ----------
    name : str
        Stable logical name of the resource inside the repository.
    resolver : str
        Materialisation mechanism.  The value is intentionally open-ended;
        examples are ``"dvc"``, ``"file"`` and ``"http"``.  Supporting a
        resolver does not imply a dependency in the core package.
    target : str
        Relative path at which the resource is expected to appear once the
        Git repository has been materialised into an Operating Space.
    locator : str, optional
        Resolver-specific source reference.  It can be a DVC pointer path, an
        URI, a dataset identifier, or any other opaque locator understood by
        the selected resolver.  It is not the identity of the DataAsset.
    kind : str, optional
        Hydrological semantic category, for example ``"climate"``,
        ``"observation"`` or ``"model-output"``.
    format : str, optional
        Physical format hint (for example ``"netcdf"`` or ``"zarr"``).
        Hydrological Twin orchestration must not use this field as the asset
        identity.
    state : str, optional
        Immutable physical-data state when available (checksum, DVC object
        hash, ETag, provider version, ...).  This complements the Git commit
        that identifies the repository state.
    metadata : mapping, optional
        Extensible scientific metadata such as variables, units, CRS,
        spatial support, or temporal support.

    Notes
    -----
    ``DataAsset`` is deliberately descriptive.  It does not open, query or
    download data.  Format-specific and transport-specific code belongs in
    optional resolver/adapter layers so the domain model remains dependency
    free.
    """

    name: str
    resolver: str
    target: str
    locator: str | None = None
    kind: str | None = None
    format: str | None = None
    state: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    PROTOCOL = "htdata-1"

    def __post_init__(self) -> None:
        for field_name in ("name", "resolver", "target"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

        target = PurePosixPath(self.target)
        if target.is_absolute() or ".." in target.parts:
            raise ValueError("target must be a relative path inside the GitRepo")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def materialized_path(self, repo_root: str | Path) -> Path:
        """Return the expected local path of the materialised resource."""
        return Path(repo_root).joinpath(*PurePosixPath(self.target).parts)

    def to_mapping(self) -> dict[str, Any]:
        """Return a serialisable representation suitable for TOML/JSON metadata."""
        data: dict[str, Any] = {
            "name": self.name,
            "resolver": self.resolver,
            "target": self.target,
        }
        for key in ("locator", "kind", "format", "state"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DataAsset":
        """Build an asset from repository metadata.

        Unknown fields are rejected so a malformed or newer manifest does not
        silently alter the meaning of an Operating Space.
        """
        known = {
            "name",
            "resolver",
            "target",
            "locator",
            "kind",
            "format",
            "state",
            "metadata",
        }
        unexpected = set(data) - known
        if unexpected:
            fields = ", ".join(sorted(unexpected))
            raise ValueError(f"unexpected DataAsset fields: {fields}")

        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        try:
            name = data["name"]
            resolver = data["resolver"]
            target = data["target"]
        except KeyError as exc:
            raise ValueError(f"missing required DataAsset field: {exc.args[0]}") from exc

        return cls(
            name=name,
            resolver=resolver,
            target=target,
            locator=data.get("locator"),
            kind=data.get("kind"),
            format=data.get("format"),
            state=data.get("state"),
            metadata=metadata,
        )
