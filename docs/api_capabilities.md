# HydrologicalTwin API Capabilities

`HydrologicalTwin` exposes a macro-only public contract for external consumers.

For `cawaqsviz`, the target surface is limited to:

- `configure`
- `load`
- `describe`
- `fetch`
- `transform`
- `render`
- `export`

Everything else is an internal implementation detail. External code must not
orchestrate `domain/`, `services/`, `config/`, or `tools/` directly.

All operations act on compartment aggregates and structured public request or response
types. External consumers must not construct or manipulate low-level backend objects
such as `Compartment`, `Mesh`, `Observation`, or `Extraction` directly.

---

## Lifecycle

| Method | Required State | Next State | Description |
|---|---|---|---|
| `configure` | EMPTY | CONFIGURED | Attach project and geometry configuration |
| `load` | CONFIGURED | LOADED | Build and register project compartments |
| `describe` | LOADED | (unchanged) | Return the frontend catalog and twin metadata |
| `fetch` | LOADED | (unchanged) | Fetch workflow payloads through typed requests |
| `transform` | LOADED | (unchanged) | Compute aggregations, criteria, budgets, regimes, runoff ratio, and AQ balances |
| `render` | LOADED | (unchanged) | Produce final artefacts such as reports, plots, and AQ balance diagrams |
| `export` | LOADED | (unchanged) | Export twin snapshots or derived outputs |

---

## Macro Intents

### `configure(request)`
Attach project-level and geometry configuration. No I/O is performed.

### `load(request)`
Accept a public project-load request, build compartments internally, and
materialise the on-disk simulation cache. For every `(compartment, outtype)`
whose CaWaQS binary output is present, `load` ensures a `.npy` cache file
exists for each parameter covering the configured `(startSim, endSim)`
period. Files already present and matching the period are left untouched;
stale files from a different period are evicted and re-decoded. After `load`
returns, the twin is in the `LOADED` state and every `fetch(kind=
"simulation_matrix", …)` call is a pure cache read.

### `describe(request)`
Return the frontend catalog: compartments, layers, observations, units, supported
workflow kinds, and available outputs.

### `fetch(request)`
Return workflow payloads through stable kinds. Current kinds include:

- `simulation_matrix` — requires the on-disk cache materialised by `load`.
  Raises `CacheMissError` if the cache is missing (programmer error:
  `fetch` called without `load`).
- `observations`
- `sim_obs_bundle`
- `spatial_map`
- `catchment_cells`
- `aquifer_outcropping_map`
- `aq_balance_inputs`

### `transform(request)`
Perform workflow computations. Current kinds include:

- `temporal_aggregation`
- `spatial_average`
- `criteria`
- `budget`
- `hydrological_regime`
- `runoff_ratio`
- `aq_balance`

### `render(request)`
Produce final artefacts. Current kinds include:

- `budget_barplot`
- `hydrological_regime`
- `sim_obs_pdf`
- `sim_obs_interactive`
- `aq_flux_diagram`

### `export(request)`
Export data or snapshots. `pickle` remains the canonical persisted export format.

---

## Transport Layer

No HTTP schema or web framework integration is defined at this stage.
The Python-level macro facade is the only canonical contract.
