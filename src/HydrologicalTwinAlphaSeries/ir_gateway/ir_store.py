"""IRStore — file-based store for pre-validated HTAS IR TOML documents.

The store serves only pre-validated documents. It does not generate
scientific data on demand.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from HydrologicalTwinAlphaSeries.ir_gateway.ir_document import IRDocument

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

# Allowed document types matching the IR store directory structure
ALLOWED_DOCUMENT_TYPES = frozenset({
    "spatial_map",
    "time_series",
    "compare_sim_obs",
    "indicator_set",
    "scenario_comparison",
})


class DocumentNotFound(Exception):
    """Raised when a requested IR document does not exist."""


class InvalidDocumentType(Exception):
    """Raised when an invalid or forbidden document type is requested."""


class IRStore:
    """File-based store for pre-validated HTAS IR TOML documents.

    Structure:
        ir_store/
        ├── spatial_map/{document_id}.toml
        ├── time_series/{document_id}.toml
        ├── compare_sim_obs/{document_id}.toml
        ├── indicator_set/{document_id}.toml
        └── scenario_comparison/{document_id}.toml
    """

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path

    @property
    def store_path(self) -> Path:
        return self._store_path

    def get_document(self, document_type: str, document_id: str) -> IRDocument:
        """Retrieve and parse a pre-validated IR document from the store.

        Raises:
            InvalidDocumentType: if document_type is not allowed.
            DocumentNotFound: if the TOML file does not exist.
            ValueError: if the TOML content is malformed.
        """
        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise InvalidDocumentType(
                f"Invalid document type: {document_type!r}"
            )

        # Sanitize document_id to prevent path traversal
        safe_id = self._sanitize_id(document_id)
        if safe_id is None:
            raise DocumentNotFound(f"Document not found: {document_id}")

        file_path = self._store_path / document_type / f"{safe_id}.toml"
        if not file_path.is_file():
            raise DocumentNotFound(
                f"Document not found: {document_type}/{document_id}"
            )

        try:
            content = file_path.read_bytes()
            raw = tomllib.loads(content.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Failed to parse TOML document: {exc}") from exc

        return IRDocument.from_dict(raw)

    @staticmethod
    def _sanitize_id(document_id: str) -> Optional[str]:
        """Sanitize document_id to prevent path traversal attacks."""
        # Reject empty, path separators, parent references
        if not document_id:
            return None
        if "/" in document_id or "\\" in document_id:
            return None
        if ".." in document_id:
            return None
        if document_id.startswith("."):
            return None
        return document_id
