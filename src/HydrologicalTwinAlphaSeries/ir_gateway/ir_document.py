"""IRDocument — strict schema for HTAS IR TOML manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class IRDocumentId:
    """The [id] section of an IR document."""

    uuid: str = ""


@dataclass
class IRDocumentMetadata:
    """The [metadata] section of an IR document."""

    title: str = ""
    description: str = ""
    created_at: str = ""
    author: str = "HTAS System"


@dataclass
class IRDocumentProvenance:
    """The [provenance] section of an IR document."""

    htas_version: str = ""
    git_commit: str = ""
    simulation_id: str = ""
    simulation_hash: str = ""
    aggregation_policy: str = "loose_aggregation_v1"
    confidentiality_policy: str = "HTAS_IR_v1"


@dataclass
class IRDocumentDomain:
    """The [domain] section of an IR document."""

    domain_id: str = ""
    coverage_fraction: float = 0.5


@dataclass
class IRDocumentTime:
    """The [time] section of an IR document."""

    aggregation_window: int = 7
    time_resolution: str = "weekly"


@dataclass
class IRDocumentSecurity:
    """The [security] section of an IR document."""

    export_index: int = 0
    max_exports: int = 3
    aggregation_locked: bool = True
    reconstruction_resistant: bool = True


@dataclass
class IRDocumentAudit:
    """The [audit] section of an IR document."""

    audit_level: str = "public"
    traceable: bool = True


@dataclass
class IRDocumentData:
    """The [data] section of an IR document."""

    indicators: Dict[str, str] = field(default_factory=dict)
    confidence_envelope: Dict[str, float] = field(default_factory=dict)


@dataclass
class IRDocument:
    """Strict schema for a validated HTAS IR TOML manifest.

    All required sections must be present for a document to be valid.
    """

    id: IRDocumentId = field(default_factory=IRDocumentId)
    metadata: IRDocumentMetadata = field(default_factory=IRDocumentMetadata)
    provenance: IRDocumentProvenance = field(default_factory=IRDocumentProvenance)
    domain: IRDocumentDomain = field(default_factory=IRDocumentDomain)
    time: IRDocumentTime = field(default_factory=IRDocumentTime)
    security: IRDocumentSecurity = field(default_factory=IRDocumentSecurity)
    audit: IRDocumentAudit = field(default_factory=IRDocumentAudit)
    data: IRDocumentData = field(default_factory=IRDocumentData)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "IRDocument":
        """Construct an IRDocument from a parsed TOML dictionary.

        Raises ValueError if required sections are missing.
        """
        required_sections = [
            "id", "metadata", "provenance", "domain",
            "time", "security", "audit", "data",
        ]
        for section in required_sections:
            if section not in raw:
                raise ValueError(f"Missing required section: [{section}]")

        doc = cls(
            id=IRDocumentId(**{k: v for k, v in raw["id"].items() if k in ("uuid",)}),
            metadata=IRDocumentMetadata(
                title=raw["metadata"].get("title", ""),
                description=raw["metadata"].get("description", ""),
                created_at=raw["metadata"].get("created_at", ""),
                author=raw["metadata"].get("author", "HTAS System"),
            ),
            provenance=IRDocumentProvenance(
                htas_version=raw["provenance"].get("htas_version", ""),
                git_commit=raw["provenance"].get("git_commit", ""),
                simulation_id=raw["provenance"].get("simulation_id", ""),
                simulation_hash=raw["provenance"].get("simulation_hash", ""),
                aggregation_policy=raw["provenance"].get(
                    "aggregation_policy", "loose_aggregation_v1"
                ),
                confidentiality_policy=raw["provenance"].get(
                    "confidentiality_policy", "HTAS_IR_v1"
                ),
            ),
            domain=IRDocumentDomain(
                domain_id=raw["domain"].get("domain_id", ""),
                coverage_fraction=float(raw["domain"].get("coverage_fraction", 0.5)),
            ),
            time=IRDocumentTime(
                aggregation_window=int(raw["time"].get("aggregation_window", 7)),
                time_resolution=raw["time"].get("time_resolution", "weekly"),
            ),
            security=IRDocumentSecurity(
                export_index=int(raw["security"].get("export_index", 0)),
                max_exports=int(raw["security"].get("max_exports", 3)),
                aggregation_locked=bool(raw["security"].get("aggregation_locked", True)),
                reconstruction_resistant=bool(
                    raw["security"].get("reconstruction_resistant", True)
                ),
            ),
            audit=IRDocumentAudit(
                audit_level=raw["audit"].get("audit_level", "public"),
                traceable=bool(raw["audit"].get("traceable", True)),
            ),
            data=IRDocumentData(
                indicators=dict(raw["data"].get("indicators", {})),
                confidence_envelope={
                    k: float(v)
                    for k, v in raw["data"].get("confidence_envelope", {}).items()
                },
            ),
        )
        return doc

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the document to a dictionary suitable for TOML output."""
        return {
            "id": {"uuid": self.id.uuid},
            "metadata": {
                "title": self.metadata.title,
                "description": self.metadata.description,
                "created_at": self.metadata.created_at,
                "author": self.metadata.author,
            },
            "provenance": {
                "htas_version": self.provenance.htas_version,
                "git_commit": self.provenance.git_commit,
                "simulation_id": self.provenance.simulation_id,
                "simulation_hash": self.provenance.simulation_hash,
                "aggregation_policy": self.provenance.aggregation_policy,
                "confidentiality_policy": self.provenance.confidentiality_policy,
            },
            "domain": {
                "domain_id": self.domain.domain_id,
                "coverage_fraction": self.domain.coverage_fraction,
            },
            "time": {
                "aggregation_window": self.time.aggregation_window,
                "time_resolution": self.time.time_resolution,
            },
            "security": {
                "export_index": self.security.export_index,
                "max_exports": self.security.max_exports,
                "aggregation_locked": self.security.aggregation_locked,
                "reconstruction_resistant": self.security.reconstruction_resistant,
            },
            "audit": {
                "audit_level": self.audit.audit_level,
                "traceable": self.audit.traceable,
            },
            "data": {
                "indicators": self.data.indicators,
                "confidence_envelope": self.data.confidence_envelope,
            },
        }
