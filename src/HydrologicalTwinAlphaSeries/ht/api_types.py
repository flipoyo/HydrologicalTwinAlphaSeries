from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class ExtractValuesResponse:
    """Response of HydrologicalTwin.extract_values.

    Attributes
    ----------
    data : np.ndarray
        Extracted data as a NumPy array.
    dates : np.ndarray
        Corresponding dates as a NumPy array.
    meta : Optional[Dict[str, Any]]
        Additional metadata about the extraction.
    """
    data: np.ndarray  # Changed from pd.DataFrame
    dates: np.ndarray  # Add dates array
    meta: Optional[Dict[str, Any]] = None


@dataclass
class TemporalOpResponse:
    data: np.ndarray
    date_labels: np.ndarray
    meta: Optional[Dict[str, Any]] = None

@dataclass
class SpatialAverageResponse:
    """Response from spatial averaging operation."""
    data: np.ndarray  # 1D array (n_timesteps,)
    meta: dict

@dataclass
class ObservationsResponse:
    """Response from reading observation data.

    Attributes
    ----------
    data : np.ndarray
        Observation measurements, shape (n_points, n_timesteps).
        May contain NaN for missing observations.
    dates : np.ndarray
        Datetime64 array (n_timesteps,).
    meta : Optional[Dict[str, Any]]
        Additional metadata (e.g., id_compartment, obs_point_ids, period).
    """
    data: np.ndarray
    dates: np.ndarray
    meta: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Model Layer responses
# ---------------------------------------------------------------------------

@dataclass
class CompartmentInfo:
    """Serializable snapshot of compartment metadata."""
    id_compartment: int
    name: str
    layers_gis_names: List[str]
    n_layers: int
    n_cells: int
    cell_ids: np.ndarray
    out_caw_path: str
    regime: str


@dataclass
class LayerInfo:
    """Serializable snapshot of a single mesh layer."""
    id_layer: int
    n_cells: int
    cell_ids: np.ndarray
    cell_areas: np.ndarray
    cell_geometries: list
    layer_gis_name: str
    crs: Any = None  # pyproj.CRS or None


# ---------------------------------------------------------------------------
# Data Layer responses
# ---------------------------------------------------------------------------

@dataclass
class ObservationInfo:
    """Serializable snapshot of observation metadata for a compartment."""
    id_compartment: int
    obs_type: str
    n_points: int
    layer_gis_name: str
    point_names: List[str]
    point_ids: list
    cell_ids: List[int]
    layer_ids: List[int]
    geometries: list
    mesh_ids: List[int]
