# TODO for HTAS user-guide test case

## Goal

Provide one **minimal, shareable, non-proprietary test case** that can be used to:

- exercise the front API end to end,
- keep the `HTAS_user_guide.tex` examples concrete,
- validate integration from a downstream consumer such as `docs/hydrological_twin`.

## Test case that should be provided

The test case should contain a **single small project** with the smallest data footprint that still covers the main public workflow:

1. **Configuration inputs**
   - one `ConfigGeometry` source (JSON or equivalent dict source),
   - one `ConfigProject` source,
   - one compartment identifier,
   - at least one layer name and one cell-id column definition.

2. **Geometry inputs**
   - one small mesh/geometry file usable by the public `load()` path,
   - enough attributes to resolve cell ids and layer names,
   - CRS information preserved.

3. **Simulation inputs**
   - a tiny CaWaQS output directory,
   - one short simulation period (for example 1 to 2 hydrological years),
   - at least the variables needed to demonstrate:
     - `fetch(kind="simulation_matrix")`,
     - `transform(kind="budget")`,
     - `transform(kind="hydrological_regime")`.

4. **Observation inputs**
   - at least one observation point,
   - enough data to demonstrate:
     - `fetch(kind="observations")`,
     - `fetch(kind="sim_obs_bundle")`,
     - `transform(kind="criteria")`.

5. **Expected artefacts**
   - one expected pickle export path,
   - one expected rendered figure path,
   - one short note describing which examples in the guide are backed by this dataset.

## Recommended minimum coverage

The provided test case should allow the following public sequence to run without using internal classes:

1. `configure`
2. `load`
3. `describe`
4. `fetch(simulation_matrix)`
5. `fetch(observations)`
6. `fetch(sim_obs_bundle)`
7. `transform(temporal_aggregation)`
8. `transform(criteria)`
9. `transform(budget)` or `transform(hydrological_regime)`
10. `render`
11. `export`

## Best solution for storing the test case

### Recommended option: dedicated Git submodule

Use a **dedicated repository added as a Git submodule** if the test case contains binary outputs, GIS files, or data that will also be reused by downstream documentation or integration repositories.

Why this is the best default choice:

- it keeps this repository lightweight,
- it avoids mixing code history with dataset history,
- it makes version pinning explicit for documentation builds,
- it allows the same frozen dataset to be reused in HTAS and in the downstream `docs/hydrological_twin` location.

### Suggested layout

- keep `docs/HTAS_user_guide.tex` in this repository while authoring,
- move or mirror it later into the downstream `docs/hydrological_twin` location,
- mount the dataset as a submodule such as:
  - `docs/hydrological_twin/test_case`, or
  - another clearly named sibling path used by the downstream documentation build.

## When a submodule is not necessary

If the final test case is extremely small and text-only (for example JSON plus a few CSV files, no large binaries, no GIS assets), then committing it directly may be acceptable.

However, if the goal is to document a realistic HTAS workflow with reusable example data, the **submodule approach remains the safer long-term solution**.
