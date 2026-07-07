"""Tests for the HTAS IR Gateway — integration tests for the WSGI app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from HydrologicalTwinAlphaSeries.ir_gateway.app import IRGatewayApp
from HydrologicalTwinAlphaSeries.ir_gateway.session_tracker import SessionTracker

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

VALID_TOML = """\
[id]
uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

[metadata]
title = "Basin Drought Indicator Q2 2026"
description = "Aggregated drought tendency for the Loire basin."
created_at = "2026-05-28T12:00:00Z"
author = "HTAS System"

[provenance]
htas_version = "2.1.0"
git_commit = "f4e8a9c"
simulation_id = "sim_2026_loire_v4"
simulation_hash = "sha256:9d8f1234"
aggregation_policy = "loose_aggregation_v1"
confidentiality_policy = "HTAS_IR_v1"

[domain]
domain_id = "loire_basin"
coverage_fraction = 0.45

[time]
aggregation_window = 7
time_resolution = "weekly"

[security]
export_index = 1
max_exports = 3
aggregation_locked = true
reconstruction_resistant = true

[audit]
audit_level = "public"
traceable = true

[data]
indicators = { drought_tendency = "high", recharge_deficit = "moderate" }
confidence_envelope = { lower = 0.82, upper = 0.94 }
"""

LOW_COVERAGE_TOML = """\
[id]
uuid = "low-coverage-doc"

[metadata]
title = "Low coverage"
description = ""
created_at = "2026-01-01T00:00:00Z"
author = "HTAS System"

[provenance]
htas_version = "2.1.0"
git_commit = "abc"
simulation_id = "sim1"
simulation_hash = "sha256:xxx"
aggregation_policy = "loose_aggregation_v1"
confidentiality_policy = "HTAS_IR_v1"

[domain]
domain_id = "test"
coverage_fraction = 0.10

[time]
aggregation_window = 7
time_resolution = "weekly"

[security]
export_index = 0
max_exports = 3
aggregation_locked = true
reconstruction_resistant = true

[audit]
audit_level = "public"
traceable = true

[data]
indicators = {}
confidence_envelope = {}
"""

HIGH_COVERAGE_TOML = """\
[id]
uuid = "high-coverage-doc"

[metadata]
title = "High coverage"
description = ""
created_at = "2026-01-01T00:00:00Z"
author = "HTAS System"

[provenance]
htas_version = "2.1.0"
git_commit = "abc"
simulation_id = "sim1"
simulation_hash = "sha256:xxx"
aggregation_policy = "loose_aggregation_v1"
confidentiality_policy = "HTAS_IR_v1"

[domain]
domain_id = "test"
coverage_fraction = 0.90

[time]
aggregation_window = 7
time_resolution = "weekly"

[security]
export_index = 0
max_exports = 3
aggregation_locked = true
reconstruction_resistant = true

[audit]
audit_level = "public"
traceable = true

[data]
indicators = {}
confidence_envelope = {}
"""

LOW_AGGREGATION_TOML = """\
[id]
uuid = "low-agg-doc"

[metadata]
title = "Low aggregation"
description = ""
created_at = "2026-01-01T00:00:00Z"
author = "HTAS System"

[provenance]
htas_version = "2.1.0"
git_commit = "abc"
simulation_id = "sim1"
simulation_hash = "sha256:xxx"
aggregation_policy = "loose_aggregation_v1"
confidentiality_policy = "HTAS_IR_v1"

[domain]
domain_id = "test"
coverage_fraction = 0.50

[time]
aggregation_window = 3
time_resolution = "daily"

[security]
export_index = 0
max_exports = 3
aggregation_locked = true
reconstruction_resistant = true

[audit]
audit_level = "public"
traceable = true

[data]
indicators = {}
confidence_envelope = {}
"""

FORBIDDEN_KEY_TOML = """\
[id]
uuid = "forbidden-key-doc"

[metadata]
title = "Forbidden key"
description = ""
created_at = "2026-01-01T00:00:00Z"
author = "HTAS System"

[provenance]
htas_version = "2.1.0"
git_commit = "abc"
simulation_id = "sim1"
simulation_hash = "sha256:xxx"
aggregation_policy = "loose_aggregation_v1"
confidentiality_policy = "HTAS_IR_v1"

[domain]
domain_id = "test"
coverage_fraction = 0.50

[time]
aggregation_window = 7
time_resolution = "weekly"

[security]
export_index = 0
max_exports = 3
aggregation_locked = true
reconstruction_resistant = true

[audit]
audit_level = "public"
traceable = true

[data]
indicators = { numpy = "violation" }
confidence_envelope = {}
"""


def _create_store(tmp_path: Path, docs: Dict[str, Dict[str, str]]) -> Path:
    """Create a temporary IR store with the given documents.

    Args:
        tmp_path: Base temporary directory.
        docs: Mapping of document_type -> {document_id: toml_content}
    """
    store_path = tmp_path / "ir_store"
    for doc_type, files in docs.items():
        type_dir = store_path / doc_type
        type_dir.mkdir(parents=True, exist_ok=True)
        for doc_id, content in files.items():
            (type_dir / f"{doc_id}.toml").write_text(content)
    return store_path


class MockWSGIResponse:
    """Captures WSGI start_response output."""

    def __init__(self) -> None:
        self.status: str = ""
        self.headers: List[Tuple[str, str]] = []

    def start_response(self, status: str, headers: List[Tuple[str, str]]) -> None:
        self.status = status
        self.headers = headers

    def get_header(self, name: str) -> Optional[str]:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return None


def _make_environ(
    path: str,
    method: str = "GET",
    session_id: str = "sess1",
    user_id: str = "user1",
    simulation_id: str = "sim1",
    analytical_context_id: str = "ctx1",
) -> Dict[str, Any]:
    """Create a minimal WSGI environ dict."""
    return {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "HTTP_X_SESSION_ID": session_id,
        "HTTP_X_USER_ID": user_id,
        "HTTP_X_SIMULATION_ID": simulation_id,
        "HTTP_X_ANALYTICAL_CONTEXT_ID": analytical_context_id,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIRGatewaySuccess:
    """Test successful TOML retrieval."""

    def test_valid_toml_returns_200(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"doc1": VALID_TOML},
        })
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/doc1")

        body_parts = app(environ, resp.start_response)
        body = b"".join(body_parts).decode("utf-8")

        assert resp.status == "200 OK"
        assert resp.get_header("Content-Type") == "application/toml"
        assert resp.get_header("Content-Disposition") == 'inline; filename="doc1.toml"'
        assert "[id]" in body
        assert "[metadata]" in body
        assert "drought_tendency" in body

    def test_response_contains_no_raw_data(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"doc1": VALID_TOML},
        })
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/doc1")

        body_parts = app(environ, resp.start_response)
        body = b"".join(body_parts).decode("utf-8")

        # Must not contain raw/binary/numpy/xarray data markers
        for forbidden in ["numpy", "ndarray", "xarray", "binary_blob", "solver_state"]:
            assert forbidden not in body.lower()


class TestIRGateway404:
    """Test 404 responses."""

    def test_missing_document_returns_404(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {"indicator_set": {}})
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/nonexistent")

        app(environ, resp.start_response)

        assert "404" in resp.status

    def test_unknown_path_returns_404(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {})
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/unknown")

        app(environ, resp.start_response)

        assert "404" in resp.status


class TestIRGateway429:
    """Test 429 session export limit."""

    def test_fourth_export_returns_429(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"doc1": VALID_TOML},
        })
        tracker = SessionTracker()
        app = IRGatewayApp(store_path=store_path, session_tracker=tracker)

        # First 3 exports should succeed
        for i in range(3):
            resp = MockWSGIResponse()
            environ = _make_environ("/api/v1/ir/indicator_set/doc1")
            app(environ, resp.start_response)
            assert resp.status == "200 OK", f"Export {i+1} should succeed"

        # Fourth export should return 429
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/doc1")
        app(environ, resp.start_response)

        assert "429" in resp.status

    def test_different_sessions_have_independent_limits(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"doc1": VALID_TOML},
        })
        tracker = SessionTracker()
        app = IRGatewayApp(store_path=store_path, session_tracker=tracker)

        # Exhaust session 1
        for _ in range(3):
            resp = MockWSGIResponse()
            environ = _make_environ(
                "/api/v1/ir/indicator_set/doc1", session_id="sess1"
            )
            app(environ, resp.start_response)

        # Session 2 should still work
        resp = MockWSGIResponse()
        environ = _make_environ(
            "/api/v1/ir/indicator_set/doc1", session_id="sess2"
        )
        app(environ, resp.start_response)
        assert resp.status == "200 OK"


class TestIRGateway403:
    """Test 403 policy violation responses."""

    def test_low_coverage_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"low_cov": LOW_COVERAGE_TOML},
        })
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/low_cov")

        app(environ, resp.start_response)

        assert "403" in resp.status

    def test_high_coverage_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"high_cov": HIGH_COVERAGE_TOML},
        })
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/high_cov")

        app(environ, resp.start_response)

        assert "403" in resp.status

    def test_low_aggregation_window_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"low_agg": LOW_AGGREGATION_TOML},
        })
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/low_agg")

        app(environ, resp.start_response)

        assert "403" in resp.status

    def test_forbidden_key_in_data_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"forbidden": FORBIDDEN_KEY_TOML},
        })
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/forbidden")

        app(environ, resp.start_response)

        assert "403" in resp.status

    def test_invalid_document_type_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {})
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/raw_data/doc1")

        app(environ, resp.start_response)

        assert "403" in resp.status

    def test_forbidden_endpoint_raw_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {})
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/raw/something")

        app(environ, resp.start_response)

        assert "403" in resp.status

    def test_forbidden_endpoint_numpy_returns_403(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {})
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/numpy/something")

        app(environ, resp.start_response)

        assert "403" in resp.status


class TestIRGateway500:
    """Test 500 internal server error responses."""

    def test_invalid_toml_returns_500(self, tmp_path: Path) -> None:
        store_path = tmp_path / "ir_store"
        type_dir = store_path / "indicator_set"
        type_dir.mkdir(parents=True)
        (type_dir / "bad.toml").write_text("this is not [valid toml = ")

        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/bad")

        app(environ, resp.start_response)

        assert "500" in resp.status


class TestIRGatewayMethodRestrictions:
    """Test that only GET is allowed."""

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_non_get_methods_rejected(self, tmp_path: Path, method: str) -> None:
        store_path = _create_store(tmp_path, {})
        app = IRGatewayApp(store_path=store_path)
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/doc1", method=method)

        app(environ, resp.start_response)

        assert "405" in resp.status


class TestIRGatewayExportSlotNotConsumedOnError:
    """Test that failed lookups do not consume export slots."""

    def test_404_does_not_consume_export_slot(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {"doc1": VALID_TOML},
        })
        tracker = SessionTracker()
        app = IRGatewayApp(store_path=store_path, session_tracker=tracker)

        # 404 should not consume a slot
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/nonexistent")
        app(environ, resp.start_response)
        assert "404" in resp.status

        # Should still have 3 exports available
        for i in range(3):
            resp = MockWSGIResponse()
            environ = _make_environ("/api/v1/ir/indicator_set/doc1")
            app(environ, resp.start_response)
            assert resp.status == "200 OK", f"Export {i+1} should still succeed"

    def test_403_does_not_consume_export_slot(self, tmp_path: Path) -> None:
        store_path = _create_store(tmp_path, {
            "indicator_set": {
                "low_cov": LOW_COVERAGE_TOML,
                "doc1": VALID_TOML,
            },
        })
        tracker = SessionTracker()
        app = IRGatewayApp(store_path=store_path, session_tracker=tracker)

        # 403 should not consume a slot
        resp = MockWSGIResponse()
        environ = _make_environ("/api/v1/ir/indicator_set/low_cov")
        app(environ, resp.start_response)
        assert "403" in resp.status

        # Should still have 3 exports available
        for i in range(3):
            resp = MockWSGIResponse()
            environ = _make_environ("/api/v1/ir/indicator_set/doc1")
            app(environ, resp.start_response)
            assert resp.status == "200 OK", f"Export {i+1} should still succeed"
