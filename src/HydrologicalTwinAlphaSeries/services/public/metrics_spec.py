"""
Metric-spec registry: scientific metadata for performance metrics.

The values in `METRIC_SPEC` (label, decimal precision, optional suffix) are
properties of each metric's *definition*, not of any particular UI surface:

- "PBIAS" is the spelling agreed in hydrology literature.
- PBIAS is reported in percent with one decimal because that is the
  conventional precision (more decimals are spurious).
- `n_obs` is a count: integer by definition.

Because these conventions belong to the metric rather than to QGIS, the
registry lives next to the computation (Comparator.calc_performance_metrics)
in the backend. It therefore travels with the standalone
HydrologicalTwinAlphaSeries package — a CLI, notebook, or server-side
client gets sensible defaults without reencoding hydrology conventions.

Consumers:
- frontend/DialogStatisticalCriteria.py rounds GIS-layer attribute values
  using `METRIC_SPEC[k]["digits"]`.
- services/public/renderer.py formats plot annotations using
  `format_metric(key, value)`.
"""

from typing import Optional, TypedDict

import numpy as np


class _MetricSpec(TypedDict):
    label: str
    digits: int
    suffix: Optional[str]


METRIC_SPEC: dict[str, _MetricSpec] = {
    "nash":      {"label": "NASH",         "digits": 2, "suffix": None},
    "kge":       {"label": "KGE",          "digits": 2, "suffix": None},
    "pearson":   {"label": "r",            "digits": 2, "suffix": None},
    "rmse":      {"label": "RMSE",         "digits": 2, "suffix": None},
    "mae":       {"label": "MAE",          "digits": 2, "suffix": None},
    "pbias":     {"label": "PBIAS",        "digits": 1, "suffix": " %"},
    "mean_bias": {"label": "Mean Bias",    "digits": 2, "suffix": None},
    "r2":        {"label": "r²",      "digits": 2, "suffix": None},
    "n_obs":     {"label": "N_obs",        "digits": 0, "suffix": None},
    "avg_obs":   {"label": "avg_obs",      "digits": 2, "suffix": None},
    "avg_sim":   {"label": "avg_sim",      "digits": 2, "suffix": None},
    "std_obs":   {"label": "σ_obs",   "digits": 2, "suffix": None},
    "std_sim":   {"label": "σ_sim",   "digits": 2, "suffix": None},
    "std_ratio": {"label": "σ_sim/σ_obs", "digits": 2, "suffix": None},
    "avg_ratio": {"label": "μ_sim/μ_obs", "digits": 2, "suffix": None},
    "sum_ratio": {"label": "Σsim/Σobs",   "digits": 2, "suffix": None},
}


_NAN_PLACEHOLDER = "–"


def format_metric(key: str, value: float) -> str:
    """Format `value` for display using the metric's conventional precision.

    NaN renders as a stable non-numeric placeholder ("–") rather than the
    literal string "nan", so plot annotations and tables stay readable when a
    metric is undefined for a given sim/obs pair.
    """
    spec = METRIC_SPEC[key]

    try:
        if np.isnan(value):
            return _NAN_PLACEHOLDER
    except TypeError:
        return _NAN_PLACEHOLDER

    digits = spec["digits"]
    if digits == 0:
        body = f"{int(round(float(value)))}"
    else:
        body = f"{float(value):.{digits}f}"

    suffix = spec["suffix"]
    return body + suffix if suffix else body
