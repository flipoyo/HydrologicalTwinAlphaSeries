# HTAS Domain Model — Compartment-Centric Architecture

## Core Invariant

> `Compartment` is the **primary domain aggregate**.
> All public operations flow through compartments, never through low-level
> artifacts (meshes, observations, extraction points) directly.

---

## Domain Entities

### `Compartment` (primary aggregate)

A CaWaQS compartment that owns its spatial support, observational data,
extraction points, and temporal context.

| Attribute     | Type              | Cardinality | Description                        |
|---------------|-------------------|-------------|------------------------------------|
| `mesh`        | `Mesh`            | 1           | Spatial support (cells & layers)   |
| `observations`| `Observation`     | 0..1        | Observation data (optional)        |
| `extraction`  | `Extraction`      | 0..1        | Extraction points (optional)       |
| `timeframe`   | `TimeFrame`       | 0..1        | Temporal context (optional)        |

### `Mesh`

Spatial discretisation owned by a Compartment.  Contains one or more layers,
each composed of cells with geometry, area, and identifiers.

- Always accessed **through its owning Compartment**.
- Never manipulated directly by services or the façade.

### `Observation`

Time-series observation records attached to a Compartment.
Carries observation points with spatial linkage to mesh cells.

- Owned by a Compartment (0..1 relationship).
- Observation points reference cells in the Compartment's Mesh.

### `Extraction`

Named extraction points (e.g. piezometers, gauging stations) linked
to specific cells in the Compartment's Mesh.

### `TimeFrame`

Temporal support describing a simulation or analysis period.

| Attribute    | Type              | Description                                 |
|--------------|-------------------|---------------------------------------------|
| `date_ini`   | `datetime`        | Start date (inclusive)                       |
| `date_end`   | `datetime`        | End date (exclusive)                         |
| `timestep`   | `str`             | Temporal resolution (`"daily"`, `"monthly"`) |

---

## Relationship Diagram

```
HydrologicalTwin
  └── compartments : Dict[int, Compartment]
        ├── mesh       : Mesh (1)
        │     └── layers : Dict[int, MeshLayer]
        │           └── cells : List[Cell]
        ├── observations : Observation (0..1)
        │     └── obs_points : List[ObsPoint]
        ├── extraction : Extraction (0..1)
        │     └── ext_point : List[ExtractionPoint]
        └── timeframe : TimeFrame (0..1)
```

---

## Rules

1. **Compartment aggregates everything.** No cross-layer dependencies.
2. **Services accept Compartment** (or groups of Compartments), never raw Mesh
   or Observation objects.
3. **The façade (`HydrologicalTwin`)** manages compartments, enforces lifecycle,
   and delegates to services. It never manipulates internal artifacts directly.
4. **Domain objects are pure** — no orchestration, no service imports.

---

## Lifecycle

Compartments are registered into the twin in bulk via:

```python
twin.load(compartments={1: comp_aq, 2: comp_hyd})
```

Once loaded, all macro-methods (`describe`, `extract`, `transform`, `render`,
`export`) operate on the registered compartments.
