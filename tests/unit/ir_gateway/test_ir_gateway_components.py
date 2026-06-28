"""Tests for the IRDocument model and PolicyValidator."""

from __future__ import annotations

import pytest

from HydrologicalTwinAlphaSeries.ir_gateway.ir_document import IRDocument
from HydrologicalTwinAlphaSeries.ir_gateway.policy_validator import (
    PolicyValidator,
    PolicyViolation,
)
from HydrologicalTwinAlphaSeries.ir_gateway.serializer import TOMLSerializer
from HydrologicalTwinAlphaSeries.ir_gateway.session_tracker import (
    ExportLimitExceeded,
    SessionTracker,
)


class TestIRDocument:
    """Tests for IRDocument data model."""

    def test_from_dict_valid(self) -> None:
        raw = {
            "id": {"uuid": "test-uuid"},
            "metadata": {"title": "Test", "description": "", "created_at": "", "author": "X"},
            "provenance": {
                "htas_version": "1.0",
                "git_commit": "abc",
                "simulation_id": "sim1",
                "simulation_hash": "sha256:x",
            },
            "domain": {"domain_id": "d1", "coverage_fraction": 0.5},
            "time": {"aggregation_window": 7, "time_resolution": "weekly"},
            "security": {
                "export_index": 0,
                "max_exports": 3,
                "aggregation_locked": True,
                "reconstruction_resistant": True,
            },
            "audit": {"audit_level": "public", "traceable": True},
            "data": {"indicators": {"x": "y"}, "confidence_envelope": {"low": 0.8}},
        }
        doc = IRDocument.from_dict(raw)
        assert doc.id.uuid == "test-uuid"
        assert doc.domain.coverage_fraction == 0.5
        assert doc.data.indicators == {"x": "y"}

    def test_from_dict_missing_section_raises(self) -> None:
        raw = {"id": {"uuid": "x"}}  # Missing most sections
        with pytest.raises(ValueError, match="Missing required section"):
            IRDocument.from_dict(raw)

    def test_to_dict_roundtrip(self) -> None:
        raw = {
            "id": {"uuid": "roundtrip"},
            "metadata": {"title": "T", "description": "D", "created_at": "now", "author": "A"},
            "provenance": {
                "htas_version": "1.0",
                "git_commit": "abc",
                "simulation_id": "s",
                "simulation_hash": "h",
                "aggregation_policy": "loose_aggregation_v1",
                "confidentiality_policy": "HTAS_IR_v1",
            },
            "domain": {"domain_id": "d", "coverage_fraction": 0.4},
            "time": {"aggregation_window": 10, "time_resolution": "monthly"},
            "security": {
                "export_index": 1,
                "max_exports": 3,
                "aggregation_locked": True,
                "reconstruction_resistant": True,
            },
            "audit": {"audit_level": "public", "traceable": True},
            "data": {"indicators": {"a": "b"}, "confidence_envelope": {"lo": 0.7}},
        }
        doc = IRDocument.from_dict(raw)
        result = doc.to_dict()
        assert result["id"]["uuid"] == "roundtrip"
        assert result["domain"]["coverage_fraction"] == 0.4


class TestPolicyValidator:
    """Tests for PolicyValidator."""

    def _make_valid_doc(self, **overrides) -> IRDocument:
        raw = {
            "id": {"uuid": "valid"},
            "metadata": {"title": "", "description": "", "created_at": "", "author": ""},
            "provenance": {
                "htas_version": "", "git_commit": "",
                "simulation_id": "", "simulation_hash": "",
            },
            "domain": {"domain_id": "d", "coverage_fraction": 0.5},
            "time": {"aggregation_window": 7, "time_resolution": "weekly"},
            "security": {
                "export_index": 0, "max_exports": 3,
                "aggregation_locked": True, "reconstruction_resistant": True,
            },
            "audit": {"audit_level": "public", "traceable": True},
            "data": {"indicators": {}, "confidence_envelope": {}},
        }
        for key, val in overrides.items():
            section, field = key.split(".")
            raw[section][field] = val
        return IRDocument.from_dict(raw)

    def test_valid_document_passes(self) -> None:
        doc = self._make_valid_doc()
        validator = PolicyValidator()
        validator.validate(doc)  # Should not raise

    def test_coverage_too_low(self) -> None:
        doc = self._make_valid_doc(**{"domain.coverage_fraction": 0.1})
        validator = PolicyValidator()
        with pytest.raises(PolicyViolation, match="coverage"):
            validator.validate(doc)

    def test_coverage_too_high(self) -> None:
        doc = self._make_valid_doc(**{"domain.coverage_fraction": 0.9})
        validator = PolicyValidator()
        with pytest.raises(PolicyViolation, match="coverage"):
            validator.validate(doc)

    def test_coverage_at_lower_bound(self) -> None:
        doc = self._make_valid_doc(**{"domain.coverage_fraction": 0.25})
        PolicyValidator().validate(doc)

    def test_coverage_at_upper_bound(self) -> None:
        doc = self._make_valid_doc(**{"domain.coverage_fraction": 0.75})
        PolicyValidator().validate(doc)

    def test_aggregation_window_too_small(self) -> None:
        doc = self._make_valid_doc(**{"time.aggregation_window": 3})
        validator = PolicyValidator()
        with pytest.raises(PolicyViolation, match="Aggregation window"):
            validator.validate(doc)

    def test_max_exports_not_3(self) -> None:
        doc = self._make_valid_doc(**{"security.max_exports": 5})
        validator = PolicyValidator()
        with pytest.raises(PolicyViolation, match="max_exports"):
            validator.validate(doc)

    def test_reconstruction_resistant_false(self) -> None:
        doc = self._make_valid_doc(**{"security.reconstruction_resistant": False})
        validator = PolicyValidator()
        with pytest.raises(PolicyViolation, match="reconstruction_resistant"):
            validator.validate(doc)

    def test_traceable_false(self) -> None:
        doc = self._make_valid_doc(**{"audit.traceable": False})
        validator = PolicyValidator()
        with pytest.raises(PolicyViolation, match="traceable"):
            validator.validate(doc)


class TestTOMLSerializer:
    """Tests for the TOML serializer."""

    def test_serialize_produces_toml(self) -> None:
        raw = {
            "id": {"uuid": "ser-test"},
            "metadata": {"title": "T", "description": "", "created_at": "", "author": ""},
            "provenance": {
                "htas_version": "1.0", "git_commit": "",
                "simulation_id": "", "simulation_hash": "",
            },
            "domain": {"domain_id": "d", "coverage_fraction": 0.5},
            "time": {"aggregation_window": 7, "time_resolution": "weekly"},
            "security": {
                "export_index": 0, "max_exports": 3,
                "aggregation_locked": True, "reconstruction_resistant": True,
            },
            "audit": {"audit_level": "public", "traceable": True},
            "data": {"indicators": {"x": "y"}, "confidence_envelope": {"lo": 0.9}},
        }
        doc = IRDocument.from_dict(raw)
        serializer = TOMLSerializer()
        result = serializer.serialize(doc)

        assert "[id]" in result
        assert 'uuid = "ser-test"' in result
        assert "[metadata]" in result
        assert "[data]" in result

    def test_serialize_rejects_non_ir_document(self) -> None:
        serializer = TOMLSerializer()
        with pytest.raises(TypeError, match="IRDocument"):
            serializer.serialize({"not": "a document"})  # type: ignore[arg-type]


class TestSessionTracker:
    """Tests for the SessionTracker."""

    def test_allows_three_exports(self) -> None:
        tracker = SessionTracker()
        for i in range(3):
            idx = tracker.check_and_increment("s", "u", "sim", "ctx")
            assert idx == i + 1

    def test_fourth_export_raises(self) -> None:
        tracker = SessionTracker()
        for _ in range(3):
            tracker.check_and_increment("s", "u", "sim", "ctx")
        with pytest.raises(ExportLimitExceeded):
            tracker.check_and_increment("s", "u", "sim", "ctx")

    def test_different_keys_independent(self) -> None:
        tracker = SessionTracker()
        for _ in range(3):
            tracker.check_and_increment("s1", "u", "sim", "ctx")
        # Different session should still work
        idx = tracker.check_and_increment("s2", "u", "sim", "ctx")
        assert idx == 1

    def test_get_count(self) -> None:
        tracker = SessionTracker()
        assert tracker.get_count("s", "u", "sim", "ctx") == 0
        tracker.check_and_increment("s", "u", "sim", "ctx")
        assert tracker.get_count("s", "u", "sim", "ctx") == 1

    def test_reset(self) -> None:
        tracker = SessionTracker()
        for _ in range(3):
            tracker.check_and_increment("s", "u", "sim", "ctx")
        tracker.reset("s", "u", "sim", "ctx")
        assert tracker.get_count("s", "u", "sim", "ctx") == 0
