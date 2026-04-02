from hydrological_twin_alpha_series.ht.hydrological_twin import HydrologicalTwin
from hydrological_twin_alpha_series.security import (
    ACCESS_POLICY_ATTR,
    PUBLIC_METHODS_ATTR,
    list_public_methods,
    private_access,
    public_access,
)


def test_private_access_requires_explicit_public_annotations():
    try:
        @private_access
        class InvalidFacade:
            def exposed(self):
                return "missing"
    except TypeError as exc:
        assert "InvalidFacade uses @private_access" in str(exc)
        assert "exposed" in str(exc)
    else:
        raise AssertionError("Expected @private_access to reject undecorated public methods.")


def test_private_access_tracks_public_methods():
    @private_access
    class ValidFacade:
        @public_access
        def exposed(self):
            return "ok"

        def _internal(self):
            return "hidden"

    assert getattr(ValidFacade, ACCESS_POLICY_ATTR) == "private_by_default"
    assert getattr(ValidFacade, PUBLIC_METHODS_ATTR) == ("exposed",)
    assert list_public_methods(ValidFacade) == ("exposed",)


def test_hydrological_twin_declares_public_facade_methods_explicitly():
    public_methods = list_public_methods(HydrologicalTwin)

    assert "list_compartments" in public_methods
    assert "extract_values" in public_methods
    assert "apply_spatial_average" in public_methods
    assert "_prepare_sim_obs_data" not in public_methods
