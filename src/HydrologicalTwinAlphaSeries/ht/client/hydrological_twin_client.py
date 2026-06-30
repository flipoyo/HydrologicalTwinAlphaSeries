"""L1 · HT CLIENT · MACRO — one method per dialog operation.

:class:`HydrologicalTwinClient` wraps each ``fetch → transform → render``
chain into a single call that returns a typed ``*Result`` dataclass.
Zero ``qgis.*`` / ``PyQt5`` / ``processing`` imports.
"""

from __future__ import annotations

from ...services.public.automatic_detection_config import (
    detect_from_out_caw,
    detect_project_neighbors,
)
from ..developer import HydrologicalTwin
from . import operations_client
from .api_types import (
    BudgetBarplotResult,
    CompareSimObsResult,
    HydrologicalRegimeResult,
    MaskAqBoundaryResult,
    MaskHydBoundaryResult,
    MaskInternalValuesResult,
    SpatialMapAqResult,
    SpatialMapWatbalResult,
    StatisticalCriteriaResult,
)


class HydrologicalTwinClient:
    """L1 · HT CLIENT · MACRO — one operation per dialog, on top of :class:`HydrologicalTwin`.

    One method per user-facing operation. Method bodies are thin (≤5 statements):
    they delegate to :func:`operations_client.run_*`, which owns the orchestration.
    This is the surface a future HTTP server will expose.

    Add a new operation: (1) ``*Result`` in :mod:`api_types`, (2) ``run_<name>``
    in :mod:`operations_client`, (3) one-line facade method here.
    """

    def __init__(self, metadata: dict):
        self._twin = HydrologicalTwin(metadata=metadata)

    def configure(self, **kwargs):
        return self._twin.configure(**kwargs)

    def load(self, **kwargs):
        return self._twin.load(**kwargs)

    def describe(self):
        return self._twin.describe()

    def is_ready(self) -> bool:
        return self._twin.state.value in {"LOADED", "READY"}

    @classmethod
    def build(cls, metadata: dict, *, configure_kwargs: dict, load_kwargs: dict) -> "HydrologicalTwinClient":
        client = cls(metadata)
        client.configure(**configure_kwargs)
        client.load(**load_kwargs)
        return client

    @staticmethod
    def detect_from_out_caw(out_caw_directory: str) -> dict:
        return detect_from_out_caw(out_caw_directory)

    @staticmethod
    def detect_project_neighbors(project_file_path) -> dict:
        return detect_project_neighbors(project_file_path)


    def budget_barplot(self, **kwargs) -> BudgetBarplotResult:
        return operations_client.run_budget_barplot(self._twin, **kwargs)

    def hydrological_regime(self, **kwargs) -> HydrologicalRegimeResult:
        return operations_client.run_hydrological_regime(self._twin, **kwargs)

    def spatial_map_watbal(self, **kwargs) -> SpatialMapWatbalResult:
        return operations_client.run_spatial_map_watbal(self._twin, **kwargs)

    def spatial_map_aq(self, **kwargs) -> SpatialMapAqResult:
        return operations_client.run_spatial_map_aq(self._twin, **kwargs)

    def compare_sim_obs(self, **kwargs) -> CompareSimObsResult:
        return operations_client.run_compare_sim_obs(self._twin, **kwargs)

    def statistical_criteria(self, **kwargs) -> StatisticalCriteriaResult:
        return operations_client.run_statistical_criteria(self._twin, **kwargs)

    def mask_internal_values(
        self, *, weighted: bool = True, **kwargs
    ) -> MaskInternalValuesResult:
        # ``weighted`` is broken out from kwargs so it appears in the public
        # signature; the output unit is now carried per-spec as the 4th element
        # of each ``(compartment, outtype, param, unit)`` tuple in ``specs``.
        # See :func:`operations_client.run_mask_internal_values` for the ``specs``
        # shape, the unit token table, and semantics.
        return operations_client.run_mask_internal_values(
            self._twin, weighted=weighted, **kwargs
        )

    def mask_hyd_boundary(self, **kwargs) -> MaskHydBoundaryResult:
        return operations_client.run_mask_hyd_boundary(self._twin, **kwargs)

    def mask_aq_boundary(
        self, *, write_geopackage: bool = False, unit: str = "m3/j", **kwargs
    ) -> MaskAqBoundaryResult:
        # ``write_geopackage`` is broken out so it appears in the public
        # signature; ``False`` keeps today's loose face-flux CSV behaviour and
        # ``True`` additionally writes the AqBoundary GeoPackage bundle. ``unit``
        # selects the boundary-flux output unit token — ``"m3/j"`` (m³/day,
        # default, current behaviour) or ``"m3/mois"`` (m³/month, an average-month
        # rate); it drives the numeric conversion, the loose-CSV column suffix, and
        # the GeoPackage unit label. See
        # :func:`operations_client.run_mask_aq_boundary` for the two modes.
        return operations_client.run_mask_aq_boundary(
            self._twin, write_geopackage=write_geopackage, unit=unit, **kwargs
        )
