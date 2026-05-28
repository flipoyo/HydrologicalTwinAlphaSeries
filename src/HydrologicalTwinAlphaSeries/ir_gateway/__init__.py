"""HTAS IR Gateway — read-only API serving pre-validated TOML manifests.

This module implements the single publication gateway for HTAS IR documents.
It exposes only validated HTASObject TOML documents and enforces strict
policy controls including spatial coverage bounds, temporal aggregation
minimums, and per-session export limits.
"""

from HydrologicalTwinAlphaSeries.ir_gateway.ir_document import IRDocument
from HydrologicalTwinAlphaSeries.ir_gateway.ir_store import IRStore
from HydrologicalTwinAlphaSeries.ir_gateway.policy_validator import PolicyValidator
from HydrologicalTwinAlphaSeries.ir_gateway.serializer import TOMLSerializer
from HydrologicalTwinAlphaSeries.ir_gateway.session_tracker import SessionTracker

__all__ = [
    "IRDocument",
    "IRStore",
    "PolicyValidator",
    "SessionTracker",
    "TOMLSerializer",
]
