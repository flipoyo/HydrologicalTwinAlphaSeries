# HydrologicalTwinAlphaSeries Architecture Notes

HydrologicalTwinAlphaSeries is the standalone backend package for the CaWaQS alpha.x series. It is designed to be reusable independently from QGIS and to provide a stable API boundary for `cawaqsviz` and other front ends.

## Package Layers

- `config`: backend constants and configuration models
- `domain`: compartments, meshes, observations, and extraction entities
- `services`: temporal, spatial, budget, rendering, and vector operators
- `ht`: the `HydrologicalTwin` facade and serializable API types
- `tools`: shared utility functions

## Boundary With cawaqsviz

The backend package does not import from `cawaqsviz`. QGIS-specific behavior stays in `cawaqsviz/interface/GeoDataProvider.py`, which converts QGIS layers into GeoDataFrames before they are passed into backend domain objects.

For compatibility during the migration, `cawaqsviz/backend` remains as a shim layer that re-exports symbols from `hydrological_twin_alpha_series`. The backend implementation itself now lives only in this package.

## Intended Repository Layout

The long-term target is:

- `HydrologicalTwinAlphaSeries`: standalone backend repository
- `cawaqsviz`: visualization/application repository
- `cawaqsviz/external/HydrologicalTwinAlphaSeries`: Git submodule checkout of the backend repository

The current source tree is structured to support that split without changing the public `HydrologicalTwin` facade.