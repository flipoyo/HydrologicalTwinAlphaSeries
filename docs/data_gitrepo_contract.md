# Data GitRepo contract

## Purpose

Hydrological Twin treats the **Git repository (`GitRepo`) as the elementary structural unit** of a Twin.

A Twin is an ontological state-space represented as a GitTree. ComplexGitSync materialises that GitTree into a reproducible Operating Space. Hydrological Twin then manages and orchestrates the resulting hydrological Twin.

This contract extends that model to data without requiring physical data to live in Git.

```text
GitRepo
  -> Twin GitTree
  -> ComplexGitSync
  -> Operating Space
  -> Hydrological Twin orchestration
```

A data repository therefore represents a data resource logically and reproducibly, while the physical bytes may reside elsewhere.

## Core invariant

Hydrological Twin references a **Data GitRepo**, not a storage URI.

```text
Twin -> Data GitRepo -> DataAsset -> resolver -> physical data
```

The GitRepo is the stable identity and versioning boundary. The physical locator is an implementation detail that may change without changing the logical identity of the data resource.

## Responsibilities

### Git provider

The Git provider remains the authority for repository access rights:

- public repository: readable without repository membership;
- private repository: readable only by authorised users;
- write/commit/push rights: determined by repository/provider permissions.

Hydrological Twin and ComplexGitSync must not duplicate provider credentials or access-control state.

### ComplexGitSync

ComplexGitSync owns GitTree materialisation and state reconstruction:

- repository identity and location in the tree;
- repository commit/ref;
- PROJECT versus PRIVATE repository class;
- PRIVATE.DISTANT / PRIVATE.LOCAL operating behaviour;
- reproducible reconstruction of the GitTree Operating Space.

For data repositories, complete reconstruction also requires enough metadata to materialise the data assets declared by each repository.

### Hydrological Twin

Hydrological Twin owns the hydrological semantics and orchestration:

- what a repository represents in a Twin;
- how hydrological entities and interfaces use that repository;
- how a DataAsset is opened, queried, transformed or passed to a model;
- scientific metadata such as variables, spatial support and temporal support.

### Data resolver / adapter

A resolver maps a logical DataAsset to physical data.

Examples may include DVC, a local file, HTTP, object storage, a database, or a dedicated scientific service. Resolver implementations are intentionally outside the dependency-free domain contract.

## DataAsset

`DataAsset` is the dependency-free logical description of a data resource declared by a Data GitRepo.

Minimal fields:

| Field | Meaning |
|---|---|
| `name` | stable logical name inside the repository |
| `resolver` | mechanism used to materialise the data |
| `target` | relative path where the resource appears inside the materialised GitRepo |
| `locator` | optional resolver-specific pointer or URI |
| `kind` | optional hydrological semantic class |
| `format` | optional physical format hint |
| `state` | optional immutable physical-data state/checksum/version |
| `metadata` | extensible scientific metadata |

`locator` is **not** the DataAsset identity. The identity is the asset declaration within the versioned GitRepo.

## Repository metadata required for full Operating Space reconstruction

A Twin GitRepo that carries data should expose machine-readable metadata containing at least the following concepts.

### 1. Repository role

The Twin must be able to determine that this GitRepo is a data-bearing node and, where useful, its semantic role.

```toml
[hydrological_twin]
role = "data"
```

Possible future roles may include `model`, `data`, `workflow`, `knowledge`, `configuration`, or `interface`. The exact vocabulary remains a Hydrological Twin concern, not a ComplexGitSync concern.

### 2. Data protocol version

The repository declares which contract describes its assets.

```toml
[data]
protocol = "htdata-1"
```

The protocol version makes reconstruction deterministic and allows future schema evolution.

### 3. Data assets

Each physical or logical resource is declared independently.

```toml
[[data.assets]]
name = "safran-precipitation"
resolver = "dvc"
target = "data/safran"
locator = "data/safran.dvc"
kind = "climate"
format = "netcdf"
state = "md5:..."

[data.assets.metadata]
variable = "precipitation"
unit = "mm/day"
```

### 4. Physical-data state

The Git commit reconstructs the repository state but does not necessarily reconstruct the bytes stored outside Git.

A data asset therefore needs, when the resolver supports it, an immutable physical-data state such as:

- DVC object hash;
- content checksum;
- object-store version;
- ETag with defined immutability semantics;
- immutable provider dataset version.

This gives two complementary state identities:

```text
GitRepo state  = Git commit
Data state     = DataAsset.state
```

Together they are sufficient to ask whether a reconstructed Operating Space contains the intended data state.

### 5. Materialisation target

Every asset declares where it must appear relative to the root of its GitRepo after materialisation.

This is essential because downstream models and workflows need stable Operating Space paths even when storage URIs differ between machines.

### 6. No credentials in repository metadata

Data metadata must not contain passwords, access tokens, cloud secrets, SSH keys or other user credentials.

The access rule remains:

```text
Git repository rights
        x
repository class in ComplexGitSync
        ->
what part of the Operating Space the user may materialise and modify
```

A future independent access-management component may reconcile declared Twin users with Git-provider repository permissions, but this is intentionally outside both `DataAsset` and ComplexGitSync.

## Reconstruction sequence

A complete data-aware Operating Space can be reconstructed as follows:

```text
1. ComplexGitSync resolves the Twin GitTree.
2. ComplexGitSync checks out each GitRepo at its recorded state.
3. Hydrological Twin reads the metadata of data-bearing GitRepos.
4. Each DataAsset is validated against the declared protocol.
5. The selected resolver materialises the physical data at DataAsset.target.
6. DataAsset.state is verified when available.
7. The Operating Space is READY for hydrological orchestration.
```

The exact ownership of steps 3-6 between Hydrological Twin and ComplexGitSync is deliberately not fixed by this first contract. The architectural invariant is that **CGS reconstructs the GitTree; data metadata makes the data state reconstructible as part of the same Operating Space**.

## Why this matters

This preserves a single structural primitive across the system:

```text
GitRepo = elementary Twin node
```

Code, models, documentation, workflows and data can all be represented by GitRepos. Data differs only because the physical payload may be external to Git and therefore needs a resolver and an independently verifiable data state.

The result is a Git-native Twin whose full Operating Space can be reconstructed without making physical storage location part of the Twin ontology.
