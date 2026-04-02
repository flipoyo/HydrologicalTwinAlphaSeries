"""REST views that expose HydrologicalTwin operations over HTTP.

Every view is a thin adapter: it delegates to the backend facade and
converts the response dataclasses (which may contain NumPy arrays) into
plain Python objects that Django REST Framework can serialise to JSON.
"""

from __future__ import annotations

import numpy as np
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from hydrological_twin_alpha_series import (
    ConfigGeometry,
    ConfigProject,
    HydrologicalTwin,
    __version__,
)

from . import twin_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _numpy_safe(obj):
    """Recursively convert NumPy types to JSON-friendly Python natives."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _numpy_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_numpy_safe(i) for i in obj]
    return obj


def _serialize_compartment_info(info):
    """Turn a CompartmentInfo dataclass into a plain dict."""
    return _numpy_safe({
        "id_compartment": info.id_compartment,
        "name": info.name,
        "layers_gis_names": info.layers_gis_names,
        "n_layers": info.n_layers,
        "n_cells": info.n_cells,
        "cell_ids": info.cell_ids,
        "out_caw_path": info.out_caw_path,
        "regime": info.regime,
    })


def _serialize_layer_info(info):
    """Turn a LayerInfo dataclass into a plain dict."""
    return _numpy_safe({
        "id_layer": info.id_layer,
        "n_cells": info.n_cells,
        "cell_ids": info.cell_ids,
        "cell_areas": info.cell_areas,
        "layer_gis_name": info.layer_gis_name,
        "crs": str(info.crs) if info.crs is not None else None,
    })


def _serialize_observation_info(info):
    """Turn an ObservationInfo dataclass into a plain dict."""
    return _numpy_safe({
        "id_compartment": info.id_compartment,
        "obs_type": info.obs_type,
        "n_points": info.n_points,
        "layer_gis_name": info.layer_gis_name,
        "point_names": info.point_names,
        "point_ids": info.point_ids,
        "cell_ids": info.cell_ids,
        "layer_ids": info.layer_ids,
        "mesh_ids": info.mesh_ids,
    })


def _require_twin():
    """Return the twin or an error Response."""
    twin = twin_store.get_twin()
    if twin is None:
        return None, Response(
            {"error": "Twin not initialised. POST to /api/init/ first."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return twin, None


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@api_view(["GET"])
def health(request: Request) -> Response:
    """Return service health and twin status."""
    twin = twin_store.get_twin()
    return Response({
        "status": "ok",
        "version": __version__,
        "twin_initialised": twin is not None,
    })


@api_view(["POST"])
def init_twin(request: Request) -> Response:
    """Initialise (or replace) the in-memory HydrologicalTwin.

    Expects a JSON body with the keys understood by
    ``ConfigGeometry.fromDict`` and ``ConfigProject.fromDict`` plus the
    directory paths needed by the ``HydrologicalTwin`` constructor::

        {
            "config_geom": { ... },
            "config_proj": { ... },
            "out_caw_directory": "/path/to/out",
            "obs_directory": "/path/to/obs",
            "temp_directory": "/path/to/temp"   // optional
        }
    """
    data = request.data

    required = ("config_geom", "config_proj", "out_caw_directory", "obs_directory")
    missing = [k for k in required if k not in data]
    if missing:
        return Response(
            {"error": f"Missing required fields: {missing}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        config_geom = ConfigGeometry.fromDict(data["config_geom"])
        config_proj = ConfigProject.fromDict(data["config_proj"])
        twin = HydrologicalTwin(
            config_geom=config_geom,
            config_proj=config_proj,
            out_caw_directory=data["out_caw_directory"],
            obs_directory=data["obs_directory"],
            temp_directory=data.get("temp_directory"),
            metadata=data.get("metadata"),
        )
        twin_store.set_twin(twin)
        return Response({"status": "initialised"}, status=status.HTTP_201_CREATED)
    except (KeyError, TypeError, ValueError):
        return Response(
            {"error": "Invalid configuration payload."},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
def list_compartments(request: Request) -> Response:
    """Return metadata for every registered compartment."""
    twin, err = _require_twin()
    if err:
        return err
    compartments = twin.list_compartments()
    return Response([_serialize_compartment_info(c) for c in compartments])


@api_view(["GET"])
def get_compartment(request: Request, id_compartment: int) -> Response:
    """Return metadata for a single compartment."""
    twin, err = _require_twin()
    if err:
        return err
    try:
        info = twin.get_compartment_info(id_compartment)
    except KeyError:
        return Response(
            {"error": f"Compartment {id_compartment} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(_serialize_compartment_info(info))


@api_view(["GET"])
def get_layers(request: Request, id_compartment: int) -> Response:
    """Return all layers for a compartment."""
    twin, err = _require_twin()
    if err:
        return err
    try:
        layers = twin.get_all_layers(id_compartment)
    except KeyError:
        return Response(
            {"error": f"Compartment {id_compartment} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response([_serialize_layer_info(layer) for layer in layers])


@api_view(["GET"])
def get_observations(request: Request, id_compartment: int) -> Response:
    """Return observation metadata for a compartment (or 204 if none)."""
    twin, err = _require_twin()
    if err:
        return err
    try:
        info = twin.get_observation_info(id_compartment)
    except KeyError:
        return Response(
            {"error": f"Compartment {id_compartment} not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if info is None:
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(_serialize_observation_info(info))
