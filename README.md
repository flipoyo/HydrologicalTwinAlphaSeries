# HydrologicalTwinAlphaSeries

HydrologicalTwinAlphaSeries is the standalone scientific backend for CaWaQS-ViZ. It is a POC for HydrologicalTwin. 

It owns the hydrological twin domain model, post-processing services, API facade, and backend configuration objects so the visualization layer can remain a separate application.

This repository is designed to be developed independently from the QGIS application layer and consumed by cawaqsviz through an editable install from a Git submodule checkout.

## Authorship

The project metadata lists the named contributors below as authors; their current roles are:

- Project Manager: Nicolas Flipo
- Main Developer: Simone Mazzarelli
- Other contributors to come: Tristan Bourgeois, Nicolas Gallois, ...
- Proto implementation as CaWaQS-ViZ backend: Lise-Marie Girod

## Layout

- `src/hydrological_twin_alpha_series/domain`: compartment, mesh, observation, and extraction entities
- `src/hydrological_twin_alpha_series/services`: analysis, rendering, and vector operators
- `src/hydrological_twin_alpha_series/ht`: `HydrologicalTwin` facade and API types
- `src/hydrological_twin_alpha_series/config`: backend constants and configuration models
- `src/hydrological_twin_alpha_series/tools`: shared utilities
- `tests`: smoke coverage for imports and backend construction
- `docs`: backend-focused API examples and architecture notes

## Setup

```bash
pixi install
```

This installs the package in editable mode from the local checkout.

## Minimal Usage

```python
from hydrological_twin_alpha_series import ConfigGeometry, ConfigProject, HydrologicalTwin

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
config_proj = ConfigProject.fromDict(
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

twin = HydrologicalTwin(
	config_geom=config_geom,
	config_proj=config_proj,
	out_caw_directory=config_proj.cawOutDirectory,
	obs_directory=config_proj.obsDirectory,
)

print(twin.list_compartments())
```

## Developer Workflow

Run a package smoke check:

```bash
pixi run run
```

Run the tests:

```bash
pixi run test
```

Run linting:

```bash
pixi run lint
```

## Before Committing

Run the same checks locally that the backend CI runs on GitHub Actions:

```bash
pixi install
pixi run lint
pixi run test
pixi run run
```

`pixi run lint` validates the backend source tree and tests with Ruff, `pixi run test` runs the unit and integration tests, and `pixi run run` is a package smoke check for the command-line entry point.

If you are editing the backend through the `cawaqsviz` checkout, run these commands from `external/HydrologicalTwinAlphaSeries/` before committing in the backend repository and then updating the submodule pointer in `cawaqsviz`.

The integration smoke test that constructs a minimal `HydrologicalTwin` object lives in `tests/integration/test_hydrological_twin_smoke.py`.

## Integration with cawaqsviz

The intended integration point is a Git submodule mounted at `external/HydrologicalTwinAlphaSeries` inside the `cawaqsviz` repository. The cawaqsviz Pixi environment should install this package in editable mode instead of carrying a duplicated backend tree.

Manual GitHub and submodule registration steps belong to the application repository workflow and are intentionally kept separate from this backend package setup.
