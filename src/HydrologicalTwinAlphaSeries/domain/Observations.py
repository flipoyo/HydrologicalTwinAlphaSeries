import os
from typing import Dict, List, Union

import geopandas as gpd
import shapely

from HydrologicalTwinAlphaSeries.config.constants import (
    reversed_module_caw,
)
from HydrologicalTwinAlphaSeries.domain.Extraction import Extraction, ExtractionPoint
from HydrologicalTwinAlphaSeries.tools.spatial_utils import (
    get_nearest_cell,
    read_hyd_corresp_file,
)

sep = os.sep  # Ensure compatibility with different OS path separators


class ObsPoint(ExtractionPoint):
    """
    Observation Point Class

    :param id_cell: ID of the cell in the GIS layer
    :type id_cell: int
    :param id_point: ID of the observation point (optional)
    :type id_point: Union[str, None]
    :param geometry_point: Geometry of the observation point
    :type geometry_point: shapely.Point
    :param name: Name of the observation point
    :type name: str
    :param id_layer: ID of the GIS layer to which the observation point belongs
    :type id_layer: int
    :param id_mesh: ID of the mesh to which the observation point belongs
    :type id_mesh: int
    """
    def __init__(
        self,
        id_cell: int,
        id_point: Union[str, None],
        geometry_point: shapely.Point,
        name: str,
        id_layer: int,
        id_mesh: int,
    ):
        super().__init__(
            id_cell=id_cell,
            geometry_point=geometry_point,
            name=name,
            id_layer=id_layer,
            id_mesh=id_mesh
        )

        self.id_point = id_point  # id point : data file should have the same name as the id_cell
        self.obstimeserie = None
        self.simtimeserie = None
        print(self.__repr__())

    def __repr__(self):
        return (
            f"{self.name} : {self.id_point} (linked to cell {self.id_cell} "
            f"of layer {self.id_layer} of mesh {self.id_mesh})"
        )


class Observation(Extraction):
    """
    Observation Class

    .. NOTE:: An Observation class is present in each Compartment() being measured

    :param id_obs: ID of the observation type (e.g., discharge, water depth)
    :type id_obs: int
    :param id_compartment: ID of the compartment to which the observation belongs
    :type id_compartment: int
    :param config: Configuration object containing settings for the observation
    :type config: Config
    :param out_caw_directory: Directory for CaWaQS output files
    :type out_caw_directory: str
    :param obs_gdf: GeoDataFrame containing observation points
    :type obs_gdf: gpd.GeoDataFrame
    :param mesh_gdfs: Dictionary mapping layer names to mesh GeoDataFrames
    :type mesh_gdfs: Dict[str, gpd.GeoDataFrame]
    """
    def __init__(
        self,
        id_obs: int,
        id_compartment: int,
        config,
        out_caw_directory: str,
        obs_gdf: gpd.GeoDataFrame,
        mesh_gdfs: Dict[str, gpd.GeoDataFrame]
    ):
        self.id_type = id_obs
        self.id_compartment = id_compartment
        self.config = config
        self.out_caw_directory = out_caw_directory

        self.obs_gdf = obs_gdf
        self.crs = obs_gdf.crs           # pyproj.CRS or None — CRS of the observation point layer
        self.mesh_gdfs = mesh_gdfs

        self.obs_type = self.defineExtType()
        self.id_mesh = self.defineIdMesh()

        self.layer_gis_name = self.defineLayerGisName()
        self.out_caw_path = self.defineOutCawPath()
        self.obs_points = self.defineObsPoints(id_obs)
        self.n_obs = len(self.obs_points)

    def __repr__(self):
        return f"Observations points : {self.n_obs} {self.obs_type}(s)"

    def defineLayerGisName(self):
        """
        Extracts the GIS layer name for the observation type
        """
        return self.config.obsNames[self.id_compartment]

    def defineObsPoints(self, id_obs: int) -> List[ObsPoint]:
        """
        Defines the observation points based on the GeoDataFrame and observation type

        :param id_obs: ID of the observation type (1 for Piezometer, 2 for Station)
        :type id_obs: int
        :return: List of ObsPoint objects representing the observation points
        :rtype: List[ObsPoint]
        """
        id_obs = int(id_obs)
        config = self.config
        obs_points = []

        # Get column names/indices
        id_point_col = None
        if config.obsIdsColCells[id_obs] != '':
            id_point_col_idx = int(config.obsIdsColCells[id_obs])
            id_point_col = self.obs_gdf.columns[id_point_col_idx]

        name_col_idx = int(config.obsIdsColNames[id_obs])
        name_col = self.obs_gdf.columns[name_col_idx]

        layer_col = None
        if config.obsIdsColLayer[id_obs] is not None:
            layer_col_idx = int(config.obsIdsColLayer[id_obs])
            layer_col = self.obs_gdf.columns[layer_col_idx]

        cell_col = None
        if config.obsIdsCell[id_obs] is not None:
            cell_col_idx = int(config.obsIdsCell[id_obs])
            cell_col = self.obs_gdf.columns[cell_col_idx]

        for idx, row in self.obs_gdf.iterrows():
            id_point = row[id_point_col] if id_point_col is not None else None
            name_point = row[name_col]

            if layer_col is not None:
                id_layer = row[layer_col]
            else:
                id_layer = 0

            geometry_point = row.geometry

            # Define closer cell in layer in mesh
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
                obs_points.append(
                    ObsPoint(
                        id_cell=id_cell,
                        id_point=id_point,
                        geometry_point=geometry_point,
                        name=name_point,
                        id_layer=id_layer,
                        id_mesh=self.id_mesh
                    )
                )

        return obs_points
