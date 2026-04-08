from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject


def test_config_models_from_dict():
    config_geom = ConfigGeometry.fromDict(
        {
            "ids_compartment": [1],
            "resolutionNames": {1: [["AQ_LAYER"]]},
            "ids_col_cell": {1: 0},
            "obsNames": {},
            "obsIdsColCells": {},
            "obsIdsColNames": {},
            "obsIdsColLayers": {},
            "obsIdsCell": {},
            "extNames": {},
            "extIdsColNames": {},
            "extIdsColLayers": {},
            "extIdsColCells": {},
        }
    )
    config_project = ConfigProject.fromDict(
        {
            "json_path_geometries": "geometry.json",
            "projectName": "demo",
            "cawOutDirectory": "/tmp/out",
            "startSim": 2000,
            "endSim": 2001,
            "obsDirectory": "/tmp/obs",
            "regime": "annual",
        }
    )

    assert config_geom.idCompartments == [1]
    assert config_project.projectName == "demo"
    assert config_project.ppDirectory.endswith("PostProcessing")