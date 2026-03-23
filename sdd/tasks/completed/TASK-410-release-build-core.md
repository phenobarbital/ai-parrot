# TASK-410: Rewrite release.yml — Core Package Build Job

**Feature**: migrate-github-release
**Spec**: `sdd/specs/migrate-github-release.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The existing `release.yml` runs `cibuildwheel` at the repo root, which no longer works after the monorepo migration (FEAT-057). The root `pyproject.toml` is now a workspace root, not a package.

This task rewrites the workflow foundation: the `build-core` job that builds `ai-parrot` wheels using `cibuildwheel` from `packages/ai-parrot/`, where the Cython and Rust/Maturin extensions live.

Implements **Module 1** from the spec.

---

## Scope

- Rewrite `.github/workflows/release.yml` replacing the current single `build` job with a `build-core` job.
- The `build-core` job must:
  - Run `cibuildwheel` from `packages/ai-parrot/` (not the repo root).
  - Install Rust for the `yaml_rs` maturin extension.
  - Build for Python 3.10, 3.11, 3.12 on `ubuntu-latest`.
  - Set `CIBW_BEFORE_BUILD` to install Rust inside the cibuildwheel container.
  - Set correct `RUST_SUBPACKAGE_PATH` pointing to `src/parrot/yaml_rs`.
  - Upload wheel artifacts with `actions/upload-artifact@v4`.
- Keep the release trigger (`on: release: types: [created]`).
- Remove the old `build` and `deploy` jobs entirely (they will be re-added in subsequent tasks).

**NOT in scope**: build-tools job, build-loaders job, deploy job (TASK-411, TASK-412).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/release.yml` | MODIFY | Rewrite with build-core job |

---

## Implementation Notes

### Pattern to Follow

The existing workflow structure is close but needs the working directory changed:

```yaml
jobs:
  build-core:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest]
        python-version: ["3.10", "3.11", "3.12"]
    defaults:
      run:
        working-directory: packages/ai-parrot
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install Rust
        uses: actions-rs/toolchain@v1
        with:
          profile: minimal
          toolchain: stable
          override: true
      # ... cibuildwheel from packages/ai-parrot
```

### Key Constraints

- `cibuildwheel` must run from `packages/ai-parrot/` where `pyproject.toml` and `setup.py` live.
- `CIBW_BEFORE_BUILD` installs Rust inside the container for `yaml_rs`.
- The Cython extension source is at `src/parrot/utils/types.pyx` (updated in TASK-398).
- Artifact names must be unique and distinguishable (prefix with `core-`).

### References in Codebase

- `.github/workflows/release.yml` — current workflow to replace
- `packages/ai-parrot/pyproject.toml` — core package build config
- `packages/ai-parrot/setup.py` — Cython/Maturin build setup

---

## Acceptance Criteria

- [ ] `build-core` job uses `cibuildwheel` from `packages/ai-parrot/` directory
- [ ] Rust toolchain installed for `yaml_rs` maturin build
- [ ] Builds for Python 3.10, 3.11, 3.12 on ubuntu-latest
- [ ] Wheel artifacts uploaded with descriptive names
- [ ] Workflow file passes basic YAML syntax validation
- [ ] Old monolithic `build` and `deploy` jobs removed

---

## Test Specification

```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"

# Validate with actionlint (if available)
actionlint .github/workflows/release.yml
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-github-release.spec.md` for full context
2. **Check dependencies** — no dependencies for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** the current `.github/workflows/release.yml` to understand existing structure
5. **Rewrite** the workflow with only the `build-core` job
6. **Verify** YAML is valid
7. **Move this file** to `sdd/tasks/completed/TASK-410-release-build-core.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-23
**Notes**: Rewrote release.yml replacing the old single build+deploy jobs with a new build-core job that runs cibuildwheel from packages/ai-parrot/ with Python 3.10, 3.11, 3.12 matrix.
**Deviations from spec**: none

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
