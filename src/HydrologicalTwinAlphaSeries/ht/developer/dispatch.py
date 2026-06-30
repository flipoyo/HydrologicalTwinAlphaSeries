"""Per-verb ``kind=...`` routing for the dispatching micro-verbs.

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
  ``services/public/twin_io.py``.
- The 4 non-dispatching verbs (``configure``, ``load``, ``describe``,
  ``export``) — they are small and inline in the facade by design.

Relation to other modules
-------------------------
- ``hydrological_twin_developer.py`` calls into this module from the 4 dispatching
  facade methods.
- This module calls into ``handlers.py`` for the work.
- This module may call ``services/public/twin_io.py`` for incidental state reads, but
  the primary path is through ``handlers``.

Import direction (no backward edges)
------------------------------------
    L2: hydrological_twin_developer.py → dispatch.py → handlers.py
    L3: → services/public/twin_io.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.config.constants import AQ_FACE_DIRECTIONS, _LENGTH_UNITS, _LENGTH_UNIT_FACTORS, _VOLUMETRIC_UNITS, _VOLUMETRIC_UNIT_FACTORS, module_caw, _PARAM_NON_VOLUMETRIC_UNITS
from HydrologicalTwinAlphaSeries.services.public.polygon_mask import (
    cells_boundary_faces,
    cells_in_polygon,
    cells_in_polygon_weighted,
    reaches_in_polygon_carachterisation,
)
from HydrologicalTwinAlphaSeries.services.public.spatial import Spatial
from HydrologicalTwinAlphaSeries.tools.spatial_utils import reproject_polygon_to_match
from HydrologicalTwinAlphaSeries.services.public.twin_io import read_values, _resolve_cell_id_col, _resolve_mesh_gdf

from .api_types import (
    AssembleRequest,
    BoundaryAqLayersResult,
    BoundaryFluxResponse,
    AquiferBalanceInputsResponse,
    AquiferBalanceResponse,
    BudgetComputationResponse,
    CellSelectionResponse,
    CompartmentBundleResult,
    CriteriaResponse,
    ExportRequest,
    ExportResult,
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
    from .hydrological_twin_developer import HydrologicalTwin  # noqa: F401



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
        sim_matrix, dates = read_values(
            twin,
            id_compartment=request.id_compartment,
            outtype=request.outtype,
            param=request.param,
            syear=request.syear,
            eyear=request.eyear,
            id_layer=request.id_layer,
            cutsdate=request.cutsdate,
            cutedate=request.cutedate,
        )
        return ValuesResponse(
            data=sim_matrix,
            dates=dates,
            meta={
                "id_compartment": request.id_compartment,
                "outtype": request.outtype,
                "param": request.param,
                "syear": request.syear,
                "eyear": request.eyear,
                "id_layer": request.id_layer,
                "cutsdate": request.cutsdate,
                "cutedate": request.cutedate,
            },
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
            response = twin.fetch(
                kind="simulation_matrix",
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

        # can be removed long term if we enforce target_unit presence in the dialog and/or disallow weighted
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
        
        if request.param in _PARAM_NON_VOLUMETRIC_UNITS and request.target_unit in _VOLUMETRIC_UNITS:
            raise TypeError(
                f"mask(kind='area_values', param={request.param!r}, target_unit={request.target_unit!r}) is not valid: "
                f"param {request.param!r} is non-volumetric and cannot be converted to volumetric units like {request.target_unit!r}."
            )

        if request.target_unit in _LENGTH_UNITS and request.param not in _PARAM_NON_VOLUMETRIC_UNITS:
            raise TypeError(
                f"mask(kind='area_values', param={request.param!r}, target_unit={request.target_unit!r}) is not valid: "
                f"target_unit {request.target_unit!r} is a length unit but param {request.param!r} is not recognized as non-volumetric. "
            )

        weights: Optional[np.ndarray] = None
        clipped_geoms: Optional[List[Any]] = None
        if request.polygon is not None:
            # Resolution selector for AQ internal-values specs request the cross-layer outcropping mesh keyed on the global ``id_abs``;
            if request.resolution == "outcropping":
                mesh_gdf = twin._build_outcropping_mesh_gdf(request.id_compartment)
                id_col = "id_abs"
            # Resolution selector for HYD internal values has to follow thereaches mesh 
            else:
                mesh_gdf = _resolve_mesh_gdf(twin,request.id_compartment, request.id_layer)
                id_col = _resolve_cell_id_col(twin, request.id_compartment)
            request.polygon = reproject_polygon_to_match(
                request.polygon,
                request.polygon_crs,
                mesh_gdf.crs,
                context="mask(kind='area_values')",
            )
            if request.resolution == "reaches":
                # HYD reaches: select internal + boundary-crossing reaches. Call
                # the characterisation once, then materialise ids / weights /
                # clipped geometries in the SAME order so the three stay
                # row-aligned for the downstream cells-gdf assembly.
                reach_info = reaches_in_polygon_carachterisation(
                    mesh_gdf, request.polygon, id_col
                )
                resolved_cell_ids = reach_info["internal_and_boundary_ids"]
                weights = np.asarray(
                    [reach_info["weights"][cid] for cid in resolved_cell_ids],
                    dtype=np.float64,
                )
                clipped_geoms = [
                    reach_info["clipped_geometries"][cid]
                    for cid in resolved_cell_ids
                ]
            elif request.weighted and request.target_unit in _VOLUMETRIC_UNITS:
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
            if request.target_unit in _VOLUMETRIC_UNITS:
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
            elif request.target_unit in _LENGTH_UNITS:
                full_response = twin.fetch(
                    kind="simulation_matrix",
                    id_compartment=request.id_compartment,
                    outtype=request.outtype,
                    param=request.param,
                    syear=request.syear,
                    eyear=request.eyear,
                    cutsdate=request.cutsdate,
                    cutedate=request.cutedate,
                    id_layer=request.id_layer,
                )
                factor = _LENGTH_UNIT_FACTORS[request.target_unit]
                full_response.data = full_response.data * factor
            else: 
                raise ValueError(f"Unsupported target unit: {request.target_unit}, temporarily change the unit chosen. Dev: update the unit in the constant.py")
            # ``resolved_cell_ids`` are 1-based GLOBAL matrix indices: per-layer
            # GIS ids for WATBAL (where layer-0 ``id_abs == cell.id``, so the
            # arithmetic is byte-identical to before) and global ``id_abs`` for
            # the AQ outcropping resolver. Either way, id N lives at positional
            # row N-1 of the binary-ordered (getCellIdVector-order) values
            # array — correct for a cell in any layer, not just layer 0. The
            # 1-based ids stay as labels (meta + GeoPackage join); only the
            # positional lookup is shifted by -1.
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
        mesh_gdf = _resolve_mesh_gdf(twin, request.id_compartment, request.id_layer)
        request.polygon = reproject_polygon_to_match(
            request.polygon,
            request.polygon_crs,
            mesh_gdf.crs,
            context="mask(kind='polygon_cells')",
        )
        id_col = _resolve_cell_id_col(twin,request.id_compartment)
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
        network_gdf = _resolve_mesh_gdf(twin, request.id_compartment, request.id_layer)
        request.polygon = reproject_polygon_to_match(
            request.polygon,
            request.polygon_crs,
            network_gdf.crs,
            context="mask(kind='boundary_hyd')",
        )
        id_col = _resolve_cell_id_col(twin, request.id_compartment)
        classification = reaches_in_polygon_carachterisation(
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
        network_gdf = _resolve_mesh_gdf(twin, request.id_compartment, request.id_layer)
        request.polygon = reproject_polygon_to_match(
            request.polygon,
            request.polygon_crs,
            network_gdf.crs,
            context="mask(kind='boundary_hyd_flux')",
        )
        id_col = _resolve_cell_id_col(twin, request.id_compartment)
        classification = reaches_in_polygon_carachterisation(
            network_gdf, request.polygon, id_col=id_col
        )
        boundary_ids = sorted(classification["boundary_ids"])
        signs = {cid: classification["signs"][cid] for cid in boundary_ids}

        q_response = request.q_response
        if q_response is None:
            raise ValueError(
                "mask(kind='boundary_hyd_flux') requires 'q_response' to be "
                "pre-fetched by the caller and passed via MaskRequest."
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
        layers_to_scan = (
            request.id_layers if request.id_layers is not None else [request.id_layer]
        )
        all_face_directions: Dict[Any, List[str]] = {}
        all_edge_geometries: Dict[Any, Any] = {}
        cell_layer_ids: Dict[Any, int] = {}
        for lid in layers_to_scan:
            aq_mesh_gdf = _resolve_mesh_gdf(twin, request.id_compartment, lid)
            # Reproject once into this layer's mesh CRS. All AQ layers of one
            # compartment share a CRS, so we also advance request.polygon_crs to
            # the mesh CRS — on the next loop iteration the helper then sees a
            # matching CRS and no-ops, instead of re-reprojecting an already
            # reprojected polygon from the stale original polygon_crs.
            request.polygon = reproject_polygon_to_match(
                request.polygon,
                request.polygon_crs,
                aq_mesh_gdf.crs,
                context="mask(kind='boundary_aq')",
            )
            request.polygon_crs = aq_mesh_gdf.crs
            id_col = _resolve_cell_id_col(twin, request.id_compartment)
            boundary_faces, edge_geometries = cells_boundary_faces(
                aq_mesh_gdf, request.polygon, id_col=id_col
            )
            for cid, dirs in boundary_faces.items():
                if cid in all_face_directions:
                    raise ValueError(
                        f"mask(kind='boundary_aq'): cell_id {cid!r} appears in multiple "
                        f"layers of compartment {request.id_compartment} — cell_ids must "
                        "be globally unique across layers. Check the mesh configuration."
                    )
                # One cardinal face per cell maps to exactly one CaWaQS finite-
                # difference flux (flux_x/flux_y one/two via AQ_FACE_DIRECTIONS).
                # On a refined (quadtree) grid a cell may share one side with
                # several smaller outside neighbours, so deduplicate to the
                # distinct cardinal directions (insertion order preserved): the
                # geometry side already merges those same-side sub-edges into one
                # line per direction, and the flux side carries one net series per
                # direction — never N. ``cells_boundary_faces`` already returns
                # unique directions; this guard keeps the contract explicit and
                # robust if that ever changes.
                unique_dirs = list(dict.fromkeys(dirs))
                all_face_directions[cid] = unique_dirs
                all_edge_geometries[cid] = edge_geometries[cid]
                # ``lid`` is the only scope holding both this cell and its
                # aquifer layer; record the membership so downstream consumers
                # (e.g. assemble(kind="boundary_aq_layers")) can split the merged
                # boundary edges back into one surface per layer. The uniqueness
                # guard above makes this mapping single-valued by construction.
                cell_layer_ids[cid] = lid
        return BoundaryFluxResponse(
            cell_ids=list(all_face_directions.keys()),
            face_directions=all_face_directions,
            edge_geometries=all_edge_geometries,
            cell_layer_ids=cell_layer_ids,
            fluxes={},
            dates=None,
            meta={
                "id_compartment": request.id_compartment,
                "id_layers": layers_to_scan,
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
        # The boundary cells + their flux faces were already resolved across all
        # layers by the boundary_aq pass and threaded in via face_orientations;
        # reuse them rather than recomputing single-layer here.
        if request.face_orientations is None:
            raise ValueError(
                "mask(kind='boundary_aq_flux') requires 'face_orientations' "
                "(the boundary_aq response) to be passed via MaskRequest."
            )
        boundary_faces = request.face_orientations.face_directions

        if request.face_responses is None:
            raise ValueError(
                "mask(kind='boundary_aq_flux') requires 'face_responses' to be "
                "pre-fetched by the caller and passed via MaskRequest."
            )
        face_data: Dict[str, np.ndarray] = {}
        dates: Optional[np.ndarray] = None
        for direction in AQ_FACE_DIRECTIONS:
            resp = request.face_responses[direction]
            face_data[direction] = resp.data
            if dates is None:
                dates = resp.dates

        # CaWaQS stores ONE finite-difference flux per cardinal face per cell
        # (flux_x_one/two, flux_y_one/two → west/east/south/north via
        # AQ_FACE_DIRECTIONS). So a boundary cell yields exactly one net flux
        # series per *distinct* cardinal direction it borders — never N, even
        # when N smaller refined neighbours share that side. ``boundary_faces``
        # already carries the deduplicated directions (set via the boundary_aq
        # pass above); we deduplicate again here so this branch does not depend
        # on the caller having done so, and so the per-direction series is read
        # from CaWaQS exactly once (no silent dict-key overwrite, no double-read).
        fluxes: Dict[Any, Dict[str, np.ndarray]] = {}
        for cell_id, directions in boundary_faces.items():
            fluxes[cell_id] = {
                direction: face_data[direction][cell_id - 1, :]
                for direction in dict.fromkeys(directions)
            }

        return BoundaryFluxResponse(
            cell_ids=sorted(boundary_faces.keys()),
            # Unique directions per cell, 1:1 with the per-direction flux series
            # above — one cardinal face = one net CaWaQS flux.
            face_directions={
                cid: list(dict.fromkeys(d)) for cid, d in boundary_faces.items()
            },
            fluxes=fluxes,
            dates=dates,
            meta={
                "id_compartment": request.id_compartment,
                "id_layer":       request.id_layer,
                "outtype":        "MB",
                "syear":          request.syear,
                "eyear":          request.eyear,
                "kind":           request.kind,
                "cell_ids":       list(request.face_orientations.cell_ids),
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

    if request.kind == "volumetric_rescale":
        # Scale a raw CaWaQS ``m³/s`` flux array/series to ``request.target_unit``
        # by the single factor looked up in ``_VOLUMETRIC_UNIT_FACTORS``. This is
        # the one rescale both AQ-boundary output surfaces (loose CSV per-direction
        # series + GeoPackage per-cell net) call, so the two can never apply
        # different factors. ``request.data`` may be any type that broadcasts
        # against a scalar (np.ndarray, pandas Series, plain list-of-arrays sum) —
        # the factor multiplication is shape-agnostic. The unknown-token guard
        # surfaces a token-spelling drift immediately rather than silently
        # returning unscaled data.
        if request.target_unit not in _VOLUMETRIC_UNIT_FACTORS:
            raise ValueError(
                f"transform(kind='volumetric_rescale') got unknown target_unit="
                f"{request.target_unit!r}; expected one of "
                f"{sorted(_VOLUMETRIC_UNIT_FACTORS)}."
            )
        return request.data * _VOLUMETRIC_UNIT_FACTORS[request.target_unit]

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


def export(twin: "HydrologicalTwin", request: ExportRequest) -> ExportResult:
    """Dispatch ladder for ``HydrologicalTwin.export``.

    ``request.kind`` selects a **data file format**, never a semantic artefact
    and never an image. Each branch is a transparent pass-through to the
    privileged L3 writers in ``services/private/submodel_export.py`` — no
    reshaping, no fetch/transform. This is the single L2 gate point where the
    Tier-1 write import lives (see ``services/SECURITY.md``).
    """
    from ...services.private.submodel_export import (
        save_area_geopackage,
        save_area_values_npy,
    )

    if request.kind == "npy":
        # Tier-1 privileged write — see services/SECURITY.md.
        save_area_values_npy(request.path, request.data)
    elif request.kind == "geopackage":
        # Tier-1 privileged write — see services/SECURITY.md.
        save_area_geopackage(
            request.path,
            request.data,
            request.options["provenance_rows"],
            request.options["unit_override"],
            # Optional AQ-boundary per-cell faces map; absent for every other
            # caller, leaving their daily_values tables unchanged.
            request.options.get("daily_values_faces"),
        )
    else:
        raise ValueError(f"Unknown export kind: {request.kind!r}")
    return ExportResult(path=request.path, meta={"kind": request.kind})


def assemble(twin: "HydrologicalTwin", request: AssembleRequest) -> Any:
    """Dispatch ladder for ``HydrologicalTwin.assemble``.

    Routes ``kind="compartment_bundle"`` down to the pure L3 shaping function
    :func:`build_compartment_bundle`, then wraps its plain 4-tuple into the
    L2-owned :class:`CompartmentBundleResult` so L3 never names the result type.
    ``kind="boundary_aq_layers"`` routes the AQ boundary edges down to
    :func:`build_boundary_aq_layers` and wraps its plain ``[(id_layer, gdf), ...]``
    list — plus the flat per-cell ``{cell_id: faces_str}`` map it now returns —
    into the L2-owned :class:`BoundaryAqLayersResult`.
    ``assemble`` is shape-only — no disk write happens here.
    """
    from ...services.public.geodata_assembly import (
        build_boundary_aq_layers,
        build_compartment_bundle,
    )

    if request.kind == "compartment_bundle":
        gpkg_path, compartment_blocks, provenance_rows, unit_override = (
            build_compartment_bundle(
                compartment_blocks=request.compartment_blocks or {},
                output_dir=request.output_dir or "",
                area_name=request.area_name or "",
                label=request.label or "",
                syear=request.syear,
                eyear=request.eyear,
                polygon=request.polygon,
                polygon_crs=request.polygon_crs,
                weighted=request.weighted,
                source_run=request.source_run or "",
                provenance_extra=request.provenance_extra,
            )
        )
        return CompartmentBundleResult(
            gpkg_path=gpkg_path,
            compartment_blocks=compartment_blocks,
            provenance_rows=provenance_rows,
            unit_override=unit_override,
        )

    if request.kind == "boundary_aq_layers":
        entries, faces_by_cell = build_boundary_aq_layers(
            edge_geometries=request.edge_geometries or {},
            cell_layer_ids=request.cell_layer_ids or {},
            crs=request.crs,
            face_directions=request.face_directions or {},
        )
        return BoundaryAqLayersResult(
            entries=entries, faces_by_cell=faces_by_cell
        )

    raise ValueError(f"Unknown assemble kind: {request.kind!r}")
