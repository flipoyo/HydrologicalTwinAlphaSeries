"""Integration tests for the HydrologicalTwin canonical facade.

These tests validate the lifecycle, state transitions, macro-methods,
and output structure of the HydrologicalTwin facade.  They only
import from the public API surface.
"""

import pytest

from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject
from HydrologicalTwinAlphaSeries.ht import (
    DescribeRequest,
    ExportRequest,
    ExportResult,
    FacadeDescription,
    HydrologicalTwin,
    InvalidStateError,
    LoadCompartmentRequest,
    LoadGeometrySource,
    LoadRequest,
    RenderRequest,
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


class _Provider:
    def __init__(self, compartment):
        self.compartment = compartment

    def build_compartment(self, request, twin):
        return self.compartment


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
        twin.load(LoadRequest())
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

        twin.load(LoadRequest())
        assert twin.state == TwinState.LOADED

    def test_load_accepts_typed_compartment_requests(self, tmp_path):
        from unittest.mock import MagicMock

        from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment

        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        compartment = MagicMock(spec=Compartment)
        twin.load(
            LoadRequest(
                compartments=[
                    LoadCompartmentRequest(
                        id_compartment=7,
                        stable_id="AQ-7",
                        geometry_source=LoadGeometrySource(
                            kind="provider",
                            provider=_Provider(compartment),
                        ),
                    )
                ]
            )
        )

        assert twin.state == TwinState.LOADED
        assert twin.compartments[7] is compartment

    def test_register_compartment_after_load(self, tmp_path):
        twin = HydrologicalTwin()
        twin.configure(
            config_geom=_make_config_geom(),
            config_proj=_make_config_proj(tmp_path),
            out_caw_directory=str(tmp_path / "out"),
            obs_directory=str(tmp_path / "obs"),
        )
        twin.load(LoadRequest())

        # register_compartment requires LOADED state and a Compartment instance
        from unittest.mock import MagicMock

        from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
        mock_comp = MagicMock(spec=Compartment)
        with pytest.deprecated_call(match="register_compartment"):
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
        twin.load(LoadRequest())
        with pytest.deprecated_call(match="register_compartment"):
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
            with pytest.deprecated_call(match="register_compartment"):
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
            twin.load(LoadRequest())

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
        twin.load(LoadRequest())
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
        twin.load(LoadRequest())
        return twin

    def test_describe_returns_twin_description(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        desc = twin.describe(DescribeRequest(kind="catalog"))
        assert isinstance(desc, TwinDescription)
        assert desc.kind == "catalog"
        assert desc.state == "LOADED"
        assert desc.n_compartments == 0
        assert desc.compartments == []
        assert "simulation_matrix" in desc.extract_kinds
        assert "register_compartment" in desc.transitional_methods

    def test_export_pickle_returns_export_result(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        pkl_path = str(tmp_path / "twin.pkl")
        result = twin.export(ExportRequest(kind="pickle", path=pkl_path))
        assert isinstance(result, ExportResult)
        assert result.path == pkl_path
        assert result.meta["fmt"] == "pickle"

    def test_export_unknown_format_raises(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        with pytest.raises(ValueError, match="Unknown export format"):
            twin.export(path=str(tmp_path / "x"), fmt="unknown")

    def test_render_returns_file_artefacts(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        twin = self._make_loaded_twin(tmp_path)
        expected = [str(tmp_path / "budget.png")]
        plot_budget_barplot = MagicMock(return_value=expected)

        monkeypatch.setattr(
            "HydrologicalTwinAlphaSeries.ht.hydrological_twin.Renderer.plot_budget_barplot",
            plot_budget_barplot,
        )

        result = twin.render(
            RenderRequest(
                kind="budget",
                payload={"data_dict": {}, "plot_title": "Budget"},
            )
        )

        assert result.artefacts == expected
        assert result.meta == {"kind": "budget"}
        plot_budget_barplot.assert_called_once_with(
            data_dict={},
            plot_title="Budget",
            output_folder=None,
            output_name=None,
            yaxis_unit="mm",
        )

    def test_render_unknown_kind_raises(self, tmp_path):
        twin = self._make_loaded_twin(tmp_path)
        with pytest.raises(ValueError, match="Unknown render kind"):
            twin.render(kind="unknown_kind")


class TestFacadeDescription:
    """Verify the explicit facade description exposed to frontend consumers."""

    def test_describe_api_facade_lists_macro_and_frontend_methods(self):
        twin = HydrologicalTwin()

        description = twin.describe_api_facade()

        assert isinstance(description, FacadeDescription)
        assert description.entrypoint == "HydrologicalTwin"
        assert description.primary_consumer == "cawaqsviz"
        assert description.lifecycle == ["EMPTY", "CONFIGURED", "LOADED", "READY"]

        macro_names = {method.name for method in description.macro_methods}
        assert macro_names == {
            "configure",
            "load",
            "describe",
            "extract",
            "transform",
            "render",
            "export",
        }

        transitional_names = {method.name for method in description.transitional_methods}
        assert "register_compartment" in transitional_names
        assert "compute_* / build_* / render_* specifics" in transitional_names
