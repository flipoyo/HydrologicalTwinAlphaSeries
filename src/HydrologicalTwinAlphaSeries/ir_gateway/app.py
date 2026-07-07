"""WSGI application for the HTAS IR Gateway API.

Implements:
    GET /api/v1/ir/{document_type}/{document_id}

All other methods and paths are rejected.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from HydrologicalTwinAlphaSeries.ir_gateway.ir_store import (
    DocumentNotFound,
    InvalidDocumentType,
    IRStore,
)
from HydrologicalTwinAlphaSeries.ir_gateway.policy_validator import (
    PolicyValidator,
    PolicyViolation,
)
from HydrologicalTwinAlphaSeries.ir_gateway.serializer import TOMLSerializer
from HydrologicalTwinAlphaSeries.ir_gateway.session_tracker import (
    ExportLimitExceeded,
    SessionTracker,
)

# Type aliases for WSGI
StartResponse = Callable[[str, List[Tuple[str, str]]], Any]
WSGIEnviron = Dict[str, Any]

# Route pattern for the IR endpoint
_IR_ROUTE = re.compile(r"^/api/v1/ir/([^/]+)/([^/]+)$")

# Forbidden path prefixes
_FORBIDDEN_PREFIXES = (
    "/api/v1/raw/",
    "/api/v1/numpy/",
    "/api/v1/xarray/",
    "/api/v1/mesh/",
    "/api/v1/state/",
    "/api/v1/tensor/",
    "/api/v1/export/csv",
    "/api/v1/export/json",
    "/api/v1/export/netcdf",
)


def _json_error(status: str, message: str) -> Tuple[str, bytes]:
    """Create a JSON error response body."""
    body = json.dumps({"error": message}).encode("utf-8")
    return status, body


class IRGatewayApp:
    """WSGI application implementing the HTAS IR read-only API gateway.

    This application serves only pre-validated HTAS IR documents as TOML
    manifests. It enforces policy validation, session export limits, and
    rejects all non-GET requests and forbidden endpoints.
    """

    def __init__(
        self,
        store_path: Path,
        session_tracker: Optional[SessionTracker] = None,
    ) -> None:
        self._store = IRStore(store_path)
        self._tracker = session_tracker or SessionTracker()
        self._validator = PolicyValidator()
        self._serializer = TOMLSerializer()

    @property
    def session_tracker(self) -> SessionTracker:
        """Expose session tracker for testing."""
        return self._tracker

    def __call__(
        self, environ: WSGIEnviron, start_response: StartResponse
    ) -> Iterable[bytes]:
        """WSGI entry point."""
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")

        # Only GET is allowed
        if method != "GET":
            status, body = _json_error("405 Method Not Allowed", "Only GET is allowed")
            start_response(status, [
                ("Content-Type", "application/json"),
                ("Allow", "GET"),
            ])
            return [body]

        # Check forbidden paths
        for prefix in _FORBIDDEN_PREFIXES:
            if path.startswith(prefix):
                status, body = _json_error("403 Forbidden", "Endpoint not available")
                start_response(status, [("Content-Type", "application/json")])
                return [body]

        # Match IR route
        match = _IR_ROUTE.match(path)
        if not match:
            status, body = _json_error("404 Not Found", "Unknown endpoint")
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        document_type = match.group(1)
        document_id = match.group(2)

        return self._handle_ir_request(
            environ, start_response, document_type, document_id
        )

    def _handle_ir_request(
        self,
        environ: WSGIEnviron,
        start_response: StartResponse,
        document_type: str,
        document_id: str,
    ) -> Iterable[bytes]:
        """Handle a validated IR document request."""
        # Extract session info from headers
        session_id = environ.get("HTTP_X_SESSION_ID", "default")
        user_id = environ.get("HTTP_X_USER_ID", "anonymous")
        simulation_id = environ.get("HTTP_X_SIMULATION_ID", "default")
        analytical_context_id = environ.get("HTTP_X_ANALYTICAL_CONTEXT_ID", "default")

        # Check session export limit (before document lookup to fail fast)
        # But per spec, failed lookup must NOT consume a slot, so we check
        # the limit here but only increment after successful validation.
        current_count = self._tracker.get_count(
            session_id, user_id, simulation_id, analytical_context_id
        )
        if current_count >= 3:
            status, body = _json_error(
                "429 Too Many Requests", "Session export limit exceeded"
            )
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        # Lookup document in IR store
        try:
            document = self._store.get_document(document_type, document_id)
        except InvalidDocumentType:
            status, body = _json_error("403 Forbidden", "Invalid document type")
            start_response(status, [("Content-Type", "application/json")])
            return [body]
        except DocumentNotFound:
            status, body = _json_error("404 Not Found", "Document not found")
            start_response(status, [("Content-Type", "application/json")])
            return [body]
        except ValueError:
            status, body = _json_error(
                "500 Internal Server Error", "Document processing error"
            )
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        # Policy validation
        try:
            self._validator.validate(document)
        except PolicyViolation:
            status, body = _json_error("403 Forbidden", "Policy violation")
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        # Serialize to TOML
        try:
            toml_content = self._serializer.serialize(document)
        except Exception:
            status, body = _json_error(
                "500 Internal Server Error", "Serialization error"
            )
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        # Atomic export counter increment (only after all validation passes)
        try:
            self._tracker.check_and_increment(
                session_id, user_id, simulation_id, analytical_context_id
            )
        except ExportLimitExceeded:
            status, body = _json_error(
                "429 Too Many Requests", "Session export limit exceeded"
            )
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        # Success — return TOML
        body = toml_content.encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/toml"),
            ("Content-Disposition", f'inline; filename="{document_id}.toml"'),
        ])
        return [body]


def create_app(store_path: Optional[Path] = None) -> IRGatewayApp:
    """Factory function to create the IR Gateway WSGI application.

    Args:
        store_path: Path to the IR document store directory.
                   Defaults to ./ir_store relative to cwd.
    """
    if store_path is None:
        store_path = Path.cwd() / "ir_store"
    return IRGatewayApp(store_path=store_path)
