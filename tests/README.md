# HTAS Tests

This directory contains the HydrologicalTwinAlphaSeries (HTAS) test
suite. Most tests are pure unit / facade tests; this README focuses on
the one piece of infrastructure that needs explanation — the
**end-to-end smoke test on real CaWaQS data**.

## What the smoke test does

`integration/test_cwv_gis_smoke.py` walks the full HTAS macro API on a
real, light CaWaQS simulation output (the `cwv-gis-testcase` fixture):

```
configure  →  load  →  describe  →  fetch  →  transform  →  render
```

It asserts only two things:

1. No step raises an exception.
2. `render(kind="budget_barplot")` produces a PNG that exists on disk.

The point is **crash detection** when a real dataset is fed through the
public API.

## What it deliberately does NOT test

This is **not** a numerical regression test. It does not assert on:

- Array shapes or contents.
- Specific output values, sums, or means.
- Tolerances against golden reference files.
- Plot pixel content.

Numerical regression testing (golden outputs, tolerances,
`syrupy`-style snapshots, regeneration workflows) is intentionally out
of scope at this stage. The trade is: cheap to maintain now; we add
value checks later if and when a real numerical incident slips past.

## How to run it locally

Run the commands from the **HTAS repo root** (the directory containing
this submodule's `pixi.toml`). If you have cawaqsviz checked out, that
is `external/HydrologicalTwinAlphaSeries/`; if you have HTAS standalone,
it's the top of the repo. `pixi run test` is the same command CI uses,
so what you see locally is what CI sees.

```bash
# 1. Clone the testcase fixture somewhere (only this subdirectory matters)
git clone --depth 1 --filter=blob:none --sparse \
    --branch v0.1-cwv-gis-smoke-CI \
    https://gitlab.com/cawaqs/gtest/testcases.git /tmp/cawaqs-testcases
git -C /tmp/cawaqs-testcases sparse-checkout set datasets/cwv-gis-testcase

# 2. Move into the HTAS pixi env (skip if you're already there)
cd external/HydrologicalTwinAlphaSeries   # or just the HTAS repo root

# 3. Point the test at the cloned fixture and run it — should pass + write a PNG
export CWAQS_FIXTURE_ROOT=/tmp/cawaqs-testcases/datasets/cwv-gis-testcase
pixi run test tests/integration/test_cwv_gis_smoke.py -v

# 4. Verify the SKIP path — re-run without the env var, expect SKIPPED (not FAILED)
unset CWAQS_FIXTURE_ROOT
pixi run test tests/integration/test_cwv_gis_smoke.py -v
```

If `CWAQS_FIXTURE_ROOT` is unset, the test **skips cleanly** —
developers running the full suite locally without the fixture see a
`SKIPPED` line, not a failure.

## How it runs in CI

The HTAS workflow (`.github/workflows/ci.yml`) clones the fixture on
the runner using a sparse, blobless clone pinned to a **git tag**, sets
`CWAQS_FIXTURE_ROOT` via `$GITHUB_ENV`, and the existing
`pixi run test` step picks it up.

## Two things that age (and require maintenance)

The smoke test is engineered to be stable across changes that don't
touch its actual surface area. But two things will need a human update
over time:

### 1. The pinned fixture tag in `ci.yml`

The CI step clones `gitlab.com/cawaqs/gtest/testcases` at a fixed git
tag (currently `v0.1-cwv-gis-smoke-CI`). When the testcase repo
legitimately evolves and we want CI to use the new version:

- Pick the new tag on the testcase repo.
- Edit `.github/workflows/ci.yml` and bump the `--branch <tag>` value.
- Open a PR. CI will exercise the new fixture.

We pin by tag (not by branch) on purpose: branches move, tags don't —
this keeps CI deterministic.

### 2. The HTAS macro API signatures used by the test

The test calls the public macro API directly: `configure`, `load`,
`describe`, `fetch`, `transform`, `render`. If any of those signatures
change (renamed kwargs, removed kinds, restructured response objects),
the test will need a corresponding update.

This is **a feature, not a bug**: the smoke test is a guard against
silent breakage when the public API drifts. If you change a macro
signature, fixing this test should be part of the same PR.

What the test does *not* couple to:

- Internal helpers under `services/` or `domain/`.
- Specific output array shapes or values.
- Backend implementation details below the macro API.

## Why an inline `_SmokeGeoProvider` instead of cawaqsviz's `GeoDataProvider`?

`HydrologicalTwin.load` needs an object exposing
`get_layer(name) -> GeoDataFrame`. cawaqsviz ships a
`GeoDataProvider` with two branches: a QGIS-based branch and a file
path-based branch. The file-path branch is effectively
`geopandas.read_file(layer_paths[name])`.

The smoke test defines its own ~20-line `_SmokeGeoProvider` inline.
Three reasons:

1. **HTAS independence.** HTAS CI should not need to clone or import
   cawaqsviz. The backend is migrating toward a standalone /
   server-side deployment; the test reflects that destination.
2. **Closer to a real future caller.** A server-side or user-lambda
   consumer of HTAS will not import `cawaqsviz.interface.GeoDataProvider`.
   It will write its own minimal adapter — which is exactly what the
   test does.
3. **The interface is tiny.** Duplicating ~20 lines costs less than
   moving a real provider into HTAS production code. If `_SmokeGeoProvider`
   ever grows past ~40 lines, that's the signal to promote a real
   QGIS-free provider into HTAS — but as a deliberate, separate change.
