"""End-to-end macro-API smoke test on the cwv-gis-testcase fixture.

Asserts only that the pipeline runs without crashing and that a PNG is
produced. No numerical assertions. See tests/README.md for context and
local-run instructions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import geopandas as gpd
import pytest

from HydrologicalTwinAlphaSeries import (
    ConfigGeometry,
    ConfigProject,
    HydrologicalTwin,
)

FIXTURE_ENV_VAR = "CWAQS_FIXTURE_ROOT"


class _SmokeGeoProvider:
    """Minimal duck-typed geo provider for the smoke test.

    Satisfies the only attribute HydrologicalTwin.load needs:
    ``get_layer(layer_name) -> GeoDataFrame``.
    """

    def __init__(self, layer_paths: Dict[str, str]) -> None:
        self._layer_paths = dict(layer_paths)
        self._cache: Dict[str, gpd.GeoDataFrame] = {}

    def get_layer(self, layer_name: str) -> gpd.GeoDataFrame:
        if layer_name in self._cache:
            return self._cache[layer_name]
        if layer_name not in self._layer_paths:
            raise ValueError(
                f"No file path configured for layer '{layer_name}'. "
                f"Available: {sorted(self._layer_paths)}"
            )
        gdf = gpd.read_file(self._layer_paths[layer_name])
        self._cache[layer_name] = gdf
        return gdf


def test_cwv_gis_smoke(tmp_path: Path) -> None:
    fixture_root_str = os.environ.get(FIXTURE_ENV_VAR)
    if not fixture_root_str:
        pytest.skip(
            f"{FIXTURE_ENV_VAR} is not set. "
            "See tests/README.md for how to run this test locally."
        )
    fixture_root = Path(fixture_root_str).resolve()
    if not fixture_root.is_dir():
        pytest.skip(
            f"{FIXTURE_ENV_VAR}={fixture_root} does not exist or is not a directory."
        )

    # ------------------------------------------------------------------
    # Paths in the fixture, expressed relative to fixture_root.
    # Mirrors interface/notebooks/Testcase_jupy_test.ipynb.
    # ------------------------------------------------------------------
    caw_out_dir = fixture_root / "cawaqs_simulation" / "OUTPUT"
    config_geom_json = (
        fixture_root
        / "cawaqs_simulation"
        / "OUTPUT"
        / "PostProcessing"
        / "CONFIG"
        / "config_geometries_Testcase_4comp.json"
    )
    obs_dir = ""  # sentinel: no observations in this fixture

    layer_paths = {
        "GRID_AQ": str(fixture_root / "gis_data" / "DATA_AQ" / "GRID_AQ.shp"),
        "ELEM_MUSK": str(fixture_root / "gis_data" / "DATA_HYD" / "ELEM_MUSK.shp"),
        "GRID_NSAT": str(fixture_root / "gis_data" / "DATA_NSAT" / "GRID_NSAT.shp"),
        "LIEN_BU_METEO": str(
            fixture_root / "gis_data" / "DATA_SURF" / "LIEN_BU_METEO.shp"
        ),
        "OBS_AQ": str(fixture_root / "gis_data" / "DATA_OBS" / "OBS_AQ.shp"),
        "OBS_HYD": str(fixture_root / "gis_data" / "DATA_OBS" / "OBS_HYD.shp"),
    }

    if not config_geom_json.is_file():
        pytest.skip(
            f"Fixture geometry config not found at {config_geom_json}. "
            "The fixture layout may have changed."
        )

    # ------------------------------------------------------------------
    # configure
    # ------------------------------------------------------------------
    config_geom = ConfigGeometry.fromJsonFile(str(config_geom_json))
    config_proj = ConfigProject.fromDict(
        {
            "json_path_geometries": str(config_geom_json),
            "projectName": "cwv_gis_smoke",
            "cawOutDirectory": str(caw_out_dir),
            "startSim": 1970,
            "endSim": 1972,
            "obsDirectory": obs_dir,
            "regime": "Transient",
        }
    )

    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    twin = HydrologicalTwin(
        metadata={
            "project": "cwv_gis_smoke",
            "regime": "Transient",
        }
    )
    assert twin.state.value == "EMPTY"

    twin.configure(
        config_geom=config_geom,
        config_proj=config_proj,
        out_caw_directory=str(caw_out_dir),
        obs_directory=obs_dir,
        temp_directory=str(temp_dir),
    )
    assert twin.state.value == "CONFIGURED"

    # ------------------------------------------------------------------
    # load
    # ------------------------------------------------------------------
    ids = list(config_geom.idCompartments)
    geo_provider = _SmokeGeoProvider(layer_paths)

    twin.load(ids_compartments=ids, geo_provider=geo_provider)
    assert twin.state.value == "LOADED"

    # ------------------------------------------------------------------
    # describe
    # ------------------------------------------------------------------
    description = twin.describe()
    assert description.n_compartments == len(ids)

    watbal_catalog = next(
        (c for c in description.catalog.compartments if c.name == "WATBAL"),
        None,
    )
    assert watbal_catalog is not None, (
        "Fixture is expected to expose a WATBAL compartment."
    )

    # ------------------------------------------------------------------
    # fetch  →  transform  →  render
    # ------------------------------------------------------------------
    mb_params = watbal_catalog.output_parameters.get("MB", [])
    assert mb_params, "WATBAL is expected to expose MB output parameters."

    first_param = mb_params[0]
    fetched = twin.fetch(
        kind="simulation_matrix",
        id_compartment=watbal_catalog.id_compartment,
        outtype="MB",
        param=first_param,
        syear=1970,
        eyear=1972,
        id_layer=0,
    )

    budget = twin.transform(
        kind="budget",
        data=fetched.data,
        sdate=fetched.dates[0],
        edate=fetched.dates[-1],
        cutsdate=str(fetched.dates[0]),
        cutedate=str(fetched.dates[-1]),
        frequency="Annual",
        agg_dimension="mean",
        param=first_param,
    )

    data_dict = {first_param: (budget.data, budget.date_labels, budget.param)}

    output_dir = tmp_path / "render"
    output_dir.mkdir()

    result = twin.render(
        kind="budget_barplot",
        data=data_dict,
        plot_title="cwv-gis-smoke",
        output_folder=str(output_dir),
        output_name="smoke_budget",
        yaxis_unit="mm",
    )

    assert result.artefacts, "render returned no artefacts"
    assert any(Path(p).is_file() for p in result.artefacts), (
        f"render claimed artefacts {result.artefacts!r} but none exist on disk."
    )
