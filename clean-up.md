# Cleanup summary

## Removed deprecated package-root shims

- Deleted `src/HydrologicalTwinAlphaSeries/Compartment.py`
- Deleted `src/HydrologicalTwinAlphaSeries/Extraction.py`
- Deleted `src/HydrologicalTwinAlphaSeries/Manage.py`
- Deleted `src/HydrologicalTwinAlphaSeries/Mesh.py`
- Deleted `src/HydrologicalTwinAlphaSeries/Observations.py`
- Deleted `src/HydrologicalTwinAlphaSeries/Renderer.py`
- Deleted `src/HydrologicalTwinAlphaSeries/Vec_Operator.py`
- Stopped re-exporting those deprecated modules from `src/HydrologicalTwinAlphaSeries/__init__.py`

## Reduced the public facade surface

- Removed legacy public transition helpers from `HydrologicalTwin`:
  - `register_compartment`
  - `describe_api_facade`
  - `build_watbal_spatial_gdf`
  - `build_effective_rainfall_gdf`
  - `build_aq_spatial_gdf`
  - `build_aquifer_outcropping`
  - `render_sim_obs_pdf`
  - `render_sim_obs_interactive`
- Kept the underlying behavior by moving the remaining internal delegation paths to private helpers used only by the canonical macro API (`configure`, `load`, `describe`, `extract`, `transform`, `render`, `export`)
- Removed the now-obsolete lifecycle entry for `register_compartment`

## Repository maintenance updates

- Removed Ruff exceptions that existed only for the deleted shim files
- Updated tests so the root package now validates only canonical imports and explicitly checks that deprecated shim modules are gone
- Updated integration coverage so legacy transition helpers are verified to be absent from the public `HydrologicalTwin` surface
- Removed documentation language that still described transitional compatibility wrappers as part of the intended API

## Follow-up plan for the user guide repository

Target repository: `github.com/flipoyo/hydrological_twin`

1. Replace every package-root legacy import with the canonical entrypoint:
   - prefer `from HydrologicalTwinAlphaSeries import HydrologicalTwin`
   - keep config imports on `HydrologicalTwinAlphaSeries` only when setup examples need them
2. Remove user-guide examples that call deleted transition helpers and rewrite them around:
   - `configure`
   - `load`
   - `describe`
   - `extract`
   - `transform`
   - `render`
   - `export`
3. Update any architecture diagrams or API tables so they no longer mention:
   - root shim modules
   - `register_compartment`
   - `describe_api_facade`
   - `build_*_gdf` helper methods
   - direct `render_sim_obs_*` helper methods
4. Add one migration section that maps legacy helper usage to the canonical macro entrypoints:
   - spatial maps → `extract(kind="spatial_map")`
   - aquifer outcropping → `extract(kind="aquifer_outcropping")`
   - sim/obs rendering → `render(kind="sim_obs_pdf")` or `render(kind="sim_obs_interactive")`
5. Regenerate or rerun all user-guide code snippets against this repository version so broken imports are caught immediately
