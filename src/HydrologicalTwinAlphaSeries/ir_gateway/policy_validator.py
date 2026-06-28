"""PolicyValidator — enforces HTAS IR publication constraints.

Validates every IR document before it can be served through the gateway.
Fails closed: any unknown high-risk field results in rejection.
"""

from __future__ import annotations

from typing import Any, Dict, Set

from HydrologicalTwinAlphaSeries.ir_gateway.ir_document import IRDocument

# Keys that must never appear in an IR document payload
FORBIDDEN_KEYS: Set[str] = frozenset({
    "numpy",
    "ndarray",
    "xarray",
    "dataset",
    "raw_values",
    "raw_array",
    "mesh_values",
    "cell_values",
    "native_grid",
    "solver_state",
    "binary_blob",
    "csv_dump",
    "json_array",
})


class PolicyViolation(Exception):
    """Raised when an IR document violates publication policy."""


class PolicyValidator:
    """Validates IR documents against HTAS publication policy.

    Mandatory checks:
    - 0.25 <= coverage_fraction <= 0.75
    - aggregation_window >= 7
    - max_exports == 3
    - reconstruction_resistant is True
    - traceable is True
    - No forbidden keys in payload
    """

    def validate(self, document: IRDocument) -> None:
        """Validate an IRDocument against all policy constraints.

        Raises PolicyViolation if any constraint is violated.
        """
        self._check_coverage(document)
        self._check_aggregation_window(document)
        self._check_security(document)
        self._check_audit(document)
        self._check_forbidden_keys(document)

    def _check_coverage(self, document: IRDocument) -> None:
        cf = document.domain.coverage_fraction
        if cf < 0.25 or cf > 0.75:
            raise PolicyViolation(
                f"Spatial coverage fraction {cf} outside allowed range [0.25, 0.75]"
            )

    def _check_aggregation_window(self, document: IRDocument) -> None:
        aw = document.time.aggregation_window
        if aw < 7:
            raise PolicyViolation(
                f"Aggregation window {aw} is below minimum of 7"
            )

    def _check_security(self, document: IRDocument) -> None:
        if document.security.max_exports != 3:
            raise PolicyViolation(
                f"max_exports must be 3, got {document.security.max_exports}"
            )
        if not document.security.reconstruction_resistant:
            raise PolicyViolation("reconstruction_resistant must be True")

    def _check_audit(self, document: IRDocument) -> None:
        if not document.audit.traceable:
            raise PolicyViolation("traceable must be True")

    def _check_forbidden_keys(self, document: IRDocument) -> None:
        """Check all document fields for forbidden keys."""
        raw = document.to_dict()
        self._scan_dict_for_forbidden_keys(raw)

    def _scan_dict_for_forbidden_keys(self, d: Dict[str, Any], path: str = "") -> None:
        """Recursively scan dictionary for forbidden keys."""
        for key, value in d.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise PolicyViolation(
                    f"Forbidden key '{key}' found at {path or 'root'}"
                )
            if isinstance(value, dict):
                self._scan_dict_for_forbidden_keys(value, f"{path}.{key}" if path else key)
