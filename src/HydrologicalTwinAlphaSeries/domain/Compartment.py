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
#   Compartement object
#
# ***************************************************************************/

from os import sep
from typing import Protocol, Union

from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject
from HydrologicalTwinAlphaSeries.config.constants import module_caw, obs_types, out_caw_folder
from HydrologicalTwinAlphaSeries.domain.Extraction import Extraction
from HydrologicalTwinAlphaSeries.domain.Mesh import Mesh
from HydrologicalTwinAlphaSeries.domain.Observations import Observation


class GeoLayerProvider(Protocol):
    def get_layer(self, layer_name: str):
        ...


class Compartment:
    """
    CaWaQS compartment class. 
    
    .. NOTE:: 
        One compartment is initialized per CaWaQS compartment
    """
    def __init__(
        self,
        id_compartment: int,
        config_geom: ConfigGeometry,
        config_proj: ConfigProject,
        out_caw_directory: str,
        obs_directory: str,
        geo_provider: GeoLayerProvider
    ):
        """
        Constructor method

        :param id_compartment: ID of the compartment to be initialized
        :type id_compartment: int
        :param config_geom: Geometry configuration object
        :type config_geom: ConfigGeometry
        :param config_proj: Project configuration object
        :type config_proj: ConfigProject
        :param out_caw_directory: Directory of CaWaQs models for analysis
        :type out_caw_directory: str
        :param obs_directory: Observation data directory
        :type obs_directory: str
        :param geo_provider: Provider for GeoDataFrames (QGIS or file-based)
        :type geo_provider: GeoDataProvider
        """

        super().__init__()

        self.geo_provider = geo_provider
        print(f"\n\nBUILDING Compartment {module_caw[id_compartment]}", flush=True)
        self.id_compartment = id_compartment
        self.compartment = self.defineNameCompartement(id_compartment)
        self.layers_gis_names = self.defineLayerGisName(id_compartment, config_geom)
        self.out_caw_directory = out_caw_directory
        self.out_caw_path = self.defineOutCawPath(out_caw_directory, id_compartment)
        self.mesh = self.defineMeshCompartment(id_compartment, config_geom)
        self.hyd_corresp_missing = self.mesh.hyd_corresp_missing
        self.obs_path = obs_directory
        self.obs = self.defineObsCompartment(id_compartment, config_geom)
        self.extraction = self.defineExtCompartment(id_compartment, config_geom)
        self.regime = config_proj.regime

        print(f"{self.__repr__()}")
        print(f"{module_caw[self.id_compartment]} has been created")

    def __repr__(self):
        return f"\nCompartment {module_caw[self.id_compartment]} : \
            \n\t→ CaWaQS Outputs directory : {self.out_caw_path} \
            \n\t→ Meshes : {self.mesh}\
            \n\t\t: id abs = [{self.mesh.getIdMin()} : {self.mesh.getIdMax()}]\
            \n\t→ {self.obs} \
            \n\t→ Observation path : {self.obs_path}"

    def defineNameCompartement(self, id_compartment: int):
        """
        Define Compartment Name from compartment ID

        :param id_compartment: ID of the compartment to be initialized
        :type id_compartment: int
        :return: Compartment name
        """
        return module_caw[id_compartment]

    def defineLayerGisName(self, id_compartment:int, config:ConfigGeometry):
        """
        Define Gis Layer name attached to the compartment

        :param id_compartment: ID of the compartment to be initialized
        :type id_compartment: int
        :param config: Configuration object
        :type config: Config
        :return: A list of gis layer linked to the compartment
        """
        return [
            gis_layer
            for s_l in config.resolutionNames[id_compartment]
            for gis_layer in s_l
        ]

    def defineOutCawPath(self, out_caw_directory:str, id_compartment:int):
        """
        Definie path of outputs in CaWaQS outputs directory for the define compartment

        :param out_caw_directory: directory contaning all CaWaQS outputs for all compartments
        :type out_caw_directory: str
        :param id_compartment: compartment ids
        :type id_compartment: int
        :return: path of outputs in CaWaQS outputs directory of the compartment (ex : ../OUTPUT_AQ)
        """

        path_output_compartment = (
            out_caw_directory + sep + out_caw_folder[id_compartment] + sep
        )

        print(path_output_compartment)

        return path_output_compartment

    def defineMeshCompartment(self, id_compartment: int, config: ConfigGeometry) -> Mesh:
        """
        Build compartment mesh

        :param id_compartment: compartment ids
        :type id_compartment: int
        :param config: Geometry configuration
        :type config: ConfigGeometry
        :return: compartment mesh
        """
        # Get GeoDataFrames for each layer
        layer_gdfs = {
            layer_name: self.geo_provider.get_layer(layer_name)
            for layer_name in self.layers_gis_names
        }
        return Mesh(
            id_compartment, self.layers_gis_names, layer_gdfs, config, self.out_caw_directory
        )

    def defineObsCompartment(
        self, id_compartment: int, config: ConfigGeometry
    ) -> Union[Observation, None]:
        """
        Define Observation of the defined compartment

        :param id_compartment: compartment ids
        :type id_compartment: int
        :param config: Geometry configuration
        :type config: ConfigGeometry
        :return: observation object
        """
        if id_compartment in obs_types.keys() and id_compartment in config.obsNames.keys():
            print("\nBuilding observations...")
            # Get observation layer GeoDataFrame
            obs_layer_name = config.obsNames[id_compartment]
            obs_gdf = self.geo_provider.get_layer(obs_layer_name)
            # Get mesh layer GeoDataFrames for spatial queries
            mesh_gdfs = {
                layer_name: self.geo_provider.get_layer(layer_name)
                for layer_name in self.layers_gis_names
            }
            obs = Observation(
                id_compartment, id_compartment, config, self.out_caw_directory,
                obs_gdf, mesh_gdfs
            )
            print("Observations has been created")
            return obs

        else:
            print("Any observations for this compartment", flush=True)
            return None

    def defineExtCompartment(
        self, id_compartment: int, config: ConfigGeometry
    ) -> Union[Extraction, None]:
        """
        Define Extraction points of the defined compartment

        :param id_compartment: compartment id
        :type id_compartment: int
        :param config: Configuration object
        :type config: ConfigGeometry
        """

        if id_compartment in obs_types.keys() and id_compartment in config.extNames.keys():
            print("\nBuilding extractions...")
            # Get extraction layer GeoDataFrame
            ext_layer_name = config.extNames[id_compartment]
            ext_gdf = self.geo_provider.get_layer(ext_layer_name)
            # Get mesh layer GeoDataFrames for spatial queries
            mesh_gdfs = {
                layer_name: self.geo_provider.get_layer(layer_name)
                for layer_name in self.layers_gis_names
            }
            ext = Extraction(
                id_type=id_compartment,
                id_compartment=id_compartment,
                config=config,
                out_caw_directory=self.out_caw_directory,
                ext_gdf=ext_gdf,
                mesh_gdfs=mesh_gdfs
            )
            print("Extraction has been created")
            return ext

        else:
            print("Any extraction for this compartment", flush=True)
            return None
