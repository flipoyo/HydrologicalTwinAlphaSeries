"""Read-only views into ``HydrologicalTwin`` state.

Role
----
This module holds the *accessors*: module-level functions that read from a
``HydrologicalTwin`` instance (``twin``) and return derived views over its
compartments, layers, observations, and on-disk caches. They are the lowest
layer of the ``ht/developer/`` package — they depend only on twin state, not
on other developer-side modules.

What belongs here
-----------------
- ``get_compartment``, ``list_compartments``, ``get_compartment_info``
- ``get_layer_info``, ``get_all_layers``, ``get_observation_info``
- ``read_values``, ``read_observations``, ``read_sim_steady``, ``read_obs_steady``
- ``read_watbal_converted`` (hybrid read+convert kept with the readers)
- ``has_observations``
- ``_resolve_mesh_gdf``, ``_resolve_cell_id_col``, ``_resolve_layer_infos``
- ``_ensure_disk_cache`` (idempotent disk-cache provisioning; mutates
  ``twin._disk_cache`` — documented per-function)

What does NOT belong here
-------------------------
- Heavy computation (``compute_*``, ``aggregate_*``, ``_build_*_gdf``,
  ``extract_area``, ``apply_*``) → ``handlers.py``.
- Rendering (``render_*``) → ``handlers.py``.
- ``if request.kind == "X":`` ladders → ``dispatch.py``.
- Lifecycle state transitions or gatekeeping → ``hydrological_twin.py``.

Relation to other modules
-------------------------
- ``handlers.py`` imports from this module to read twin state.
- ``hydrological_twin.py`` keeps thin facade wrappers that delegate here.
- This module imports *nothing* from ``dispatch.py`` or ``handlers.py`` —
  the dependency arrow points the other way.

Import direction (no backward edges)
------------------------------------
    hydrological_twin.py → dispatch.py → handlers.py → accessors.py
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.config.constants import obs_config, paramRecs
from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
from HydrologicalTwinAlphaSeries.services.public.vec_operator import Operator

from .api_types import (
    CompartmentInfo,
    FetchRequest,
    InvalidStateError,
    LayerInfo,
    ObservationInfo,
    ObservationsResponse,
    ValuesResponse,
)

if TYPE_CHECKING:
    from .hydrological_twin import HydrologicalTwin  # noqa: F401


def get_compartment(twin: "HydrologicalTwin", id_compartment: int) -> Compartment:
    """Return a registered Compartment.

    Raises KeyError if the compartment was not registered at init time.
    """
    if id_compartment not in twin.compartments:
        raise KeyError(
            f"Compartment {id_compartment} is not registered. "
            f"Available: {list(twin.compartments.keys())}"
        )
    return twin.compartments[id_compartment]


def _resolve_mesh_gdf(
    twin: "HydrologicalTwin", id_compartment: int, id_layer: int = 0
) -> gpd.GeoDataFrame:
    """Return the mesh GeoDataFrame for a compartment's layer.

    Used by ``mask()`` kinds that operate on cell geometries.
    """
    compartment = get_compartment(twin, id_compartment)
    layer_name = compartment.mesh.layers_gis_name[id_layer]
    return compartment.mesh.layer_gdfs[layer_name]

def _resolve_cell_id_col(twin: "HydrologicalTwin", id_compartment: int) -> Union[str, int]:
    """Return the cell-id column (name or integer position) configured for a compartment.

    Reads ``config_geom.idColCells[id_compartment]``. Used by ``mask()``
    polygon kinds to tell ``cells_in_polygon`` which column carries cell ids.
    """
    if twin.config_geom is None:
        raise InvalidStateError(
            f"Cannot resolve cell-id column for compartment {id_compartment}: "
            "config_geom is not loaded."
        )
    id_col = twin.config_geom.idColCells.get(id_compartment)
    if id_col is None:
        raise ValueError(
            f"No cell-id column configured for compartment {id_compartment} in idColCells."
        )
    return id_col


def _resolve_layer_infos(
    twin: "HydrologicalTwin",
    id_compartment: int,
    request: FetchRequest,
) -> List[LayerInfo]:
    if request.layers is not None:
        return request.layers
    if request.layer_names:
        comp_info = twin.get_compartment_info(id_compartment)
        return [
            twin.get_layer_info(id_compartment, comp_info.layers_gis_names.index(layer_name))
            for layer_name in request.layer_names
        ]
    if request.id_layer == -9999:
        return twin.get_all_layers(id_compartment)
    return [twin.get_layer_info(id_compartment, request.id_layer)]


def get_compartment_info(twin: "HydrologicalTwin", id_compartment: int) -> CompartmentInfo:
    """Return a serializable snapshot of compartment metadata."""
    comp = twin.get_compartment(id_compartment)
    return CompartmentInfo(
        id_compartment=id_compartment,
        name=comp.compartment,
        layers_gis_names=list(comp.layers_gis_names),
        n_layers=len(comp.mesh.mesh),
        n_cells=comp.mesh.ncells,
        cell_ids=np.array(comp.mesh.getCellIdVector()),
        out_caw_path=comp.out_caw_path,
        regime=comp.regime,
    )


def list_compartments(twin: "HydrologicalTwin") -> List[CompartmentInfo]:
    """Return info for all registered compartments."""
    return [
        twin.get_compartment_info(cid)
        for cid in twin.compartments
    ]


def get_layer_info(twin: "HydrologicalTwin", id_compartment: int, id_layer: int) -> LayerInfo:
    """Return cell data for a specific mesh layer."""
    comp = twin.get_compartment(id_compartment)
    layer = comp.mesh.mesh[id_layer]
    return LayerInfo(
        id_layer=id_layer,
        n_cells=layer.ncells,
        cell_ids=np.array([cell.id for cell in layer.layer]),
        cell_areas=np.array([cell.area for cell in layer.layer]),
        cell_geometries=[cell.geometry for cell in layer.layer],
        layer_gis_name=comp.layers_gis_names[id_layer]
                       if id_layer < len(comp.layers_gis_names) else "",
        crs=layer.crs,
    )


def get_all_layers(twin: "HydrologicalTwin", id_compartment: int) -> List[LayerInfo]:
    """Return LayerInfo for every layer in a compartment's mesh."""
    comp = twin.get_compartment(id_compartment)
    return [
        twin.get_layer_info(id_compartment, lid)
        for lid in comp.mesh.mesh
    ]


def get_observation_info(
    twin: "HydrologicalTwin", id_compartment: int
) -> Optional[ObservationInfo]:
    """Return a serializable snapshot of observation metadata.

    Returns None if the compartment has no observations.
    """
    comp = twin.get_compartment(id_compartment)
    if comp.obs is None:
        return None
    obs = comp.obs
    return ObservationInfo(
        id_compartment=id_compartment,
        obs_type=obs.obs_type,
        n_points=obs.n_obs,
        layer_gis_name=obs.layer_gis_name,
        point_names=[p.name for p in obs.obs_points],
        point_ids=[p.id_point for p in obs.obs_points],
        cell_ids=[p.id_cell for p in obs.obs_points],
        layer_ids=[p.id_layer for p in obs.obs_points],
        geometries=[p.geometry for p in obs.obs_points],
        mesh_ids=[p.id_mesh for p in obs.obs_points],
    )


def read_values(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    syear: int,
    eyear: int,
    id_layer: int = 0,
    cutsdate: Optional[str] = None,
    cutedate: Optional[str] = None,
) -> ValuesResponse:
    """Extract simulated values for a given variable and period (NumPy version)."""

    comp = twin.get_compartment(id_compartment)

    sim_matrix = twin.temporal.load_from_cache(
        compartment=comp,
        outtype=outtype,
        param=param,
        syear=syear,
        eyear=eyear,
        temp_directory=twin.temp_directory or "",
    )

    start_date = datetime.strptime(f"{syear}-08-01", "%Y-%m-%d")
    end_date = datetime.strptime(f"{eyear}-08-01", "%Y-%m-%d")
    dates = np.arange(
        np.datetime64(start_date),
        np.datetime64(end_date),
        dtype='datetime64[D]'
    )
    if sim_matrix.shape[1] != len(dates):
        min_len = min(sim_matrix.shape[1], len(dates))
        sim_matrix = sim_matrix[:, :min_len]
        dates = dates[:min_len]

    if cutsdate is not None or cutedate is not None:
        d_start = np.datetime64(cutsdate) if cutsdate else dates[0]
        d_end = np.datetime64(cutedate) if cutedate else dates[-1]
        mask = (dates >= d_start) & (dates <= d_end)
        sim_matrix = sim_matrix[:, mask]
        dates = dates[mask]

    return ValuesResponse(
        data=sim_matrix,
        dates=dates,
        meta={
            "id_compartment": id_compartment,
            "outtype": outtype,
            "param": param,
            "syear": syear,
            "eyear": eyear,
            "id_layer": id_layer,
            "cutsdate": cutsdate,
            "cutedate": cutedate,
        },
    )


def read_observations(
    twin: "HydrologicalTwin",
    id_compartment: int,
    syear: int,
    eyear: int,
) -> ObservationsResponse:
    """Read observation data for all observation points of a compartment."""
    comp = twin.get_compartment(id_compartment)
    cfg = obs_config[id_compartment]

    result = twin.temporal.readObsData(
        compartment=comp,
        id_col_data=cfg["id_col_data"],
        id_col_time=cfg["id_col_time"],
        sdate=syear,
        edate=eyear,
    )

    if result is None:
        return ObservationsResponse(
            data=np.empty((0, 0)),
            dates=np.array([], dtype="datetime64[D]"),
            meta={
                "id_compartment": id_compartment,
                "syear": syear,
                "eyear": eyear,
                "obs_point_ids": [],
                "n_points": 0,
            },
        )

    data, dates, point_ids = result

    return ObservationsResponse(
        data=data,
        dates=dates,
        meta={
            "id_compartment": id_compartment,
            "syear": syear,
            "eyear": eyear,
            "obs_point_ids": point_ids,
            "n_points": len(point_ids),
        },
    )


def read_sim_steady(twin: "HydrologicalTwin", id_compartment: int) -> pd.DataFrame:
    """Read steady-state simulation data. Wraps Temporal.readSimSteady."""
    comp = twin.get_compartment(id_compartment)
    return twin.temporal.readSimSteady(comp)


def read_obs_steady(
    twin: "HydrologicalTwin",
    id_compartment: int,
    obs_aggr: Union[str, float],
    cutsdate: str = None,
    cutedate: str = None,
) -> pd.DataFrame:
    """Read steady-state observation data. Wraps Temporal.readObsSteady."""
    comp = twin.get_compartment(id_compartment)
    cfg = obs_config[id_compartment]
    return twin.temporal.readObsSteady(
        compartment=comp,
        id_col_time=cfg["id_col_time"],
        id_col_data=cfg["id_col_data"],
        obs_aggr=obs_aggr,
        cutsdate=cutsdate,
        cutedate=cutedate,
    )


def _ensure_disk_cache(twin: "HydrologicalTwin") -> None:
    """Materialise the on-disk ``.npy`` cache for every compartment and outtype.

    Mutates twin-side caches via ``twin.temporal.decode_and_cache`` (idempotent
    when the cache is already present).
    """
    if twin.config_proj is None:
        return
    syear = int(twin.config_proj.startSim)
    eyear = int(twin.config_proj.endsim)
    temp_directory = twin.temp_directory or twin.out_caw_directory or ""
    if not temp_directory:
        return

    for comp in twin.compartments.values():
        prefix = f"{comp.compartment}_"
        for key, params in paramRecs.items():
            if not key.startswith(prefix):
                continue
            if not params:
                continue
            outtype = key.split("_", 1)[1]
            if comp.regime == "Transient":
                bin_file = os.path.join(
                    comp.out_caw_path,
                    f"{comp.compartment}_{outtype}.{syear}{syear + 1}.bin",
                )
            else:
                bin_file = os.path.join(
                    comp.out_caw_path,
                    f"{comp.compartment}_{outtype}.00.bin",
                )
            if not os.path.exists(bin_file):
                continue
            twin.temporal.decode_and_cache(
                compartment=comp,
                outtype=outtype,
                syear=syear,
                eyear=eyear,
                temp_directory=temp_directory,
            )


def read_watbal_converted(
    twin: "HydrologicalTwin",
    id_compartment: int,
    outtype: str,
    param: str,
    syear: int,
    eyear: int,
    cutsdate: str = None,
    cutedate: str = None,
    id_layer: int = 0,
    target_unit: str = 'mm/j',
) -> ValuesResponse:
    """Extract watbal values with vectorized unit conversion.

    Combines read_values + Operator.convert_watbal_units.
    Returns ValuesResponse with converted data.
    """
    response = twin.read_values(
        id_compartment=id_compartment,
        outtype=outtype,
        param=param,
        syear=syear,
        eyear=eyear,
        id_layer=id_layer,
        cutsdate=cutsdate,
        cutedate=cutedate,
    )

    if target_unit != 'm3/s':
        layer_info = twin.get_layer_info(id_compartment, id_layer)
        cell_areas = np.array(layer_info.cell_areas)
        response.data = Operator.convert_watbal_units(
            data=response.data,
            cell_areas=cell_areas,
            target_unit=target_unit,
        )

    return response


def has_observations(twin: "HydrologicalTwin", id_compartment: int) -> bool:
    """Check if a compartment has observation data."""
    comp = twin.get_compartment(id_compartment)
    return comp.obs is not None
