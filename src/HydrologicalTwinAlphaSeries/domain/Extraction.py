#/***************************************************************************
# CaWaQSViz
#
# Description
#							 -------------------
#		begin				: 2023
#		git sha				: $Format:%H$
#		copyright			: (C) 2023 by Lise-Marie GIROD
#		email				: lise-marie.girod@minesparis.psl.eu
# ***************************************************************************/
#
#/***************************************************************************
# *																		    *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU General Public License as published by  *
# *   the Free Software Foundation; either version 2 of the License, or	    *
# *   any later version.								    				*
# *																		    *
# ***************************************************************************/
#   BREF
#
#   Class of hydrological variable extraction (QGIS-independent, uses GeoDataFrames)
#
# ***************************************************************************/

import os
from typing import Dict, List

import geopandas as gpd
import shapely

from HydrologicalTwinAlphaSeries.config.constants import (
    link_obs_mesh,
    obs_types,
    out_caw_folder,
    reversed_module_caw,
)
from HydrologicalTwinAlphaSeries.tools.spatial_utils import (
    get_nearest_cell,
    read_hyd_corresp_file,
)

sep = os.sep


class ExtractionPoint():
    """
    Extraction Point Class

    :param id_cell: ID of the cell in the GIS layer
    :type id_cell: int
    :param geometry_point: Geometry of the extraction point
    :type geometry_point: shapely.Point
    :param name: Name of the extraction point
    :type name: str
    :param id_layer: ID of the GIS layer to which the extraction point belongs
    :type id_layer: int
    :param id_mesh: ID of the mesh to which the extraction point belongs
    :type id_mesh: int
    """
    def __init__(
        self,
        id_cell: int,
        geometry_point: shapely.Point,
        name: str,
        id_layer: int,
        id_mesh: int,
    ):
        self.id_cell = id_cell
        self.geometry = geometry_point
        self.name = name
        self.id_mesh = id_mesh
        self.id_layer = id_layer

    def __repr__(self):
        return (
            f"Extraction Point ({self.name}) : linked to cell {self.id_cell} "
            f"of layer {self.id_layer} of mesh {self.id_mesh}"
        )


class Extraction():
    def __init__(
        self,
        id_type: int,
        id_compartment: int,
        config,
        out_caw_directory: str,
        ext_gdf: gpd.GeoDataFrame,
        mesh_gdfs: Dict[str, gpd.GeoDataFrame]
    ):
        """
        Extraction class constructor

        :param id_type: Type of extraction (e.g., discharge, water depth)
        :type id_type: int
        :param id_compartment: ID of the compartment to which the extraction belongs
        :type id_compartment: int
        :param config: Configuration object containing settings for the extraction
        :type config: Config
        :param out_caw_directory: Directory for CaWaQS output files
        :type out_caw_directory: str
        :param ext_gdf: GeoDataFrame containing extraction points
        :type ext_gdf: gpd.GeoDataFrame
        :param mesh_gdfs: Dictionary mapping layer names to mesh GeoDataFrames
        :type mesh_gdfs: Dict[str, gpd.GeoDataFrame]
        """

        self.id_type = id_type
        self.ext_type = self.defineExtType()

        self.id_compartment = id_compartment
        self.id_mesh = self.defineIdMesh()
        self.config = config
        self.out_caw_directory = out_caw_directory

        self.ext_gdf = ext_gdf
        self.mesh_gdfs = mesh_gdfs

        self.layer_name = self.defineLayerGisName()
        self.out_caw_path = self.defineOutCawPath()
        self.ext_point = self.defineExtPoints()

        self.n_ext_points = len(self.ext_point)

    def __repr__(self):
        return f"Extraction points : {self.n_ext_points} {self.ext_type}(s)"

    def defineExtType(self):
        """
        Extraction of the type of extraction method (1 : piezo, 2 : station)
        """
        return obs_types[self.id_type]

    def defineIdMesh(self):
        """
        Definition of the mesh id for the extraction type method
        """
        return link_obs_mesh[self.id_type]

    def defineLayerGisName(self):
        """
        Definition of the GIS layer name for the extraction type method
        """
        return self.config.extNames[self.id_compartment]

    def defineOutCawPath(self):
        """
        Definition of the output path in the CaWaQS output directory for the extraction type method
        """
        return out_caw_folder[self.id_compartment]

    def defineExtPoints(self) -> List[ExtractionPoint]:
        """
        Definition of the extraction points method

        :return: list of ExtractionPoint
        :rtype: list[ExtractionPoint]
        """
        id_compartment = self.id_compartment
        extPoints = []

        # Get column name for point names
        name_col_idx = int(self.config.extIdsColNames[id_compartment])
        name_col = self.ext_gdf.columns[name_col_idx]

        # Get column for layer id if specified
        layer_col = None
        if self.config.extIdsColLayer[id_compartment] is not None:
            layer_col_idx = int(self.config.extIdsColLayer[id_compartment])
            layer_col = self.ext_gdf.columns[layer_col_idx]

        # Get column for cell id if specified
        cell_col = None
        if self.config.extIdsCell[id_compartment] is not None:
            cell_col_idx = int(self.config.extIdsCell[id_compartment])
            cell_col = self.ext_gdf.columns[cell_col_idx]

        for idx, row in self.ext_gdf.iterrows():
            name_point = row[name_col]

            if layer_col is not None:
                id_layer = row[layer_col]
            else:
                id_layer = 0

            geometry_point = row.geometry

            # Define cell id
            if cell_col is not None:
                print('Define Cell id from dbf')
                id_cell = row[cell_col]

                if self.id_compartment == reversed_module_caw['HYD']:
                    try:
                        corr = read_hyd_corresp_file(self.out_caw_directory)
                        id_cell = corr["ID_ABS"].loc[id_cell]
                    except FileNotFoundError:
                        pass  # keep GIS id_cell as-is
            else:
                print('Define Cell id from closer cell function')
                # Get the mesh layer and find nearest cell
                layer_name = self.config.resolutionNames[self.id_compartment][0][id_layer]
                mesh_gdf = self.mesh_gdfs[layer_name]
                id_col = self.config.idColCells[self.id_compartment]
                if isinstance(id_col, dict):
                    id_col = id_col[layer_name]

                id_cell = get_nearest_cell(geometry_point, mesh_gdf, id_col)

                if id_cell is not None and self.id_compartment == reversed_module_caw["HYD"]:
                    try:
                        corr = read_hyd_corresp_file(self.out_caw_directory)
                        id_cell = corr["ID_ABS"].loc[id_cell]
                    except FileNotFoundError:
                        pass  # keep GIS id_cell as-is

            if id_cell is not None:
                extPoints.append(
                    ExtractionPoint(
                        id_cell=id_cell,
                        geometry_point=geometry_point,
                        name=name_point,
                        id_layer=id_layer,
                        id_mesh=self.id_compartment
                    )
                )
            else:
                print(f"Cell not found for {name_point} in {self.layer_name} layer")

        return extPoints
