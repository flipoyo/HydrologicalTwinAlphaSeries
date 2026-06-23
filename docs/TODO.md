# TODO — HTAS cleanup

Clean up to keep the architecture consistent: avoid repetition and dead code,
and keep a solid division of roles across the 3-level acyclic DAG
(L1 `ht/client/` → L2 `ht/developer/` → L3 `services/`), with imports pointing
strictly downward.

## Deferred from `restructure-htas-3level-dag`

These were captured (not done) by the structural-relocation change that moved
`accessors.py` → `services/public/twin_io.py` and renamed the L1/L2 entry
modules. They complete the move toward the clean single L2→L3 arrow.

- **Fold `handlers.py` and `dispatch.py` into the L2 macro-verbs.** They are
  currently *transitional L2-internal modules* sitting between the
  `hydrological_twin_developer.py` facade and L3. Folding their compute /
  routing bodies into the macro-verb methods removes the intermediate hop so L2
  becomes a single layer that calls straight down into L3.
- **De-orchestrate `operations_client.py`.** Today it owns full
  `fetch → transform → render` chains (e.g. `run_mask_internal_values` ≈ 290
  lines). Push that chaining down toward L2 macro-verbs so the L1 client stays
  thin and the orchestration lives one level closer to the compute.
- **Revisit moving the leaf data DTOs into an L3 `io_types.py`** — *done* for
  the 5 read DTOs (`ValuesResponse`, `ObservationsResponse`, `CompartmentInfo`,
  `LayerInfo`, `ObservationInfo`), which now live in
  `services/public/io_types.py` and are re-exported by L2 `api_types.py`.
  Revisit whether the remaining `*Response` / `*Request` DTOs that L3 never
  needs should stay in L2, or whether more of them belong at the L3 leaf, once
  `handlers.py` / `dispatch.py` are folded in.

## Spotted risks

### 1. `weighted` is a redundant request field — derive it from the unit
`mask(kind="area_values")` carries a `weighted` flag *and* a `target_unit`, but
weighting is only ever meaningful on volumetric units. Two fields = two sources
of truth that can contradict each other.
- **Fix:** drop `weighted` from the request; derive numeric weighting at its one
  point of use as `target_unit in _VOLUMETRIC_UNITS`.
- **Then delete** the guard at `dispatch.py:326-333` that *raises* on
  `weighted=True` + non-volumetric unit — redundant once weighting is unit-derived.

### 2. Separate geometry-clipping from numeric weighting
Today the single `weighted` flag drives both (a) the selection/geometry — clipped
intersection geoms vs. full footprints — and (b) the numeric multiplication
`subset_data * weights`. These are independent concerns.
- **Fix:** always run `cells_in_polygon_weighted` so the gdf *always* carries
  clipped geometries (we always want them visually); apply the numeric `* weights`
  step only on the volumetric path (see #1). On the non-volumetric path the gdf
  `weight` column is empty / all-1, but the clipped geometry stays.

### 3. Rename `convert_watbal_units` to a volumetric-flux-scoped name
`services/public/vec_operator.py:165-196`. The name implies "any compartment",
but the conversion divides `mm/j` by cell area — only valid for **volumetric
flux**, not for quantities with no cell area (e.g. HYD reaches, water height).
Recharge already rides this path correctly.
- **Fix:** rename to something flux-scoped and document the volumetric assumption.

### 4. Dead dispatch arm: `area_values` with `target_unit is None`
`dispatch.py:417-435`. The `extract_area` branch is never reached by the dialog
(the dialog always sends a unit token). `extract_area` itself is clean — the
smell is the unreached dispatch arm, which also still carries the 1-based-id /
0-based-row mismatch.
- **Fix:** drop the dead arm (or guard it explicitly as developer-only).

### 5. `_build_cells_gdf` mixes orchestration with pure assembly
`ht/client/operations_client.py:975-980` (FIXME already in place). The function mixes
*selection* (`twin.mask` / `_build_outcropping_mesh_gdf` — orchestration, belongs
in `run_mask_internal_values`) with pure GeoDataFrame *assembly* (gpd join +
weight column — a services-layer op, no twin / no dispatch).
- **Fix:** keep the `twin.*` selection inline in `run_mask_internal_values`;
  extract the pure geopandas assembly into `services/`.
