"""TOML serializer for HTAS IR documents.

Only accepts IRDocument instances. No generic object dumping is allowed.
Fields are explicitly whitelisted.
"""

from __future__ import annotations

from typing import Any, Dict

from HydrologicalTwinAlphaSeries.ir_gateway.ir_document import IRDocument


class TOMLSerializer:
    """Serialize validated IRDocument instances to TOML strings.

    The serializer only accepts IRDocument instances and explicitly
    whitelists all output fields. No generic object.__dict__ dumping.
    """

    def serialize(self, document: IRDocument) -> str:
        """Serialize an IRDocument to a TOML-formatted string.

        Raises TypeError if the input is not an IRDocument.
        """
        if not isinstance(document, IRDocument):
            raise TypeError(
                f"TOMLSerializer only accepts IRDocument instances, got {type(document).__name__}"
            )
        data = document.to_dict()
        return self._dict_to_toml(data)

    def _dict_to_toml(self, data: Dict[str, Any]) -> str:
        """Convert a whitelisted dictionary to TOML format."""
        lines: list[str] = []
        for section, values in data.items():
            lines.append(f"[{section}]")
            for key, value in values.items():
                lines.append(f"{key} = {self._format_value(value)}")
            lines.append("")
        return "\n".join(lines)

    def _format_value(self, value: Any) -> str:
        """Format a single value as a TOML literal."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        if isinstance(value, str):
            return f'"{self._escape_string(value)}"'
        if isinstance(value, dict):
            items = ", ".join(
                f"{k} = {self._format_value(v)}" for k, v in value.items()
            )
            return "{ " + items + " }"
        if isinstance(value, list):
            items = ", ".join(self._format_value(v) for v in value)
            return "[" + items + "]"
        raise TypeError(f"Unsupported TOML value type: {type(value).__name__}")

    @staticmethod
    def _escape_string(s: str) -> str:
        """Escape special characters for TOML string literals."""
        return (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
