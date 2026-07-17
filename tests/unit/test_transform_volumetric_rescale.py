"""Unit tests for the L2 ``transform(kind="volumetric_rescale")`` micro-verb.

The verb scales a raw CaWaQS ``m³/s`` flux array/series by the single factor
looked up in ``_VOLUMETRIC_UNIT_FACTORS`` for the requested token. It is the one
rescale both AQ-boundary output surfaces call, so a unit can never be applied to
one surface and not the other. The branch is a pure function of ``request`` and
never touches the twin handle, so it is driven here through ``dispatch.transform``
with a ``None`` twin.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from HydrologicalTwinAlphaSeries.ht.developer import dispatch
from HydrologicalTwinAlphaSeries.ht.developer.api_types import TransformRequest


def _rescale(data, token):
    return dispatch.transform(
        None, TransformRequest(kind="volumetric_rescale", data=data, target_unit=token)
    )


def test_m3_per_day_multiplies_by_86400():
    arr = np.array([1.0, 2.0, 3.0])
    np.testing.assert_allclose(_rescale(arr, "m3/j"), arr * 86400.0)


def test_m3_per_month_multiplies_by_average_month_factor():
    arr = np.array([1.0, 2.0, 3.0])
    np.testing.assert_allclose(_rescale(arr, "m3/mois"), arr * 2_629_800.0)


def test_m3_per_second_is_pass_through():
    arr = np.array([1.0, 2.0, 3.0])
    np.testing.assert_allclose(_rescale(arr, "m3/s"), arr)


def test_unknown_token_raises_value_error_naming_the_token():
    with pytest.raises(ValueError, match="bogus"):
        _rescale(np.array([1.0]), "bogus")


def test_preserves_pandas_series_shape_and_index():
    series = pd.Series([1.0, 2.0], index=["2000-01-01", "2000-01-02"])
    out = _rescale(series, "m3/mois")
    assert isinstance(out, pd.Series)
    assert list(out.index) == ["2000-01-01", "2000-01-02"]
    np.testing.assert_allclose(out.to_numpy(), series.to_numpy() * 2_629_800.0)


# ---------------------------------------------------------------------------
# 5.6 Golden-rule guard: the L1 orchestration must not re-grow inline ×86400
# data-handling — the rescale lives only in this L2 verb. (CLAUDE.md
# "L1 only orchestrates".)
# ---------------------------------------------------------------------------


def test_run_mask_aq_boundary_has_no_inline_86400_arithmetic():
    import ast
    import inspect

    from HydrologicalTwinAlphaSeries.ht.client import operations_client

    src = inspect.getsource(operations_client.run_mask_aq_boundary)
    tree = ast.parse(src)

    # Any numeric literal 86400 / 86400.0 / 2_629_800 in *code* (not the
    # docstring, which ast.parse drops from the node values it walks) means a
    # rescale factor leaked back into L1.
    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and node.value in (86400, 86400.0, 2_629_800, 2_629_800.0)
    ]
    assert offenders == [], (
        "run_mask_aq_boundary contains an inline unit factor "
        f"{offenders!r}; push the rescale into the L2 volumetric_rescale verb."
    )
