"""Per-verb ``kind=...`` routing for the dispatching macro-verbs.

Role
----
This module holds the *dispatch ladders* that were previously embedded
inside ``HydrologicalTwin.fetch``/``mask``/``transform``/``render``. Each
function here takes the twin instance and a fully-coerced ``*Request``
dataclass, walks an ``if request.kind == "X":`` ladder, calls into
``handlers.py`` to do the work, and packages a typed ``*Response``.

What belongs here
-----------------
- ``def fetch(twin, request) -> ...``     — the 7-kind fetch ladder
- ``def mask(twin, request) -> ...``      — the mask kind ladder
- ``def transform(twin, request) -> ...`` — the transform kind ladder
- ``def render(twin, request) -> ...``    — the render kind ladder

What does NOT belong here
-------------------------
- Argument coercion from positional/``request=``/``**kwargs`` shapes →
  stays in the facade so this module receives canonical ``*Request``
  objects with sharp signatures.
- State-gate checks (``_require_state``) → stay in the facade.
- The actual computation (``compute_*``, ``_build_*_gdf``,
  ``extract_area``, ``render_*``) → ``handlers.py``.
- Reads over twin state (``read_*``, ``get_*``, ``_resolve_*``) →
  ``accessors.py``.
- The 4 non-dispatching verbs (``configure``, ``load``, ``describe``,
  ``export``) — they are small and inline in the facade by design.

Relation to other modules
-------------------------
- ``hydrological_twin.py`` calls into this module from the 4 dispatching
  facade methods.
- This module calls into ``handlers.py`` for the work.
- This module may call ``accessors.py`` for incidental state reads, but
  the primary path is through ``handlers``.

Import direction (no backward edges)
------------------------------------
    hydrological_twin.py → dispatch.py → handlers.py → accessors.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.config.constants import AQ_FACE_DIRECTIONS, module_caw
from HydrologicalTwinAlphaSeries.services.public.spatial import Spatial
from HydrologicalTwinAlphaSeries.tools.spatial_utils import (
    aq_cells_boundary_faces,
    aq_cells_on_polygon_boundary,
    cells_in_polygon,
    cells_in_polygon_weighted,
    reaches_inflow_outflow_signs,
    verify_crs_match,
)

from .api_types import (
    AqBoundaryFluxResponse,
    AqBoundaryResponse,
    AquiferBalanceInputsResponse,
    AquiferBalanceResponse,
    BudgetComputationResponse,
    CellSelectionResponse,
    CriteriaResponse,
    FetchRequest,
    HydBoundaryFluxResponse,
    HydBoundaryResponse,
    HydrologicalRegimeResponse,
    MaskRequest,
    RenderRequest,
    RenderResult,
    RunoffRatioResponse,
    SpatialMapResponse,
    TransformRequest,
    ValuesResponse,
)

if TYPE_CHECKING:
    from .hydrological_twin import HydrologicalTwin  # noqa: F401


# Units accepted when ``weighted=True`` — area-fraction weighting is only
# physically meaningful on volumetric flux data (different cell sizes
# contribute different volumes from the same intensity).
_VOLUMETRIC_UNITS = frozenset({"m3/j", "m3/s"})


def fetch(twin: "HydrologicalTwin", request: FetchRequest) -> Any:
    """Dispatch ladder for ``HydrologicalTwin.fetch``."""
    if request.kind == "simulation_matrix":
        if request.target_unit and request.outtype == "MB":
            return twin.read_watbal_converted(
                id_compartment=request.id_compartment,
                outtype=request.outtype,
                param=request.param,
                syear=request.syear,
                eyear=request.eyear,
                cutsdate=request.cutsdate,
                cutedate=request.cutedate,
                id_layer=request.id_layer,
                target_unit=request.target_unit,
            )
        return twin.read_values(
            id_compartment=request.id_compartment,
            outtype=request.outtype,
            param=request.param,
            syear=request.syear,
            eyear=request.eyear,
            id_layer=request.id_layer,
            cutsdate=request.cutsdate,
            cutedate=request.cutedate,
        )

    if request.kind == "observations":
        return twin.read_observations(
            id_compartment=request.id_compartment,
            syear=request.syear,
            eyear=request.eyear,
        )

    if request.kind == "sim_obs_bundle":
        bundle = twin._prepare_sim_obs_data(
            id_compartment=request.id_compartment,
            outtype=request.outtype,
            param=request.param,
            simsdate=request.syear,
            simedate=request.eyear,
            plotstart=request.plotstart or request.cutsdate,
            plotend=request.plotend or request.cutedate,
            id_layer=request.id_layer,
            aggr=request.agg,
            compute_criteria=request.compute_criteria,
            criteria_metrics=request.criteria_metrics,
            crit_start=request.crit_start,
            crit_end=request.crit_end,
            obs_unit=request.obs_unit,
        )
        bundle["meta"] = {
            "id_compartment": request.id_compartment,
            "outtype": request.outtype,
            "param": request.param,
        }
        return twin._bundle_dict_to_response(bundle)

    if request.kind == "spatial_map":
        comp_info = twin.get_compartment_info(request.id_compartment)
        frequency_label = twin._normalize_frequency(request.frequency, target="long")

        if comp_info.name == "WATBAL":
            if request.param in {"eff_rain", "effective_rainfall"}:
                gdf = twin._build_effective_rainfall_gdf(
                    id_compartment=request.id_compartment,
                    syear=request.syear,
                    eyear=request.eyear,
                    cutsdate=request.cutsdate,
                    cutedate=request.cutedate,
                    id_layer=request.id_layer,
                    agg=request.agg or "mean",
                    frequency=frequency_label,
                    pluriannual=request.pluriannual,
                )
            else:
                gdf = twin._build_watbal_spatial_gdf(
                    id_compartment=request.id_compartment,
                    outtype=request.outtype or "MB",
                    param=request.param,
                    syear=request.syear,
                    eyear=request.eyear,
                    cutsdate=request.cutsdate,
                    cutedate=request.cutedate,
                    id_layer=request.id_layer,
                    target_unit=request.target_unit or "mm/j",
                    agg=request.agg or "mean",
                    frequency=frequency_label,
                    pluriannual=request.pluriannual,
                )
        else:
            gdf = twin._build_aq_spatial_gdf(
                id_compartment=request.id_compartment,
                outtype=request.outtype,
                param=request.param,
                syear=request.syear,
                eyear=request.eyear,
                cutsdate=request.cutsdate,
                cutedate=request.cutedate,
                layers=twin._resolve_layer_infos(request.id_compartment, request),
                agg=request.agg or "mean",
                frequency=frequency_label,
                pluriannual=request.pluriannual,
                layer_id_offset=request.layer_id_offset,
            )

        return SpatialMapResponse(
            gdf=gdf,
            meta={
                "id_compartment": request.id_compartment,
                "param": request.param,
                "frequency": frequency_label,
                "agg": request.agg,
            },
        )

    if request.kind == "catchment_cells":
        cell_ids = Spatial().getCatchmentCellsIds(
            request.obs_geometry,
            request.network_gdf,
            request.network_col_name_cell,
            request.network_col_name_fnode,
            request.network_col_name_tnode,
        )
        return CellSelectionResponse(
            cell_ids=list(cell_ids),
            meta={"id_compartment": request.id_compartment, "kind": request.kind},
        )

    if request.kind == "aquifer_outcropping_map":
        frequency_label = twin._normalize_frequency(request.frequency, target="long")
        cell_ids = twin._build_aquifer_outcropping(
            id_compartment=request.id_compartment,
            save_directory=request.save_directory,
        )
        gdf = twin._build_aq_spatial_gdf(
            id_compartment=request.id_compartment,
            outtype=request.outtype,
            param=request.param,
            syear=request.syear,
            eyear=request.eyear,
            cutsdate=request.cutsdate,
            cutedate=request.cutedate,
            layers=twin.get_all_layers(request.id_compartment),
            agg=request.agg or "mean",
            frequency=frequency_label,
            pluriannual=request.pluriannual,
            layer_id_offset=request.layer_id_offset,
            outcropping_cell_ids=cell_ids,
        )
        return SpatialMapResponse(
            gdf=gdf,
            meta={
                "id_compartment": request.id_compartment,
                "param": request.param,
                "frequency": frequency_label,
                "agg": request.agg,
                "resolution": "outcropping",
            },
        )

    if request.kind == "aq_balance_inputs":
        alias_to_param = {
            "Overflow": "surf_overflow",
            "Riv": "flux_riv_to_aq",
            "Dirichlet": "flux_direchlet",
            "Neumann": "flux_neumann",
            "Flux_bot": "flux_z_one",
            "Flux_top": "flux_z_two",
            "Recharge": "recharge",
            "Uptake": "uptake",
            "Stock": "dv_dt",
            "Err": "err",
        }
        selected = request.variables or list(alias_to_param.keys())
        data: Dict[str, np.ndarray] = {}
        dates = None
        for label in selected:
            backend_param = alias_to_param.get(label, label)
            response = twin.read_values(
                id_compartment=request.id_compartment,
                outtype=request.outtype or "MB",
                param=backend_param,
                syear=request.syear,
                eyear=request.eyear,
                id_layer=request.id_layer if request.id_layer != 0 else -9999,
                cutsdate=request.cutsdate,
                cutedate=request.cutedate,
            )
            data[label] = response.data
            if dates is None:
                dates = response.dates

        return AquiferBalanceInputsResponse(
            data=data,
            dates=dates,
            meta={
                "id_compartment": request.id_compartment,
                "outtype": request.outtype or "MB",
                "variables": selected,
            },
        )

    raise ValueError(f"Unknown fetch kind: {request.kind!r}")


def mask(twin: "HydrologicalTwin", request: MaskRequest) -> Any:
    """Dispatch ladder for ``HydrologicalTwin.mask``."""
    if request.kind == "area_values":
        if request.cell_ids is not None and request.polygon is not None:
            raise ValueError(
                "mask(kind='area_values') accepts either 'cell_ids' or "
                "'polygon', not both."
            )
        if request.cell_ids is None and request.polygon is None:
            raise ValueError(
                "mask(kind='area_values') requires either 'cell_ids' or "
                "'polygon' to identify the cell subset."
            )
        missing = [
            name
            for name in ("id_compartment", "outtype", "param", "syear", "eyear")
            if getattr(request, name) is None
        ]
        if missing:
            raise ValueError(
                f"mask(kind='area_values') requires non-None values for: {', '.join(missing)}."
            )
        assert request.id_compartment is not None
        assert request.outtype is not None
        assert request.param is not None
        assert request.syear is not None
        assert request.eyear is not None

        if request.weighted and request.target_unit not in _VOLUMETRIC_UNITS:
            raise ValueError(
                "mask(kind='area_values', weighted=True) requires a volumetric "
                f"target_unit (one of {sorted(_VOLUMETRIC_UNITS)}); got "
                f"target_unit={request.target_unit!r}. Area-fraction weighting "
                "only has a physical meaning on volumetric data — cells of "
                "different sizes contribute different volumes from the same "
                "intensity."
            )
        if request.weighted and request.polygon is None:
            raise ValueError(
                "mask(kind='area_values', weighted=True) requires 'polygon'; "
                "weighted selection by raw 'cell_ids' is not supported."
            )

        weights: Optional[np.ndarray] = None
        clipped_geoms: Optional[List[Any]] = None
        if request.polygon is not None:
            mesh_gdf = twin._resolve_mesh_gdf(request.id_compartment, request.id_layer)
            verify_crs_match(
                mesh_gdf.crs,
                request.polygon_crs,
                context="mask(kind='area_values')",
            )
            id_col = twin._resolve_cell_id_col(request.id_compartment)
            if request.weighted:
                triples = cells_in_polygon_weighted(
                    mesh_gdf, request.polygon, id_col=id_col
                )
                resolved_cell_ids = [cid for cid, _, _ in triples]
                weights = np.asarray([w for _, w, _ in triples], dtype=np.float64)
                clipped_geoms = [g for _, _, g in triples]
            else:
                resolved_cell_ids = cells_in_polygon(
                    mesh_gdf, request.polygon, id_col=id_col
                )
        else:
            resolved_cell_ids = list(request.cell_ids or [])

        if request.target_unit is not None:
            full_response = twin.read_watbal_converted(
                id_compartment=request.id_compartment,
                outtype=request.outtype,
                param=request.param,
                syear=request.syear,
                eyear=request.eyear,
                cutsdate=request.cutsdate,
                cutedate=request.cutedate,
                id_layer=request.id_layer,
                target_unit=request.target_unit,
            )
            # The mesh GIS id column (ELEBU / DHRC) is contiguous and 1-based
            # — id N lives at positional row N-1 of the binary-ordered values
            # array. ``resolved_cell_ids`` keeps the 1-based ids as labels
            # (meta + GeoPackage join); only the positional lookup is shifted.
            # This mirrors ``data[id - 1]`` already used in budget.py:189/280
            # and handlers.py:145/213.
            row_positions = np.asarray(resolved_cell_ids, dtype=np.intp) - 1
            subset_data = full_response.data[row_positions]
            if request.weighted and weights is not None:
                subset_data = subset_data * weights[:, None]
            meta = {
                "id_compartment": request.id_compartment,
                "outtype": request.outtype,
                "param": request.param,
                "syear": request.syear,
                "eyear": request.eyear,
                "id_layer": request.id_layer,
                "n_cells": subset_data.shape[0],
                "target_unit": request.target_unit,
                "weighted": bool(request.weighted),
                "cell_ids": list(resolved_cell_ids),
            }
            return ValuesResponse(
                data=subset_data,
                dates=full_response.dates,
                meta=meta,
                weights=weights,
                clipped_geometries=clipped_geoms,
            )

        # NOTE: this branch (target_unit is None) is NOT reached by the mask
        # dialog, which always sends a unit token. It still carries the same
        # 1-based-id / 0-based-row mismatch as the converted branch above:
        # ``extract_area`` forwards ``cell_ids`` straight to
        # ``apply_spatial_mask`` (0-based positional lookup) AND reuses them as
        # CSV/meta labels, so it can't be fixed by a flat -1 here without
        # corrupting the labels — it needs a separate labels arg. Left as-is
        # for now since it's out of scope for the internal-values fix.
        return twin.extract_area(
            id_compartment=request.id_compartment,
            outtype=request.outtype,
            param=request.param,
            syear=request.syear,
            eyear=request.eyear,
            cell_ids=np.asarray(resolved_cell_ids, dtype=np.intp),
            id_layer=request.id_layer,
            cutsdate=request.cutsdate,
            cutedate=request.cutedate,
        )

    if request.kind == "polygon_cells":
        if request.id_compartment is None or request.polygon is None:
            raise ValueError(
                "mask(kind='polygon_cells') requires both 'id_compartment' and 'polygon'."
            )
        mesh_gdf = twin._resolve_mesh_gdf(request.id_compartment, request.id_layer)
        verify_crs_match(
            mesh_gdf.crs,
            request.polygon_crs,
            context="mask(kind='polygon_cells')",
        )
        id_col = twin._resolve_cell_id_col(request.id_compartment)
        cell_ids = cells_in_polygon(mesh_gdf, request.polygon, id_col=id_col)
        return CellSelectionResponse(
            cell_ids=list(cell_ids),
            meta={"id_compartment": request.id_compartment, "kind": request.kind},
        )

    if request.kind == "boundary_hyd":
        if request.id_compartment is None or request.polygon is None:
            raise ValueError(
                "mask(kind='boundary_hyd') requires both 'id_compartment' and 'polygon'."
            )
        network_gdf = twin._resolve_mesh_gdf(request.id_compartment, request.id_layer)
        verify_crs_match(
            network_gdf.crs,
            request.polygon_crs,
            context="mask(kind='boundary_hyd')",
        )
        id_col = twin._resolve_cell_id_col(request.id_compartment)
        classification = reaches_inflow_outflow_signs(
            network_gdf, request.polygon, id_col=id_col
        )
        boundary_ids = sorted(classification["boundary_ids"])
        id_col_name = (
            network_gdf.columns[id_col] if isinstance(id_col, int) else id_col
        )
        boundary_rows = network_gdf[network_gdf[id_col_name].isin(boundary_ids)]
        return HydBoundaryResponse(
            reach_ids=list(boundary_ids),
            geometries=list(boundary_rows.geometry),
            meta={
                "id_compartment": request.id_compartment,
                "kind":           request.kind,
                "inflow_ids":     list(classification["inflow_ids"]),
                "outflow_ids":    list(classification["outflow_ids"]),
                "internal_ids":   list(classification["internal_ids"]),
                "signs":          dict(classification["signs"]),
            },
        )

    if request.kind == "boundary_hyd_flux":
        if request.id_compartment is None or request.polygon is None:
            raise ValueError(
                "mask(kind='boundary_hyd_flux') requires both 'id_compartment' "
                "and 'polygon'."
            )
        if request.syear is None or request.eyear is None:
            raise ValueError(
                "mask(kind='boundary_hyd_flux') requires 'syear' and 'eyear' "
                "to read the discharge time series."
            )
        network_gdf = twin._resolve_mesh_gdf(request.id_compartment, request.id_layer)
        verify_crs_match(
            network_gdf.crs,
            request.polygon_crs,
            context="mask(kind='boundary_hyd_flux')",
        )
        id_col = twin._resolve_cell_id_col(request.id_compartment)
        classification = reaches_inflow_outflow_signs(
            network_gdf, request.polygon, id_col=id_col
        )
        boundary_ids = sorted(classification["boundary_ids"])
        signs = {cid: classification["signs"][cid] for cid in boundary_ids}

        q_response = twin.read_values(
            id_compartment=request.id_compartment,
            outtype="Q",
            param="discharge",
            syear=request.syear,
            eyear=request.eyear,
            id_layer=request.id_layer,
            cutsdate=request.cutsdate,
            cutedate=request.cutedate,
        )

        if not boundary_ids:
            Q = np.empty((0, q_response.data.shape[1]))
        else:
            Q = np.vstack(
                [q_response.data[cid - 1, :] * signs[cid] for cid in boundary_ids]
            )

        return HydBoundaryFluxResponse(
            reach_ids=boundary_ids,
            signs=signs,
            Q=Q,
            dates=q_response.dates,
            meta={
                "id_compartment": request.id_compartment,
                "id_layer":       request.id_layer,
                "outtype":        "Q",
                "param":          "discharge",
                "syear":          request.syear,
                "eyear":          request.eyear,
                "kind":           request.kind,
                "inflow_ids":     list(classification["inflow_ids"]),
                "outflow_ids":    list(classification["outflow_ids"]),
                "internal_ids":   list(classification["internal_ids"]),
            },
        )

    if request.kind == "boundary_aq":
        if request.id_compartment is None or request.polygon is None:
            raise ValueError(
                "mask(kind='boundary_aq') requires both 'id_compartment' and 'polygon'."
            )
        aq_mesh_gdf = twin._resolve_mesh_gdf(request.id_compartment, request.id_layer)
        verify_crs_match(
            aq_mesh_gdf.crs,
            request.polygon_crs,
            context="mask(kind='boundary_aq')",
        )
        id_col = twin._resolve_cell_id_col(request.id_compartment)
        cell_ids, edge_geometries = aq_cells_on_polygon_boundary(
            aq_mesh_gdf, request.polygon, id_col=id_col
        )
        return AqBoundaryResponse(
            cell_ids=list(cell_ids),
            edge_geometries=list(edge_geometries),
            meta={
                "id_compartment": request.id_compartment,
                "id_layer": request.id_layer,
                "kind": request.kind,
            },
        )

    if request.kind == "boundary_aq_flux":
        if request.id_compartment is None or request.polygon is None:
            raise ValueError(
                "mask(kind='boundary_aq_flux') requires both 'id_compartment' "
                "and 'polygon'."
            )
        if request.syear is None or request.eyear is None:
            raise ValueError(
                "mask(kind='boundary_aq_flux') requires 'syear' and 'eyear' "
                "to read the face-flux time series."
            )
        aq_mesh_gdf = twin._resolve_mesh_gdf(request.id_compartment, request.id_layer)
        verify_crs_match(
            aq_mesh_gdf.crs,
            request.polygon_crs,
            context="mask(kind='boundary_aq_flux')",
        )
        id_col = twin._resolve_cell_id_col(request.id_compartment)
        boundary_info = aq_cells_boundary_faces(
            aq_mesh_gdf, request.polygon, id_col=id_col
        )
        boundary_faces = boundary_info["boundary_faces"]

        face_data: Dict[str, np.ndarray] = {}
        dates: Optional[np.ndarray] = None
        for direction, param in AQ_FACE_DIRECTIONS.items():
            resp = twin.read_values(
                id_compartment=request.id_compartment,
                outtype="MB",
                param=param,
                syear=request.syear,
                eyear=request.eyear,
                id_layer=request.id_layer,
                cutsdate=request.cutsdate,
                cutedate=request.cutedate,
            )
            face_data[direction] = resp.data
            if dates is None:
                dates = resp.dates

        fluxes: Dict[Any, Dict[str, np.ndarray]] = {}
        for cell_id, directions in boundary_faces.items():
            fluxes[cell_id] = {
                direction: face_data[direction][cell_id - 1, :]
                for direction in directions
            }

        return AqBoundaryFluxResponse(
            cell_ids=sorted(boundary_faces.keys()),
            face_directions={cid: list(d) for cid, d in boundary_faces.items()},
            fluxes=fluxes,
            dates=dates,
            meta={
                "id_compartment": request.id_compartment,
                "id_layer":       request.id_layer,
                "outtype":        "MB",
                "syear":          request.syear,
                "eyear":          request.eyear,
                "kind":           request.kind,
                "interior_ids":   list(boundary_info["interior_ids"]),
            },
        )

    raise ValueError(f"Unknown mask kind: {request.kind!r}")


def transform(twin: "HydrologicalTwin", request: TransformRequest) -> Any:
    """Dispatch ladder for ``HydrologicalTwin.transform``."""
    if request.kind == "temporal_aggregation":
        return twin.apply_temporal_operator(
            arr=request.data,
            dates=request.dates,
            column_names=request.column_names,
            agg_dimension=request.agg_dimension,
            frequency=twin._normalize_frequency(request.frequency, target="long"),
            pluriennial=request.pluriannual,
            year_end_month=request.year_end_month,
        )

    if request.kind == "spatial_average":
        return twin.apply_spatial_average(
            id_compartment=request.id_compartment,
            data=request.data,
            operation=request.operation,
            areas=request.areas,
        )

    if request.kind == "criteria":
        bundle_dict = twin._bundle_response_to_dict(request.bundle or request.data)
        metrics = request.metrics

        per_point: List[Dict[str, Any]] = []
        all_sim: List[np.ndarray] = []
        all_obs: List[np.ndarray] = []
        by_layer_series: Dict[int, Dict[str, List[np.ndarray]]] = {}

        for point in bundle_dict.get("obs_points", []):
            criteria = point.get("criteria")
            if criteria is None:
                criteria = twin.compute_performance_stats(
                    sim=point["sim"],
                    obs=point["obs"],
                    metrics=metrics,
                )
            per_point.append(
                {
                    "name": point["name"],
                    "id_point": point.get("id_point"),
                    "id_layer": point["id_layer"],
                    "criteria": criteria,
                }
            )
            all_sim.append(point["sim"])
            all_obs.append(point["obs"])
            by_layer_series.setdefault(point["id_layer"], {"sim": [], "obs": []})
            by_layer_series[point["id_layer"]]["sim"].append(point["sim"])
            by_layer_series[point["id_layer"]]["obs"].append(point["obs"])

        global_metrics: Dict[str, Any] = {}
        if all_sim and all_obs:
            global_metrics = twin.compute_performance_stats(
                sim=np.concatenate(all_sim),
                obs=np.concatenate(all_obs),
                metrics=metrics,
            )

        by_layer = {
            layer_id: twin.compute_performance_stats(
                sim=np.concatenate(series["sim"]),
                obs=np.concatenate(series["obs"]),
                metrics=metrics,
            )
            for layer_id, series in by_layer_series.items()
        }

        return CriteriaResponse(
            per_point=per_point,
            global_metrics=global_metrics,
            by_layer=by_layer,
            meta={"metrics": metrics},
        )

    if request.kind == "budget":
        data = request.data
        if data is None:
            extracted = twin.fetch(
                request=FetchRequest(
                    kind="simulation_matrix",
                    id_compartment=request.id_compartment,
                    outtype="MB",
                    param=request.param,
                    syear=request.sdate,
                    eyear=request.edate,
                    cutsdate=request.cutsdate,
                    cutedate=request.cutedate,
                    id_layer=0,
                    target_unit="mm/j",
                )
            )
            data = extracted.data

        budget_data, date_labels, param_name = twin.compute_budget_variable(
            data=data,
            param=request.param,
            agg=request.agg_dimension,
            fz=twin._normalize_frequency(request.frequency, target="short"),
            sdate=request.sdate,
            edate=request.edate,
            cutsdate=request.cutsdate,
            cutedate=request.cutedate,
            pluriannual=request.pluriannual,
        )
        return BudgetComputationResponse(
            data=budget_data,
            date_labels=date_labels,
            param=param_name,
            meta={"frequency": request.frequency, "agg": request.agg_dimension},
        )

    if request.kind == "hydrological_regime":
        data = request.data
        dates = request.dates
        if data is None or dates is None:
            extracted = twin.fetch(
                request=FetchRequest(
                    kind="simulation_matrix",
                    id_compartment=request.id_compartment,
                    outtype=request.outtype or "Q",
                    param=request.param,
                    syear=request.sdate,
                    eyear=request.edate,
                    id_layer=0,
                )
            )
            data = extracted.data
            dates = extracted.dates

        regime_data, obs_point_names, month_labels = twin.compute_hydrological_regime(
            id_compartment=request.id_compartment,
            data=data,
            dates=dates,
            output_folder=twin.temp_directory or twin.out_caw_directory or "",
            output_name=(
                f"{module_caw.get(request.id_compartment, request.id_compartment)}_regime"
            ),
        )
        return HydrologicalRegimeResponse(
            data=regime_data,
            obs_point_names=obs_point_names,
            month_labels=month_labels,
            meta={"id_compartment": request.id_compartment, "param": request.param},
        )

    if request.kind == "runoff_ratio":
        qr_sim = twin.budget.calcSimRunoffRatio(
            surf_surf_area=request.surf_area,
            catch_surf_area=request.catch_surf_area,
            id_surf_mesh=request.id_surf,
            matrixRunOff=request.simmatrix_runoff,
            matrixRain=request.simmatrix_rain,
            matrixEtr=request.simmatrix_etr,
        )
        qr_obs = twin.budget.calcObsRunoffRatio(
            catch_surf_area=request.catch_surf_area,
            id_surf_mesh=request.id_surf,
            matrixRain=request.simmatrix_rain,
            Obsdata=request.obs_data,
        )
        return RunoffRatioResponse(
            simulated=qr_sim,
            observed=qr_obs,
            surface=float(sum(request.catch_surf_area or [])),
            meta={"id_compartment": request.id_compartment},
        )

    if request.kind == "aq_balance":
        aq_inputs = request.aq_inputs or request.data
        if isinstance(aq_inputs, AquiferBalanceInputsResponse):
            aq_inputs = aq_inputs.data
        if aq_inputs is None:
            raise ValueError("aq_balance transform requires aquifer inputs.")

        normalized_series = {
            label: twin._collapse_aq_series(values)
            for label, values in aq_inputs.items()
        }
        totals = {
            label: float(np.nansum(series))
            for label, series in normalized_series.items()
        }

        mass_balance = pd.DataFrame(
            [
                {"term": label, "value": value, "absolute_value": abs(value)}
                for label, value in totals.items()
            ]
        )

        flux_mapping = {
            "Recharge": ("Surface", "Aquifer"),
            "Riv": ("River", "Aquifer"),
            "Dirichlet": ("Boundary", "Aquifer"),
            "Neumann": ("Boundary", "Aquifer"),
            "Flux_top": ("Upper layer", "Aquifer"),
            "Flux_bot": ("Lower layer", "Aquifer"),
            "Uptake": ("Aquifer", "Abstraction"),
            "Overflow": ("Aquifer", "Surface"),
            "Stock": ("Aquifer", "Storage"),
            "Err": ("Aquifer", "Residual"),
        }
        flux = pd.DataFrame(
            [
                {
                    "term": label,
                    "source": source,
                    "target": target,
                    "value": abs(totals[label]),
                    "signed_value": totals[label],
                }
                for label, (source, target) in flux_mapping.items()
                if label in totals
            ]
        )

        return AquiferBalanceResponse(
            mass_balance=mass_balance,
            flux=flux,
            meta={"regime": request.regime or getattr(twin.config_proj, "regime", None)},
        )

    raise ValueError(f"Unknown transform kind: {request.kind!r}")


def render(twin: "HydrologicalTwin", request: RenderRequest) -> RenderResult:
    """Dispatch ladder for ``HydrologicalTwin.render``."""
    resolved_kind = {
        "budget": "budget_barplot",
        "regime": "hydrological_regime",
    }.get(request.kind, request.kind)

    if resolved_kind == "budget_barplot":
        artefacts = twin.render_budget_barplot(
            data_dict=request.data,
            plot_title=request.plot_title,
            output_folder=request.output_folder,
            output_name=request.output_name,
            yaxis_unit=request.yaxis_unit,
        )
    elif resolved_kind == "hydrological_regime":
        artefacts = twin.render_hydrological_regime(
            data=request.data,
            obs_point_names=request.obs_point_names,
            month_labels=request.month_labels,
            var=request.var,
            units=request.units,
            savepath=request.savepath,
            interactive=request.interactive,
            staticpng=request.staticpng,
            staticpdf=request.staticpdf,
            years=request.years,
        )
    elif resolved_kind == "sim_obs_pdf":
        artefacts = twin._render_sim_obs_pdf(
            id_compartment=request.id_compartment,
            outtype=request.outtype,
            param=request.param,
            simsdate=request.simsdate,
            simedate=request.simedate,
            plotstartdate=request.plotstartdate or request.plotstart,
            plotenddate=request.plotenddate or request.plotend,
            id_layer=request.id_layer,
            directory=request.directory,
            name_file=request.name_file,
            ylabel=request.ylabel,
            obs_unit=request.obs_unit,
            crit_start=request.crit_start,
            crit_end=request.crit_end,
            aggr=request.aggr,
        )
    elif resolved_kind == "aq_flux_diagram":
        artefacts = twin.render_aq_flux_diagram(
            tables=request.tables,
            output_folder=request.output_folder,
            output_name=request.output_name,
            colors=request.colors,
        )
    else:
        raise ValueError(f"Unknown render kind: {request.kind!r}")
    return RenderResult(artefacts=artefacts, meta={"kind": request.kind})
