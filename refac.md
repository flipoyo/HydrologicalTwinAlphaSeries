# Refactor comparison notes

## Scope checked

- Repository checked: `HydrologicalTwinAlphaSeries`
- Remote branch fetched for comparison: `origin/HTASrefac` (`2b3e1fd`, `Refactoring for 7methods API`)
- Current local branch baseline: operational after installing `.[dev]`

## What is operational today

On the current checkout of this repository:

- `python -m ruff check src tests` ✅
- `python -m pytest` ✅ (`36 passed`)

So the backend state currently checked out in this issue branch is coherent and operational.

## What changes on `HTASrefac`

The refactor branch is not a small cleanup. It is a large API reshaping on the backend side:

- `register_compartment` is no longer part of the canonical macro API
- the documented public contract moves from **8 macro methods** to **7 canonical methods**
- several legacy methods are reclassified as **transition methods**
- the facade grows a typed request/response workflow around `describe`, `extract`, `transform`, and `render`

This means the branch is not only an internal refactor; it changes the consumer-facing contract that `cawaqsviz` would need to follow.

## Backend validation of `HTASrefac`

In a temporary worktree created from `origin/HTASrefac`:

- `python -m ruff check src tests` ❌
  - import ordering issues
  - unused import (`warnings`)
  - multiple line-length violations
- `python -m pytest` ❌
  - `35 passed, 1 failed`
  - failing test:
    - `tests/integration/test_facade_lifecycle.py::TestMacroMethods::test_render_returns_file_artefacts`
    - expected `{"kind": "budget"}`
    - got `{"kind": "budget_barplot"}`

So, from the backend side alone, `HTASrefac` cannot currently be considered fully operational.

## Coherence with PR #28

I could not directly compare against `flipoyo/HydrologicalTwinAlphaSeries#28` because the PR is not accessible from the available GitHub API context here (`404` on PR lookup).

From the repository evidence alone, the refactor branch is **not yet coherent with the currently validated backend contract**, because:

- the canonical facade contract changes materially (8 methods -> 7 methods + transition layer)
- the branch is not lint-clean
- the branch still has a failing backend test

## Can this issue be solved fully by the agent?

**Partially only.**

What can be concluded automatically from this repository:

- current backend branch is operational
- `HTASrefac` is a substantial backend API refactor
- `HTASrefac` is not yet backend-clean/releasable as-is

What still requires human handling:

- comparison with the `cawaqsviz` side of the refactor
- confirmation of intended compatibility targets for PR #28
- decision on whether the 7-method canonical contract is the desired final public API for both repositories
