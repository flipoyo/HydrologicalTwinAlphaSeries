# HydrologicalTwin API Capabilities

This document lists the public macro-methods exposed by `HydrologicalTwin`.

These are the **only** methods external consumers should call.
Internal modules (`domain/`, `services/`, `config/`, `tools/`) are implementation
details and must not be accessed directly.

All operations act on **Compartment aggregates** — never on low-level Mesh,
Observation, or Extraction objects directly.

---

## Lifecycle

| Method                 | Required State | Next State  | Description                              |
|----------------------- |--------------- |------------ |------------------------------------------|
| `configure`            | EMPTY          | CONFIGURED  | Attach project and geometry config       |
| `load`                 | CONFIGURED     | LOADED      | Register compartments in bulk            |
| `register_compartment` | LOADED         | (unchanged) | Register a single compartment            |
| `describe`             | LOADED         | (unchanged) | Return twin metadata and compartment info|
| `extract`              | LOADED         | (unchanged) | Extract simulation or observation data   |
| `transform`            | LOADED         | (unchanged) | Temporal/spatial aggregation             |
| `render`               | LOADED         | (unchanged) | Produce visualizations                   |
| `export`               | LOADED         | (unchanged) | Export data to disk                      |

---

## Method Intents

### `configure(**kwargs)`
Set project-level and geometry configuration. Replaces constructor-time config.

### `load(**kwargs)`
Register compartments, build meshes, and attach observations.

### `register_compartment(id_compartment, compartment)`
Register a single compartment after initial `load()`.

### `describe(**kwargs)`
Inspect twin metadata, list compartments, layer info, and observation info.

### `extract(**kwargs)`
Extract simulation matrices, observation data, or area subsets.

### `transform(**kwargs)`
Apply temporal aggregation (annual, monthly) or spatial averaging.

### `render(**kwargs)`
Produce file artefacts such as budget bar plots, sim-vs-obs charts, and hydrological
regime plots without launching interactive screen views.

### `export(**kwargs)`
Export data as CSV, pickle snapshots, or GeoDataFrames.

---

## Transport Layer

No HTTP schema or web framework integration is defined at this stage.
The wire protocol will be designed once the façade methods and public result types
are stable enough to deserve exposure.
