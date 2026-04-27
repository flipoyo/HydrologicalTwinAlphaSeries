"""Unit tests for the mask() macro dispatcher scaffold (S0)."""

import pytest

from HydrologicalTwinAlphaSeries.ht import HydrologicalTwin, MaskRequest
from HydrologicalTwinAlphaSeries.ht.api_types import InvalidStateError, TwinState


def _twin_in_loaded_state() -> HydrologicalTwin:
    twin = HydrologicalTwin()
    twin._state = TwinState.LOADED
    return twin


def test_mask_unknown_kind_raises_value_error_naming_the_kind():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError) as exc:
        twin.mask(kind="does_not_exist")

    assert "does_not_exist" in str(exc.value)


def test_mask_unknown_kind_via_request_object_raises_value_error():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError) as exc:
        twin.mask(request=MaskRequest(kind="does_not_exist"))

    assert "does_not_exist" in str(exc.value)


def test_mask_before_loaded_state_raises_invalid_state():
    twin = HydrologicalTwin()

    with pytest.raises(InvalidStateError):
        twin.mask(kind="does_not_exist")


def test_mask_rejects_unexpected_kwargs_alongside_request():
    twin = _twin_in_loaded_state()

    with pytest.raises(TypeError):
        twin.mask(request=MaskRequest(kind="does_not_exist"), bogus_kwarg=42)
