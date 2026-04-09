# Canonical Monolithic Architecture for HTAS

## Core Invariant

> HTAS exposes a single canonical object (`HydrologicalTwin`) that manages a
> structured domain composed of `Compartment` aggregates. All public operations
> act on compartments, never on low-level artifacts directly.

---

## Public Entry Point

`HydrologicalTwin` is the **single public entry point** for all backend operations.

```python
from HydrologicalTwinAlphaSeries import HydrologicalTwin
```

No other import is required for normal usage.

---

## Domain Model

`Compartment` is the **primary domain aggregate**. All data flows through
compartments. See `docs/domain_model.md` for the full hierarchy.

```
HydrologicalTwin
  └── compartments : Dict[int, Compartment]
        ├── mesh         : Mesh (1)
        ├── observations : Observation (0..1)
        ├── extraction   : Extraction (0..1)
        └── timeframe    : TimeFrame (0..1)
```

---

## Internal Layers (not part of the public API)

| Layer        | Purpose                                     |
|------------- |---------------------------------------------|
| `domain/`    | State & entities (no orchestration)         |
| `services/`  | Operations (no global state)                |
| `config/`    | Configuration models and constants          |
| `tools/`     | Generic utilities only                      |
| `ht/`        | Façade + public result types                |

---

## Public API — Macro-Methods (≤ 8)

The facade exposes only high-level macro-capabilities:

| Method                  | Purpose                                          |
|------------------------ |--------------------------------------------------|
| `configure`             | Set project and geometry configuration           |
| `load`                  | Register compartments in bulk                    |
| `register_compartment`  | Register a single compartment                    |
| `describe`              | Inspect twin metadata and compartment info       |
| `extract`               | Extract simulation or observation data           |
| `transform`             | Apply temporal/spatial aggregation               |
| `render`                | Produce visualizations (PDF, interactive plots)  |
| `export`                | Export data to files (CSV, pickle, GeoDataFrame) |

These methods **delegate** to `services/` and `domain/` — they contain no heavy logic.

---

## Internal State Model

`HydrologicalTwin` enforces an explicit lifecycle via an internal state machine:

```
EMPTY → CONFIGURED → LOADED → READY
```

- **EMPTY**: Instance created, no configuration.
- **CONFIGURED**: Configuration attached, no data loaded.
- **LOADED**: Compartments registered, data accessible. All macro-methods are operational.
- **READY**: All compartments validated and cross-checked. Reserved for future
  validation logic (e.g., CRS consistency checks, observation coverage verification).
  Currently, the transition from LOADED → READY is not yet automated.

Invalid call sequences raise `InvalidStateError`.

---

## Rules

- **Compartment is the primary aggregate.** All operations flow through compartments.
- **domain/** holds state, no orchestration.
- **services/** holds operations, no global state. Services accept Compartment objects.
- **tools/** holds generic utilities with no domain meaning.
- **ht/** holds the façade, public result types, and persistence.
- Public API returns **structured result types** (not raw dicts or internal objects).
- No direct numerical logic inside the façade.
- No direct file I/O inside the façade (delegated to services).

---

## Transport / API Layer

No web framework dependency exists in core. HTTP/REST/FastAPI/Django concerns are
explicitly deferred. The Python-level canonical API is the only contract at this stage.

See also: `docs/api_capabilities.md` for the list of façade methods and their intent.
