# services/ — security model and the `private/` charter

This document governs the boundary between `services/public/` and
`services/private/`. Read it before adding a method to either folder.

## Why `services/private/` exists

The HydrologicalTwinAlphaSeries backend is migrating toward a standalone,
possibly server-side component. In that future the backend runs remote and
only a curated subset of operations is exposed to a user laptop. Some
operations can return server-resident simulation data scoped to a
geometry the user supplies — and the most advanced planned form of the
**mask** rebuilds the configuration JSONs for the selected area and writes
the raw NumPy of an area-scoped *submodel*. That artefact is a rehydratable
model, not a chart: handing it to a laptop is a real data leak.

`services/private/` is the structural home for that leak-prone code. Today
it is a folder boundary plus this written charter. A later change will add
a runtime authorization gate (see *Next step* below); when it does, having
all privileged code behind one import path makes the gate easy to wire and
easy to audit.

## The data-leak risk of the mask operations

The mask operations (`mask_watbal`, `mask_hyd_boundary`, `mask_aq_boundary`
on `HydrologicalTwinClient`) take a user-supplied polygon and return the
subset of server-resident data that intersects it. Spatial-map operations,
by contrast, return whole-mesh **aggregated** values and carry no
user-geometry-scoped raw data — they are not a leak surface.

The danger is not "the mask UI" as a whole. It is the *production of
submodel-grade raw artefacts scoped to a user-selected area*.

## The tiered definition of "dangerous"

Ranked from most to least dangerous.

### Tier 1 — submodel-grade raw artefacts

The area-scoped submodel: the raw NumPy of the masked cells plus the
rebuilt configuration JSONs for the selected area. This *is* a model that
can be re-instantiated and run. **Must be in `services/private/`.**

- *Today:* `services/private/submodel_export.py::save_area_values_npy` —
  the `.npy` write of the per-cell value array for a masked WATBAL area,
  invoked by `ht/client/operations.py::run_mask_watbal`. This is the
  precursor of the full submodel-numpy + rebuilt-config writer.
- *Today:* `services/private/submodel_export.py::save_area_geopackage` —
  the transportable GeoPackage bundling masked-cells geometry, long-form
  per-(cell, date, param) values, and run provenance for a masked WATBAL
  area; also invoked by `ht/client/operations.py::run_mask_watbal` when
  the `write_geopackage=True` opt-in flag is set. Same Tier-1 leak
  surface as the `.npy` writer: user-supplied geometry combined with raw
  per-cell numeric arrays on disk.

### Tier 2 — raw per-cell time series (CSV form)

Raw, not aggregated, scoped to the user polygon. A determined user can
reconstruct local dynamics from these. Less directly weaponisable than a
`.npy`, but the same family.

### Tier 3 — cell-ID enumeration scoped to user geometry

Which cells fall inside the user's polygon. On its own this is mesh
metadata; it becomes dangerous only when paired with a Tier-1 or Tier-2
array.

## The placement rule

When adding a method, apply this test:

> A method belongs in `services/private/` if it **both**
> (i) consumes a user-supplied geometry **AND**
> (ii) returns or writes raw per-cell numeric arrays, or a rebuildable
>      configuration/submodel bundle.
>
> Geometry-only methods (cell-ID enumeration, boundary detection) stay
> public. Aggregated-only methods (whole-mesh maps, budgets, summary
> statistics) stay public. Only the combination — user geometry **and**
> raw per-cell data out — is private.

If a method satisfies both clauses, put it in `services/private/` and
import it by its concrete module path (`services/private/__init__.py` is
intentionally empty, so every privileged import is greppable).

### Intent-based placement (the two-clause test is sufficient, not necessary)

The two-clause rule is sufficient — satisfy both clauses and the method is
private — but it is not the *only* reason a method belongs in `private/`. A
method MAY also belong there by the **data-leak intent** of this charter:
when it assembles a Tier-2 raw per-point/per-cell series destined for a
user-exported CSV, it is squarely in the leak-prone family even if it
consumes no user-supplied geometry (clause (i) fails).

The literal geometry clause MUST NOT be used to reclassify such a method as
public. A function placed here on intent should say so in its docstring, so
a future reader applying the two-clause test literally does not "helpfully"
move it back to `public/`.

- *Today:* `services/private/raw_data_export.py::assemble_daily_sim_obs_table`
  — assembles the wide daily sim/obs DataFrame for the `csv` mode of
  `compare_sim_obs`. It takes no user geometry (observation points are fixed
  model locations), so it fails clause (i); it is private by Tier-2 export
  intent. It performs no I/O — the frontend writes the CSV.

## Known public-but-flagged code (deferred migration)

The following code is leak-relevant but knowingly still public in the
current change, to keep that change scoped to structure + Tier-1 only.
A follow-up change should migrate it:

- **Tier 2 — raw per-cell CSV writes.** `run_mask_watbal` writes a raw
  per-cell WATBAL CSV alongside the `.npy`; `run_mask_hyd_boundary` and
  `run_mask_aq_boundary` write raw boundary-flux CSVs. These remain in the
  public `ht/client/operations.py`.
- **Tier 3 — cell-ID builders.** `services/public/spatial.py::Spatial`
  (`getCatchmentCellsIds`, `getUpStreamSection`, `buildAqOutcropping`) and
  the `kind="catchment_cells"` / `kind="aquifer_outcropping_map"` dispatch
  branches enumerate cells from a user geometry. They remain public.

## Next step

This change establishes the folder boundary and this charter. It does
**not** yet add a runtime authorization check. The planned follow-up is a
runtime gate — a capability flag set at `HydrologicalTwinClient`
construction time, a privileged-vs-public client split, or a
dispatch-level token check — that refuses Tier-1 (and eventually Tier-2/3)
operations unless the caller is authorized. Because all Tier-1 code is
reachable only through `services/private/`, that gate has a single,
auditable surface to guard.
