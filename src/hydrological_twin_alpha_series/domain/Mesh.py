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
#   CaWaQS mesh class (QGIS-independent, uses GeoDataFrames)
#
# ***************************************************************************/

import os
from typing import Dict, List

import geopandas as gpd
import pandas as pd

from hydrological_twin_alpha_series.config.constants import reversed_module_caw

sep = os.sep  # Ensure compatibility with different OS path separators


class Mesh:
    """
    Mesh class

    .. NOTE:: A single Mesh() is an attribute of the Compartment class. The mesh attribute
        of the Mesh() class is a dictionary containing all the layers of the mesh,
        identified by a key from 0 to n (0 being the most recent layer in the case of the
        aquifer compartment).
    """

    def __init__(
        self,
        id_compartment: int,
        layers_gis_name: List[str],
        layer_gdfs: Dict[str, gpd.GeoDataFrame],
        config,
        out_caw_directory: str
    ):
        """
        Initialize the Mesh.

        :param id_compartment: Compartment ID
        :type id_compartment: int
        :param layers_gis_name: List of gis layer names needed to build mesh
        :type layers_gis_name: List[str]
        :param layer_gdfs: Dictionary mapping layer names to GeoDataFrames
        :type layer_gdfs: Dict[str, gpd.GeoDataFrame]
        :param config: configuration class
        :type config: ConfigGeometry
        :param out_caw_directory: CaWaQS output directory
        :type out_caw_directory: str
        """
        super().__init__()

        print("Building mesh")
        self.id_compartment = id_compartment
        self.layers_gis_name = layers_gis_name
        self.layer_gdfs = layer_gdfs
        self.config = config
        self.out_caw_directory = out_caw_directory
        self.mesh = self.GetMesh()
        self.ncells = self.getNCells()

    def __repr__(self):
        return f"{self.layers_gis_name} : {self.mesh}"

    def getNCells(self):
        """
        Get number of cells in mesh

        :return: number of cell in mesh
        :rtype: int
        """
        ncells = 0
        for layer in self.mesh.keys():
            ncells += self.mesh[layer].ncells

        return ncells

    @property
    def hyd_corresp_missing(self):
        return any(layer._hyd_corresp_missing for layer in self.mesh.values())

    def getIdMax(self):
        """
        Get Max cell id abs in layer
        """
        max_id_per_layer = []

        for id_lay, layer in self.mesh.items():
            max_id_per_layer.append(max([cell.id for cell in layer.layer]))

        return max(max_id_per_layer)

    def getIdMin(self):
        """
        Get Max cell id abs in layer
        """
        min_id = []

        for id_lay, layer in self.mesh.items():
            min_id.append(min([cell.id for cell in layer.layer]))

        return min(min_id)

    def getCellIdVector(self):
        """
        Return CaWaQS-ordered list of absolute cell IDs.

        This matches exactly the column order of CaWaQS simulation matrices.
        """
        ids = []
        for layer in self.mesh.values():          # layer order
            for cell in layer.layer:              # CaWaQS cell order
                ids.append(cell.id)
        return ids

    class Layer:
        """
        Layer class
        """
        def __init__(
            self,
            id_compartment: int,
            layer_gis_name: str,
            gdf: gpd.GeoDataFrame,
            config,
            out_caw_directory: str
        ):
            """
            Initialize the Layer.

            :param id_compartment: Compartment ID
            :type id_compartment: int
            :param layer_gis_name: Name of the GIS layer
            :type layer_gis_name: str
            :param gdf: GeoDataFrame containing the layer data
            :type gdf: gpd.GeoDataFrame
            :param config: Configuration object
            :param out_caw_directory: CaWaQS output directory
            :type out_caw_directory: str
            """
            self.id_compartment = id_compartment
            self.out_caw_directory = out_caw_directory
            self._hyd_corresp_missing = False
            self.crs = gdf.crs           # pyproj.CRS or None — stored before cells are built
            self.layer = self.buildLayer(layer_gis_name, gdf, config)
            self.ncells = len(self.layer)

        def __repr__(self):
            return f"Layer count {self.ncells} cells"

        class Cell:
            def __init__(self, id_compartment, id_cell, geometry, id_abs=None):
                self.id = id_cell  # id int of the cells
                self.id_abs = id_abs
                self.geometry = geometry  # shapely geometry
                self.area = geometry.area  # in meters (shapely uses .area property)

            def __repr__(self):
                return f"id : {self.id} ({round(self.area, 1) * 1e-4} ha)"

        def buildLayer(self, layer_gis_name: str, gdf: gpd.GeoDataFrame, config):
            """
            Build layer from GeoDataFrame.

            :param layer_gis_name: Name of the layer
            :type layer_gis_name: str
            :param gdf: GeoDataFrame containing the layer data
            :type gdf: gpd.GeoDataFrame
            :param config: Configuration object
            :return: List of Cell objects
            """
            n_col = config.idColCells[self.id_compartment]

            # Get column name from index or dict
            if isinstance(n_col, str):
                col_name = n_col
            elif isinstance(n_col, int):
                col_name = gdf.columns[n_col]
            elif isinstance(n_col, dict):
                n_col = n_col[layer_gis_name]
                if isinstance(n_col, int):
                    col_name = gdf.columns[n_col]
                else:
                    col_name = n_col
            else:
                col_name = gdf.columns[int(n_col)]

            layer = []
            print("Building layer ...", flush=True)

            if self.id_compartment != reversed_module_caw["HYD"]:
                for idx, row in gdf.iterrows():
                    id_cell = row[col_name]

                    if id_cell >= 0:
                        geometry_cell = row.geometry

                        layer.append(
                            self.Cell(self.id_compartment, id_cell, geometry_cell)
                        )

            else:
                try:
                    corr_file = self.readHydCorrespfile(self.out_caw_directory)
                    for idx, row in gdf.iterrows():
                        id_gis = row[col_name]
                        id_int = corr_file["ID_ABS"].loc[id_gis]
                        geometry_cell = row.geometry

                        layer.append(self.Cell(self.id_compartment, id_int, geometry_cell))

                except FileNotFoundError as e:
                    print(
                        f"WARNING: {e}\n"
                        "Falling back to GIS IDs for HYD mesh. "
                        "HYD simulation outputs (Q, H) will not be readable.",
                        flush=True,
                    )
                    self._hyd_corresp_missing = True
                    for idx, row in gdf.iterrows():
                        id_cell = row[col_name]
                        if id_cell >= 0:
                            geometry_cell = row.geometry
                            layer.append(
                                self.Cell(self.id_compartment, id_cell, geometry_cell)
                            )

            return layer

        def readHydCorrespfile(self, out_caw_directory):
            print(f"reading hyd corresp file : {out_caw_directory}")
            corresp_file_path = out_caw_directory + sep + "HYD_corresp_file.txt"
            if not os.path.isfile(corresp_file_path):
                raise FileNotFoundError(
                    f"File {corresp_file_path} not found. "
                    "Check your CaWaQS command file: either you didn't request any "
                    "HYDraulic outputs "
                    "(nor discharge, nor water depth) or you requested FORMATTED results that "
                    "CaWaQS-Viz doesn't handle yet. In the former case, request "
                    "UNFORMATTED outputs."
                )

            corr = pd.read_csv(corresp_file_path, index_col=2, sep=r"\s+")

            return corr

    def GetMesh(self):
        """
        Build mesh from GeoDataFrames

        :return: layers dictionary
        :rtype: dict
        """

        layers = {}

        for id_layer, layer_gis_name in enumerate(self.layers_gis_name):
            gdf = self.layer_gdfs[layer_gis_name]
            layers[id_layer] = self.Layer(
                self.id_compartment, layer_gis_name, gdf, self.config, self.out_caw_directory
            )
        return layers
