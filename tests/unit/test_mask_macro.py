"""Unit tests for the mask() macro dispatcher (S0 scaffold + S1 area_values)."""

import numpy as np
import pytest

from HydrologicalTwinAlphaSeries.ht import HydrologicalTwin, MaskRequest, ValuesResponse
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


# ---------------------------------------------------------------------------
# S1 — kind="area_values" wraps extract_area()
# ---------------------------------------------------------------------------


def _area_values_kwargs(**overrides):
    base = {
        "kind": "area_values",
        "id_compartment": 1,
        "outtype": "MB",
        "param": "rain",
        "syear": 2000,
        "eyear": 2001,
    }
    base.update(overrides)
    return base


def test_mask_area_values_with_cell_ids_delegates_to_extract_area(monkeypatch):
    twin = _twin_in_loaded_state()
    captured = {}
    expected_response = ValuesResponse(data=np.zeros((3, 365)), dates=np.arange(365))

    def fake_extract_area(**kwargs):
        captured.update(kwargs)
        return expected_response

    monkeypatch.setattr(twin, "extract_area", fake_extract_area)

    response = twin.mask(**_area_values_kwargs(cell_ids=[1, 2, 3]))

    assert response is expected_response
    assert captured["id_compartment"] == 1
    assert captured["outtype"] == "MB"
    assert captured["param"] == "rain"
    assert captured["syear"] == 2000
    assert captured["eyear"] == 2001
    assert captured["id_layer"] == 0
    np.testing.assert_array_equal(captured["cell_ids"], np.array([1, 2, 3]))


def test_mask_area_values_with_both_cell_ids_and_polygon_raises():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError, match="either 'cell_ids' or 'polygon', not both"):
        twin.mask(**_area_values_kwargs(cell_ids=[1], polygon=object()))


def test_mask_area_values_with_neither_cell_ids_nor_polygon_raises():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError, match="requires either 'cell_ids' or 'polygon'"):
        twin.mask(**_area_values_kwargs())


def test_mask_area_values_with_polygon_only_raises_not_implemented():
    twin = _twin_in_loaded_state()

    with pytest.raises(NotImplementedError, match="cells_in_polygon"):
        twin.mask(**_area_values_kwargs(polygon=object()))


def test_mask_area_values_missing_required_field_raises():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError, match="non-None values for: outtype"):
        twin.mask(
            kind="area_values",
            id_compartment=1,
            param="rain",
            syear=2000,
            eyear=2001,
            cell_ids=[1, 2, 3],
        )
