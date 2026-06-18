"""Raw-data export assemblers (CSV / text / numpy).

The functions in this module assemble raw, per-point/per-cell series destined
for user export. They live under ``services/private/`` to keep leak-prone
"raw data" code behind the same internal-only boundary as the mask operations.

NB: placement here is by the *intent* of the private-folder charter (these
assemble Tier-2 raw per-point series for CSV export), not by the literal
"consumes a user-supplied geometry" clause of the placement rule in
``services/SECURITY.md``. See that document for the full rationale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:  # avoid a hard import cycle at runtime
    from HydrologicalTwinAlphaSeries.ht.developer.api_types import (
        SimObsBundleResponse,
    )


def assemble_daily_sim_obs_table(bundle: "SimObsBundleResponse") -> pd.DataFrame:
    """Assemble one wide daily sim/obs table from a sim/obs bundle.

    Builds a single date-indexed :class:`pandas.DataFrame` covering every
    observation and extraction point in ``bundle``:

    * each observation point contributes a ``sim_<name>`` column (on the
      simulation date axis ``bundle.sim_dates``) and an ``obs_<name>`` column
      (on the observation date axis ``bundle.obs_dates``);
    * each extraction point contributes a ``sim_<name>`` column only —
      extraction points have no observations, so ``sim_`` columns
      intentionally have no ``obs_`` counterpart.

    The sim and obs series ride two *separate* date axes; they are aligned by
    an outer-join (``pd.concat(axis=1)``) on the union of dates, with gaps
    filled by ``NaN``. The arrays are not assumed equal-length or co-dated.

    When two points share the same ``name``, the colliding column keys are
    disambiguated by appending the point's ``id_point`` (e.g.
    ``sim_STATION_A_12``) so no two columns share a key.

    Placement note: this function lives in ``services/private/`` by the
    data-leak *intent* of the charter (it assembles a Tier-2 raw per-point
    series destined for a user-exported CSV), **not** by the user-supplied
    geometry clause of the placement rule — it consumes no geometry. The
    geometry clause MUST NOT be used to move it back to ``public/``. See
    ``services/SECURITY.md``.

    This function performs **no** disk I/O: it returns data, leaving
    persistence to the caller (the frontend).

    :param bundle: A populated :class:`SimObsBundleResponse`.
    :returns: A date-indexed :class:`pandas.DataFrame` (possibly empty when
        the bundle carries no observation and no extraction points).
    """
    sim_index = pd.DatetimeIndex(bundle.sim_dates)
    obs_index = pd.DatetimeIndex(bundle.obs_dates)

    # Count name occurrences across all points so we know which need a
    # disambiguating ``id_point`` suffix.
    all_points = list(bundle.obs_points) + list(bundle.ext_points)
    name_counts: dict = {}
    for point in all_points:
        name_counts[point.name] = name_counts.get(point.name, 0) + 1

    def _key(point) -> str:
        if name_counts.get(point.name, 0) > 1:
            return f"{point.name}_{point.id_point}"
        return point.name

    columns: "dict[str, pd.Series]" = {}

    for point in bundle.obs_points:
        key = _key(point)
        if point.sim is not None:
            columns[f"sim_{key}"] = pd.Series(point.sim, index=sim_index)
        if point.obs is not None:
            columns[f"obs_{key}"] = pd.Series(point.obs, index=obs_index)

    for point in bundle.ext_points:
        key = _key(point)
        if point.sim is not None:
            columns[f"sim_{key}"] = pd.Series(point.sim, index=sim_index)

    if not columns:
        # No obs and no ext points: return a well-formed empty table rather
        # than raise, so callers can persist a header-only CSV cleanly.
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))

    table = pd.concat(columns, axis=1)
    table.index.name = "Date"
    return table
