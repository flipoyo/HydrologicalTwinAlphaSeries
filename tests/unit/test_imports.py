from HydrologicalTwinAlphaSeries import Compartment, ConfigGeometry, HydrologicalTwin, Manage


def test_root_imports_are_available():
    assert Compartment.__name__ == "Compartment"
    assert ConfigGeometry.__name__ == "ConfigGeometry"
    assert HydrologicalTwin.__name__ == "HydrologicalTwin"
    assert hasattr(Manage, "Temporal")