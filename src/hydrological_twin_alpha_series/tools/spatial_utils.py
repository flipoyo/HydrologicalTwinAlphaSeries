# /***************************************************************************
# CaWaQSViz
#
# Description
# -------------------
# begin				: 2023
# git sha				: $Format:%H$
# copyright			: (C) 2023 by Lise-Marie GIROD
# email				: lise-marie.girod@minesparis.psl.eu
# ***************************************************************************/
#
# /***************************************************************************
# *																		    *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU General Public License as published by  *
# *   the Free Software Foundation; either version 2 of the License, or	    *
# *   any later version.								    				*
# *																		    *
# ***************************************************************************/
#   BREF
#
#   Shared spatial utilities for the backend (QGIS-independent).
#   Contains common functions for spatial operations using shapely, scipy, and geopandas.
#
# ***************************************************************************/

import os
from typing import Dict, List, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from shapely.ops import unary_union

sep = os.sep


class SpatialIndex:
    """
    Cached spatial index for efficient nearest neighbor queries.

    Build the KDTree once and reuse it for multiple queries.
    """

    def __init__(self, gdf: gpd.GeoDataFrame):
        """
        Initialize spatial index from a GeoDataFrame.

        :param gdf: GeoDataFrame to index
        :type gdf: gpd.GeoDataFrame
        """
        self.gdf = gdf
        self._tree = None
        self._centroids = None

        if not gdf.empty:
            self._centroids = np.array([[g.centroid.x, g.centroid.y] for g in gdf.geometry])
            self._tree = cKDTree(self._centroids)

    def get_nearest_idx(self, point_geom: shapely.Point) -> Union[int, None]:
        """
        Get the index of the nearest feature to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :return: Index into the GeoDataFrame of the nearest feature
        :rtype: Union[int, None]
        """
        if self._tree is None:
            return None

        query_point = np.array([[point_geom.centroid.x, point_geom.centroid.y]])
        _, idx = self._tree.query(query_point, k=1)
        return idx[0]

    def get_nearest_cell_id(
        self, point_geom: shapely.Point, id_col: Union[str, int]
    ) -> Union[int, None]:
        """
        Get the cell ID of the nearest feature to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :param id_col: Column name or index for the cell ID
        :type id_col: Union[str, int]
        :return: ID of the nearest cell
        :rtype: Union[int, None]
        """
        idx = self.get_nearest_idx(point_geom)
        if idx is None:
            return None

        # Resolve column name if given as index
        if isinstance(id_col, int):
            id_col = self.gdf.columns[id_col]

        return self.gdf.iloc[idx][id_col]

    def get_nearest_row(self, point_geom: shapely.Point) -> Union[pd.Series, None]:
        """
        Get the full row of the nearest feature to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :return: Row from GeoDataFrame of the nearest feature
        :rtype: Union[pd.Series, None]
        """
        idx = self.get_nearest_idx(point_geom)
        if idx is None:
            return None
        return self.gdf.iloc[idx]

    def get_nearest_k_indices(
        self, point_geom: shapely.Point, k: int = 1
    ) -> Union[np.ndarray, None]:
        """
        Get indices of the k nearest features to a point.

        :param point_geom: Query point geometry
        :type point_geom: shapely.Point
        :param k: Number of nearest neighbors
        :type k: int
        :return: Array of indices into the GeoDataFrame
        :rtype: Union[np.ndarray, None]
        """
        if self._tree is None:
            return None

        query_point = np.array([[point_geom.centroid.x, point_geom.centroid.y]])
        _, indices = self._tree.query(query_point, k=k)
        return indices


# Cache for spatial indices (key: id(gdf))
_spatial_index_cache: Dict[int, SpatialIndex] = {}


def get_spatial_index(gdf: gpd.GeoDataFrame) -> SpatialIndex:
    """
    Get or create a cached spatial index for a GeoDataFrame.

    :param gdf: GeoDataFrame to index
    :type gdf: gpd.GeoDataFrame
    :return: Cached SpatialIndex for the GeoDataFrame
    :rtype: SpatialIndex
    """
    gdf_id = id(gdf)
    if gdf_id not in _spatial_index_cache:
        _spatial_index_cache[gdf_id] = SpatialIndex(gdf)
    return _spatial_index_cache[gdf_id]


def clear_spatial_index_cache() -> None:
    """Clear the spatial index cache."""
    _spatial_index_cache.clear()


def get_nearest_cell(
    point_geom: shapely.Point, mesh_gdf: gpd.GeoDataFrame, id_col: Union[str, int]
) -> Union[int, None]:
    """
    Find the nearest cell to a point using cached spatial index.

    :param point_geom: Geometry of the point to search from
    :type point_geom: shapely.Point
    :param mesh_gdf: GeoDataFrame containing mesh cells
    :type mesh_gdf: gpd.GeoDataFrame
    :param id_col: Column name or index for the cell ID
    :type id_col: Union[str, int]
    :return: ID of the nearest cell, or None if mesh is empty
    :rtype: Union[int, None]
    """
    spatial_idx = get_spatial_index(mesh_gdf)
    return spatial_idx.get_nearest_cell_id(point_geom, id_col)


def get_nearest_row(point_geom: shapely.Point, gdf: gpd.GeoDataFrame) -> Union[pd.Series, None]:
    """
    Find the nearest feature row to a point using cached spatial index.

    :param point_geom: Geometry of the point to search from
    :type point_geom: shapely.Point
    :param gdf: GeoDataFrame to search
    :type gdf: gpd.GeoDataFrame
    :return: Row of the nearest feature, or None if empty
    :rtype: Union[pd.Series, None]
    """
    spatial_idx = get_spatial_index(gdf)
    return spatial_idx.get_nearest_row(point_geom)


def read_hyd_corresp_file(out_caw_directory: str) -> pd.DataFrame:
    """
    Read the hydraulic correspondence file.

    :param out_caw_directory: Directory where the CaWaQS output files are stored
    :type out_caw_directory: str
    :return: DataFrame containing the correspondence data
    :rtype: pd.DataFrame
    :raises FileNotFoundError: If the correspondence file is not found
    """
    print(f"reading hyd corresp file : {out_caw_directory}")
    corresp_file_path = out_caw_directory + sep + "HYD_corresp_file.txt"
    if not os.path.isfile(corresp_file_path):
        raise FileNotFoundError(
            f"File {corresp_file_path} not found. "
            "Check your CaWaQS command file: either you didn't request any HYDraulic outputs "
            "(nor discharge, nor water depth) or you requested FORMATTED results that "
            "CaWaQS-Viz doesn't handle yet. In the former case, request UNFORMATTED outputs."
        )

    corr = pd.read_csv(corresp_file_path, index_col=2, sep=r"\s+")
    return corr


def combine_geometries(geometries: List[shapely.Geometry]) -> shapely.Geometry:
    """
    Merge multiple geometries into a single geometry.

    This replaces the QGIS-dependent combineGeometries function.

    :param geometries: List of shapely geometries to merge
    :type geometries: List[shapely.Geometry]
    :return: Merged geometry
    :rtype: shapely.Geometry
    """
    return unary_union(geometries)


class CRSMismatchError(ValueError):
    """Raised by verify_crs_match when two defined CRS are incompatible.

    Inherits from ValueError for backwards compatibility, but is a distinct
    type so callers can catch it without accidentally swallowing unrelated
    ValueError exceptions (e.g. from rendering libraries).
    """


def verify_crs_match(crs_a, crs_b, context: str = "") -> None:
    """
    Raise CRSMismatchError if two CRS values are defined and incompatible.

    Passes silently when either CRS is None (undetermined — cannot verify).
    Raises with a descriptive message when both are defined but differ.

    Backend spatial operations that join two datasets MUST call this before
    the join so that CRS mismatches surface as explicit errors rather than
    silently wrong spatial results.

    :param crs_a: First CRS (pyproj.CRS, EPSG string, or None)
    :param crs_b: Second CRS (pyproj.CRS, EPSG string, or None)
    :param context: Operation name included in the error message
    :raises CRSMismatchError: If both CRS are defined and do not match
    """
    if crs_a is None or crs_b is None:
        return  # one side unknown — cannot verify, pass silently
    if crs_a != crs_b:
        ctx = f" in {context}" if context else ""
        raise CRSMismatchError(
            f"CRS mismatch{ctx}: {crs_a} vs {crs_b}. "
            "Reproject one layer to match the other before this operation."
        )


def reproject_to_match(
    gdf: gpd.GeoDataFrame,
    target_crs,
    context: str = "",
) -> gpd.GeoDataFrame:
    """
    Reproject a GeoDataFrame to a target CRS.

    Raises explicitly when the target CRS is None, because silently returning
    an un-reprojected GDF would hide the misconfiguration.

    :param gdf: GeoDataFrame to reproject
    :param target_crs: Target CRS (pyproj.CRS, EPSG string, or None)
    :param context: Operation name included in the error message
    :return: Reprojected GeoDataFrame (new object), or original if already matching
    :rtype: gpd.GeoDataFrame
    :raises ValueError: If target_crs is None
    """
    if target_crs is None:
        ctx = f" for {context}" if context else ""
        raise ValueError(
            f"Cannot reproject{ctx}: target CRS is None. The reference layer has no CRS defined."
        )
    if gdf.crs == target_crs:
        return gdf
    return gdf.to_crs(target_crs)
