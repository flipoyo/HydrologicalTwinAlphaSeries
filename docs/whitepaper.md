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

## Access policy exploration

The recommended direction for this repository is to keep the facade private by default and mark supported entry points explicitly:

- apply `@private_access` to the facade class
- apply `@public_access` only to methods meant to be called by external applications such as `cawaqsviz`

This approach is preferable to treating all methods as public and trying to mark a few as private afterwards, because it fails closed when the API grows. It should still be viewed as a contract and CI/CD gate rather than as a security sandbox, since Python does not provide true in-process access isolation.

A fast CD check is feasible without adding Django-specific code: the import-time validation and `tests/unit/test_security_access.py` provide a lightweight gate that can be called from any Python or Django pipeline.
