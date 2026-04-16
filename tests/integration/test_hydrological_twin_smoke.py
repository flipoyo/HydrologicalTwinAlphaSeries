from HydrologicalTwinAlphaSeries import ConfigGeometry, ConfigProject, HydrologicalTwin


def test_hydrological_twin_can_be_constructed(tmp_path):
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
            "cawOutDirectory": str(tmp_path / "out"),
            "startSim": 2000,
            "endSim": 2001,
            "obsDirectory": str(tmp_path / "obs"),
            "regime": "annual",
        }
    )

    twin = HydrologicalTwin(
        config_geom=config_geom,
        config_proj=config_project,
        out_caw_directory=config_project.cawOutDirectory,
        obs_directory=config_project.obsDirectory,
        temp_directory=str(tmp_path / "temp"),
        metadata={"regime": config_project.regime},
    )

    assert twin.out_caw_directory == config_project.cawOutDirectory
    assert twin.temporal.__class__.__name__ == "Temporal"
    assert twin.list_compartments() == []
