from importlib import import_module

import pytest

from HydrologicalTwinAlphaSeries import ConfigGeometry, ConfigProject, HydrologicalTwin


def test_root_imports_are_limited_to_canonical_entrypoints():
    assert ConfigGeometry.__name__ == "ConfigGeometry"
    assert ConfigProject.__name__ == "ConfigProject"
    assert HydrologicalTwin.__name__ == "HydrologicalTwin"


@pytest.mark.parametrize(
    "module_name",
    [
        "HydrologicalTwinAlphaSeries.Compartment",
        "HydrologicalTwinAlphaSeries.Extraction",
        "HydrologicalTwinAlphaSeries.Manage",
        "HydrologicalTwinAlphaSeries.Mesh",
        "HydrologicalTwinAlphaSeries.Observations",
        "HydrologicalTwinAlphaSeries.Renderer",
        "HydrologicalTwinAlphaSeries.Vec_Operator",
    ],
)
def test_deprecated_root_shim_modules_are_removed(module_name):
    with pytest.raises(ModuleNotFoundError):
        import_module(module_name)
