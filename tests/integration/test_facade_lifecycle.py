"""Integration tests for the HydrologicalTwin canonical facade.

These tests validate the lifecycle, state transitions, macro-methods,
and output structure of the HydrologicalTwin facade.  They only
import from the public API surface.
"""

import pytest

from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject
from HydrologicalTwinAlphaSeries.ht import (
    ExportResult,
    HydrologicalTwin,
    InvalidStateError,
    TwinDescription,
    TwinState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_geom():
    return ConfigGeometry.fromDict(
        {
            "ids_compartment": [1],
            "resolutionNames": {1: [["AQ_LAYER"]]},
            "ids_col_cell": {1: 0},
            "obsNames": {},
            "obsIdsColCells": {},
            "obsIdsColNames": {},
            "obsIdsColLayers": {},
            "obsIdsCell": {},
            "extNames": {},
            "extIdsColNames": {},
            "extIdsColLayers": {},
            "extIdsColCells": {},
        }
    )


def _make_config_proj(tmp_path):
    return ConfigProject.fromDict(
        {
            "json_path_geometries": "geometry.json",
            "projectName": "demo",
            "cawOutDirectory": str(tmp_path / "out"),
            "startSim": 2000,
            "endSim": 2001,
            "obsDirectory": str(tmp_path / "obs"),
            "regime": "annual",
        }
    )


# ---------------------------------------------------------------------------
# State lifecycle tests
# ---------------------------------------------------------------------------

class TestStateLifecycle:
    """Verify EMPTY → CONFIGURED → LOADED → READY transitions."""

    def test_new_twin_starts_empty(self):
        twin = HydrologicalTwin()
        assert twin.state == TwinState.EMPTY

    def test_configure_transitions_to_configured(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        assert twin.state == TwinState.CONFIGURED

    def test_load_transitions_to_loaded(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        twin.load(compartments={})
        assert twin.state == TwinState.LOADED

    def test_auto_configure_at_construction(self, tmp_path):
        twin = HydrologicalTwin(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        assert twin.state == TwinState.CONFIGURED

    def test_full_lifecycle(self, tmp_path):
        twin = HydrologicalTwin()
        assert twin.state == TwinState.EMPTY

        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        assert twin.state == TwinState.CONFIGURED

        twin.load(compartments={})
        assert twin.state == TwinState.LOADED

    def test_register_compartment_after_load(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        twin.load(compartments={})

        # register_compartment requires LOADED state and a Compartment instance
        from unittest.mock import MagicMock

        from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
        mock_comp = MagicMock(spec=Compartment)
        twin.register_compartment(id_compartment=99, compartment=mock_comp)
        assert 99 in twin.compartments
        assert twin.compartments[99] is mock_comp

    def test_register_compartment_rejects_non_compartment(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        twin.load(compartments={})
        with pytest.raises(TypeError, match="Expected a Compartment"):
            twin.register_compartment(id_compartment=1, compartment=object())

    def test_register_compartment_before_load_raises(self, tmp_path):
        twin = HydrologicalTwin(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        with pytest.raises(InvalidStateError, match="LOADED"):
            from unittest.mock import MagicMock

            from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
            twin.register_compartment(
                id_compartment=1,
                compartment=MagicMock(spec=Compartment),
            )


# ---------------------------------------------------------------------------
# Invalid state transition tests
# ---------------------------------------------------------------------------

class TestInvalidStateTransitions:
    """Verify that invalid call sequences raise InvalidStateError."""

    def test_load_before_configure_raises(self):
        twin = HydrologicalTwin()
        with pytest.raises(InvalidStateError, match="CONFIGURED"):
            twin.load(compartments={})

    def test_describe_before_load_raises(self, tmp_path):
        twin = HydrologicalTwin(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        with pytest.raises(InvalidStateError, match="LOADED"):
            twin.describe()

    def test_extract_before_load_raises(self, tmp_path):
        twin = HydrologicalTwin(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        with pytest.raises(InvalidStateError):
            twin.extract(id_compartment=1, outtype="MB", param="rain", syear=2000, eyear=2001)

    def test_render_before_load_raises(self, tmp_path):
        twin = HydrologicalTwin(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        with pytest.raises(InvalidStateError):
            twin.render(kind="budget")

    def test_export_before_load_raises(self, tmp_path):
        twin = HydrologicalTwin(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        with pytest.raises(InvalidStateError):
            twin.export(path=str(tmp_path / "out.pkl"))

    def test_configure_after_loaded_raises(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        twin.load(compartments={})
        with pytest.raises(InvalidStateError):
            twin.configure(
                config_geom=_make_config_geom(),
                config_proj=_make_config_proj(tmp_path),
                out_caw_directory=str(tmp_path / "out"),
                obs_directory=str(tmp_path / "obs"),
            )


# ---------------------------------------------------------------------------
# Macro-method output structure tests
# ---------------------------------------------------------------------------

class TestMacroMethods:
    """Verify macro-method output types."""

    def _make_loaded_twin(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        twin.load(compartments={})
        return twin

    def test_describe_returns_twin_description(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        desc = twin.describe()
        assert isinstance(desc, TwinDescription)
        assert desc.state == "LOADED"
        assert desc.n_compartments == 0
        assert desc.compartments == []

    def test_export_pickle_returns_export_result(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        pkl_path = str(tmp_path / "twin.pkl")
        result = twin.export(path=pkl_path, fmt="pickle")
        assert isinstance(result, ExportResult)
        assert result.path == pkl_path
        assert result.meta["fmt"] == "pickle"

    def test_export_unknown_format_raises(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        with pytest.raises(ValueError, match="Unknown export format"):
            twin.export(path=str(tmp_path / "x"), fmt="unknown")

    def test_render_returns_file_artefacts(self, tmp_path, monkeypatch):
        twin = self._make_loaded_twin(tmp_path)
        expected = [str(tmp_path / "budget.png")]

        monkeypatch.setattr(twin, "render_budget_barplot", lambda **kwargs: expected)

        result = twin.render(kind="budget")

        assert result.artefacts == expected
        assert result.meta == {"kind": "budget"}

    def test_render_unknown_kind_raises(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        with pytest.raises(ValueError, match="Unknown render kind"):
            twin.render(kind="unknown_kind")
