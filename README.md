# HydrologicalTwinAlphaSeries

HydrologicalTwinAlphaSeries is the standalone scientific backend supporting CaWaQS-ViZ.

It serves as a proof-of-concept (POC) for the HydrologicalTwin framework and is dedicated to the definition, validation, and consolidation of its core computational structures.

The repository provides the backend layer required to structure hydrological simulation outputs, expose controlled programmatic interfaces, and support post-processing workflows required by the visualization layer. It focuses strictly on the backend domain, including data structuring and transformation, computational services, configuration models, and API exposure for external consumers. It does not include user interface components, QGIS integration logic, or visualization responsibilities.

It is intentionally developed independently from the QGIS application layer, which consumes it as an external dependency.

HydrologicalTwinAlphaSeries constitutes the AlphaSeries of the HydrologicalTwin framework. In this context, Alpha does not denote instability in the conventional software sense, but a phase in which the system is under formal construction. Core assumptions, data structures, and computational behaviors are actively explored and stress-tested.

The term Series designates a coherent progression of such states. Each iteration contributes to the convergence toward a stable and reproducible backend foundation, ensuring that future versions rely on explicitly validated principles rather than implicit design choices.

---

## Status

This repository is part of the AlphaSeries phase.

This phase is dedicated to:

* defining core architectural invariants,
* validating backend behaviors under real use cases,
* stabilizing interfaces with the visualization environment.

No long-term API stability is guaranteed at this stage.

---

## Relationship with CaWaQS-ViZ

CaWaQS-ViZ is the primary consumer of this repository.

The integration follows a clear separation of concerns:

* HydrologicalTwinAlphaSeries → backend computation and data structuring
* CaWaQS-ViZ → visualization, interaction, and GIS integration

The backend is intended to be integrated as an external dependency (e.g. Git submodule), avoiding duplication and ensuring consistency between computation and visualization layers.

---

## Repository Structure

* `src/HydrologicalTwinAlphaSeries/domain`
  Core domain entities (e.g. compartments, meshes, observations)

* `src/HydrologicalTwinAlphaSeries/services`
  Computational services and transformation operators

* `src/HydrologicalTwinAlphaSeries/ht`
  Backend facade and exposed API types

* `src/HydrologicalTwinAlphaSeries/config`
  Configuration models and constants

* `src/HydrologicalTwinAlphaSeries/tools`
  Shared utilities

* `tests`
  Backend validation and integration checks

* `docs`
  Technical notes and backend-oriented documentation
  (see [canonical_monolith.md](docs/canonical_monolith.md) for the target architecture,
  [domain_model.md](docs/domain_model.md) for the compartment-centric domain model)

---

## Development Principles

* strict separation between computation and visualization layers,
* reproducible backend behavior,
* explicit configuration-driven workflows,
* minimal coupling with external applications.

---

## Integration Workflow

When used within CaWaQS-ViZ:

* this repository is mounted as an external dependency,
* development can occur independently on both sides,
* synchronization is handled through version control (submodule or equivalent mechanism).

---

## Authorship

* Contact: hydrologicaltwin@minesparis.psl.eu
* Project Manager: Nicolas Flipo
* Main Developer: Simone Mazzarelli
* Proto implementation (CaWaQS-ViZ backend): Lise-Marie Girod

Contributors (ongoing):
Tristan Bourgeois, Nicolas Gallois, Fulvia Baratelli, Pierre Guillou, Fabien Ors, Mariam Taki

---

## Positioning

HydrologicalTwinAlphaSeries is not a generic Python package.

It is the computational foundation of a hydrological twin system, currently under active definition and validation.

---

## Developer Workflow

CaWaQS-ViZ (frontend, GitLab) consumes HydrologicalTwinAlphaSeries (backend, GitHub)
as a Git submodule. Three scenarios arise depending on where changes are needed.

### 1. Frontend-only changes

Create a branch on the GitLab repository (CaWaQS-ViZ) and work from there.
The submodule is not affected.

### 2. Backend-only changes (no CaWaQS-ViZ testing needed)

Create a branch on the GitHub repository (HydrologicalTwinAlphaSeries) and work
from there. The frontend does not need to be updated until the work is merged.

### 3. Coordinated frontend + backend changes

When both sides need to evolve together — or when backend changes must be
continuously tested through CaWaQS-ViZ — open **two branches with the same name**:
one on GitLab (frontend) and one on GitHub (backend).

#### Initial setup (once per coordinated branch)

1. **In `.gitmodules`**, set the tracked branch to the shared branch name:

   ```ini
   [submodule "external/HydrologicalTwinAlphaSeries"]
       branch = <branch-name>
   ```

2. **Pull the backend branch** into the submodule:

   ```bash
   git submodule update --remote external/HydrologicalTwinAlphaSeries
   ```

3. **Commit the pointer update** in the parent repo so GitLab records the
   new submodule state:

   ```bash
   git add external/HydrologicalTwinAlphaSeries .gitmodules
   git commit -m "Track backend branch <branch-name>"
   ```

#### Ongoing synchronization

Every time new commits are pushed to the tracked backend branch on GitHub,
the parent repo will show a diff on `external/HydrologicalTwinAlphaSeries`.
To stay in sync:

```bash
git submodule update --remote external/HydrologicalTwinAlphaSeries
git add external/HydrologicalTwinAlphaSeries
git commit -m "Update submodule to latest <branch-name>"
```

> **Tip:** commit the pointer update frequently. It keeps the frontend
> aligned with the latest backend and avoids large, hard-to-debug jumps.

#### After the work is done

When both branches are merged (backend into `main` on GitHub, frontend into
`main` on GitLab), reset `.gitmodules` to track `main` again:

```ini
branch = main
```

### Key concepts

| Term | Meaning |
|---|---|
| **Submodule pointer** | A commit hash stored in the parent repo. It pins the exact backend version used. It does not update automatically. |
| `.gitmodules` `branch` field | Tells `git submodule update --remote` which remote branch to fetch. Has no effect without `--remote`. |
| **Detached HEAD** | Normal state for a submodule — it checks out a specific commit, not a branch. |