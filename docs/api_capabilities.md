# HydrologicalTwin API Capabilities

This document lists the public macro-methods exposed by `HydrologicalTwin`.

These are the **only** methods external consumers should call.
Internal modules (`domain/`, `services/`, `config/`, `tools/`) are implementation
details and must not be accessed directly.

All operations act on **Compartment aggregates** — never on low-level Mesh,
Observation, or Extraction objects directly.

---

## Lifecycle

| Method      | Required State | Next State  | Description                                      |
|------------ |--------------- |------------ |--------------------------------------------------|
| `configure` | EMPTY          | CONFIGURED  | Attach project and geometry config               |
| `load`      | CONFIGURED     | LOADED      | Consume a typed load request for compartments    |
| `describe`  | LOADED         | (unchanged) | Return the frontend catalog and API capabilities |
| `extract`   | LOADED         | (unchanged) | Run typed extraction workflows                   |
| `transform` | LOADED         | (unchanged) | Run typed business calculations                  |
| `render`    | LOADED         | (unchanged) | Produce final artefacts                          |
| `export`    | LOADED         | (unchanged) | Export data to disk                              |

---

## Method Intents

### `configure(**kwargs)`
Set project-level and geometry configuration. Replaces constructor-time config.

### `load(LoadRequest)`
Load typed compartment requests describing geometry sources, observation sources,
period, and directories. The stable public geometry contract is a provider-based
source (`geometry_source.kind == "provider"`).

### `describe(DescribeRequest(kind="catalog"))`
Return the unique frontend catalog: available compartments, stable identifiers,
resolutions, observation layers, units, supported outputs, and available
`extract` / `transform` / `render` kinds.

### `extract(ExtractRequest)`
Supported public kinds are:
`simulation_matrix`, `observations`, `sim_obs_bundle`, `spatial_map`,
`catchment_cells`, `aquifer_outcropping`, and `aq_balance_inputs`.

### `transform(TransformRequest)`
Supported public kinds are:
`temporal_aggregation`, `performance_criteria`, `aggregated_budget`,
`hydrological_regime`, `runoff_ratio`, and `interlayer_exchanges`.

### `render(RenderRequest)`
Produce final artefacts such as budget bar plots, sim-vs-obs charts, and
hydrological regime plots. Rendering is the only contractual production point
for final artefacts.

### `export(ExportRequest)`
Export data as CSV, pickle snapshots, or GeoDataFrames.

---

## Explicit Frontend Integration Facade

`HydrologicalTwin.describe_api_facade()` returns the stable macro-contract plus
the temporary compatibility wrappers kept during the CWV migration.

Compatibility wrappers are transitional only and emit deprecation warnings:

| Transitional helper family | Replacement |
|---|---|
| `register_compartment` | `load(LoadRequest(...))` |
| `get_compartment_info`, `get_layer_info`, `get_all_layers`, `get_observation_info` | `describe(DescribeRequest(kind="catalog"))` |
| `extract_values`, `read_observations`, `_prepare_sim_obs_data` | `extract(ExtractRequest(...))` |
| `compute_*`, `build_*`, `render_*` specifics | `transform(TransformRequest(...))` and `render(RenderRequest(...))` |

---

## Transport Layer

No HTTP schema or web framework integration is defined at this stage.
The wire protocol will be designed once the façade methods and public result types
are stable enough to deserve exposure.
