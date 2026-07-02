# TODO — HTAS LAYER REFACTORING

Clean up to keep the architecture consistent: avoid repetition and dead code,
and keep a solid division of roles across the 3-level layered architecture
(L1 · HT CLIENT · MACRO `ht/client/` → L2 · HT DEVELOPER · MICRO `ht/developer/` → L3 · SERVICES · ELEMENTARIES `services/`),
with imports pointing strictly downward (each level calls only the level below).
The imports among layers are allowed. For instance in many L2 methods is imported and used the fetch simulation matrix function. For the moment is allowed. It pose problems or the use of the notebook anyway. In a second moment this should become stricter. *** Not prioritised ***  
*NB: I added comments around with LAYER REFACTORING to define the areas that should be moved /replaced*

*** PHYLOSOPHY *** : THE L1 is PURE orchestrator
## Deferred from `restructure-htas-3level-dag`

These were captured (not done) by the structural-relocation change that moved
`accessors.py` → `services/public/twin_io.py` and renamed the L1/L2 entry
modules. They complete the move toward the clean single L2→L3 arrow.

- **Fold `handlers.py` and `dispatch.py` into the L2 micro-verbs.** They are
  currently *transitional L2-internal modules* sitting between the
  `hydrological_twin_developer.py` facade and L3. Folding their compute /
  routing bodies into the micro-verb methods removes the intermediate hop so L2
  becomes a single layer that calls straight down into L3.
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

### 4. Dead dispatch arm: `area_values` with `target_unit is None` — DONE
The `extract_area` fall-through arm (never reached by the dialog, which always
sends a unit) has been **removed**: `mask(kind="area_values")` now raises
`ValueError` when `target_unit is None`. `extract_area` itself is deleted (#6).

### 5. `_build_cells_gdf` mixes orchestration with pure assembly
`ht/client/operations_client.py:975-980` (FIXME already in place). The function mixes
*selection* (`twin.mask` / `_build_outcropping_mesh_gdf` — orchestration, belongs
in `run_mask_internal_values`) with pure GeoDataFrame *assembly* (gpd join +
weight column — a services-layer op, no twin / no dispatch).
- **Fix:** keep the `twin.*` selection inline in `run_mask_internal_values`;
  extract the pure geopandas assembly into `services/`.

### 6. Dead code — unused functions (mostly DONE)
Functions with **no reference** in `src/`, `tests/`, the notebooks, or the CWV
frontend (verified by whole-word sweep + `getattr` check).
- **Deleted:** `extract_area` (+ its L2 facade + the `dispatch.py` no-unit arm,
  see #4), `aggregate_matrix` and `simMatrixToDf` (`services/public/temporal.py`),
  `reverseDict` (`config/models.py`). `extract_area` was reachable only from the
  developer gate with `target_unit is None`; the 3 tests that exercised that path
  were rewritten to assert the new "unit required" contract.
- **Still open — `fromJsonString`** (`config/factory.py:11`): no caller, but it
  is an unused sibling of the *used* `fromDict` / `fromJsonFile` on the same
  `FactoryClass`, so it may be deliberate factory API. Decide keep-vs-drop for
  the constructor triplet as a whole.

> NB: the `read_values` `AttributeError` bug formerly tracked here is **fixed** —
> `_build_aq_spatial_gdf` unpacks the raw `(sim_matrix, dates)` tuple. The
> structural question ("all `read_values` should route through `fetch`, called
> from L1 not L2") lives in #8.

### 7. Thin the L2 pass-through delegators — but keep the gate
`hydrological_twin_developer.py` carries ~40 near-identical two-line delegators
of the shape `from ...services.public import twin_io; return twin_io.f(self, ...)`
(e.g. `read_observations`, `get_layer_info`, `has_observations`, every `_build_*`,
every `render_*`). The repetition is real boilerplate and worth removing.
- **Do NOT** "connect the frontend directly to `services/`" to remove them: that
  makes callers reach past the L2 entry gate into L3 leaves, which is exactly the
  "reaching around the gate" bug the architecture forbids, and it dissolves the
  `ExploreData → Client` network seam we want to keep for the future server.
- **Distinction that drives the refactor:** a method that only *forwards* is
  boilerplate (could be generated from a declarative `name → service fn` table,
  or `__getattr__` delegation for pure pass-throughs); a method that *guarantees
  a contract* (arg coercion, `_require_state`, DTO wrapping) is architecture and
  must stay explicit. The DTO-wrapping seam is what makes callers able to trust
  a return type — losing that seam silently is the class of bug to guard against
  (a caller trusting a DTO that a thinned delegator no longer wraps). Tie to #8.
- **First step when picked up:** sort the ~40 methods into "pure forward" vs
  "shapes something". That sort is the whole design.

### 8. `read_values` should be reached through `fetch`, from L1 — not L2
Today `read_values` is called from **L2** (inside handlers such as
`_build_aq_spatial_gdf` and `_prepare_sim_obs_data`). Because some L2 methods fetch data
and others do not, the developer API is inconsistent: a notebook user can't tell
which verbs need data already loaded and which pull it themselves. The ideal
structure routes **all** `read_values` through the `fetch` verb, orchestrated at
**L1**, so L2 handlers receive data rather than fetch it.
- **Fix:** move the `read_values`/`fetch` call up into L1 orchestration; have the
  L2 handlers take the already-fetched matrix as an argument.
- This is the structural half formerly noted under #6; it is the single home for
  the "read_values from L1" idea (also referenced by #7's DTO-seam point).