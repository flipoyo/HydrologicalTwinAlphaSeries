import json
import os
from os import sep

from HydrologicalTwinAlphaSeries.config.constants import module_caw
from HydrologicalTwinAlphaSeries.config.factory import FactoryClass


class Config(FactoryClass):
    def __init__(self, a_dict: dict):
        self.a_dict = a_dict

    def writeJsonConfig(self, jsonPath: str):
        os.makedirs(os.path.dirname(jsonPath), exist_ok=True)
        with open(jsonPath, "w", encoding="utf-8") as json_file:
            json.dump(self.a_dict, json_file, ensure_ascii=False, indent=4)

    def reverseDict(self, dict_to_reverse: dict):
        return {value: key for key, value in dict_to_reverse.items()}


class ConfigGeometry(Config):
    def __init__(self, a_dict: dict):
        super(ConfigGeometry, self).__init__(a_dict)

        self.idCompartments = a_dict["ids_compartment"]
        self.resolutionNames = a_dict["resolutionNames"]
        self.idColCells = a_dict["ids_col_cell"]

        self.obsNames = a_dict["obsNames"]
        self.obsIdsColCells = a_dict["obsIdsColCells"]
        self.obsIdsColNames = a_dict["obsIdsColNames"]
        self.obsIdsColLayer = a_dict["obsIdsColLayers"]
        self.obsIdsCell = a_dict["obsIdsCell"]

        self.extNames = a_dict["extNames"]
        self.extIdsColNames = a_dict["extIdsColNames"]
        self.extIdsColLayer = a_dict["extIdsColLayers"]
        self.extIdsCell = a_dict["extIdsColCells"]

    def __repr__(self):
        return f"\nGEOMETRIES CONFIG : \n\
            Compartments : {[module_caw[id_c] for id_c in self.idCompartments]}\n\
            MESH CONFIG : \n\
                \tLayers gis names : {[res for res in self.resolutionNames.values()]}\n\
                \tId of col in dfb containing cells ids : {self.idColCells}\n\
            OBS CONFIG :\n\
                \tLayer gis names : {self.obsNames}\n\
                \tId of col in dfb containing mps ids : {self.obsIdsColCells}\n\
                \tId of col in dfb containing mps names : {self.obsIdsColNames}\n\
                \tId of col in dfb containing mps aq layer : {self.obsIdsColLayer}\n\
                \tId of col in dbf containing mps linked cell in mesh : {self.obsIdsCell}\n\
                "


class ConfigProject(Config):
    def __init__(self, a_dict):
        super(ConfigProject, self).__init__(a_dict)
        self.json_path_geometries = a_dict["json_path_geometries"]
        self.projectName = a_dict["projectName"]
        self.cawOutDirectory = a_dict["cawOutDirectory"]
        self.startSim = a_dict["startSim"]
        self.endsim = a_dict["endSim"]
        self.obsDirectory = a_dict["obsDirectory"]
        self.ppDirectory = a_dict["cawOutDirectory"] + sep + "PostProcessing"
        self.regime = a_dict["regime"]

    def __repr__(self):
        return f"\
                \nPROJECT CONFIG : \n\
                \nProject Name : {self.projectName}\
                \nDirectory of CaWaQS output : {self.cawOutDirectory}\
                \nDirectory of Observation data : {self.obsDirectory}\
                \nPost-Process directory : {self.ppDirectory}\
                "