# Feature Specification: Migrate GitHub Release Workflow

**Feature ID**: FEAT-058
**Date**: 2026-03-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x (post-monorepo)

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `.github/workflows/release.yml` builds and publishes a single `ai-parrot` wheel to PyPI. After FEAT-057 (monorepo-migration), the repository contains three independent packages:

- `packages/ai-parrot/` — core framework
- `packages/ai-parrot-tools/` — tools & toolkits
- `packages/ai-parrot-loaders/` — document loaders

The existing workflow:
1. Runs `cibuildwheel` at the repo root — this no longer works because the root `pyproject.toml` is now a workspace root (not a package).
2. Publishes only `ai-parrot` — `ai-parrot-tools` and `ai-parrot-loaders` are never built or published.
3. Uses the Rust/Maturin build for `parrot/yaml_rs` — this now lives inside `packages/ai-parrot/src/parrot/yaml_rs`.
4. Has a hardcoded PyPI environment URL for a single package.

### Goals

1. **Build all 3 packages**: The release workflow builds wheels for `ai-parrot`, `ai-parrot-tools`, and `ai-parrot-loaders`.
2. **Publish all 3 to PyPI**: Each package published to its own PyPI project with trusted publishing.
3. **Rust/Cython builds**: The `ai-parrot` core package still requires Rust (maturin/yaml_rs) and Cython extensions — build these correctly from the `packages/ai-parrot/` directory.
4. **Pure Python packages**: `ai-parrot-tools` and `ai-parrot-loaders` are pure Python — no cibuildwheel needed, just `uv build`.
5. **Independent versioning**: Each package has its own version. All 3 are built and published on the same release event.
6. **Backward-compatible release trigger**: Still triggered by GitHub release creation.

### Non-Goals (explicitly out of scope)

- Independent per-package versioning — all 3 packages release together.
- Separate release triggers per package — one release = all 3 packages.
- Changes to `ci.yml` or `codeql-analysis.yml` — only `release.yml`.
- PyPI trusted publishing setup (that's a manual PyPI config step, documented but not automated).

---

## 2. Architectural Design

### Overview

The workflow splits into 3 parallel build jobs + 1 deploy job:

```
release event
    │
    ├── build-core (cibuildwheel + maturin for ai-parrot)
    │     └── artifacts: ai_parrot-*.whl
    │
    ├── build-tools (uv build for ai-parrot-tools)
    │     └── artifacts: ai_parrot_tools-*.whl + sdist
    │
    ├── build-loaders (uv build for ai-parrot-loaders)
    │     └── artifacts: ai_parrot_loaders-*.whl + sdist
    │
    └── deploy (needs: build-core, build-tools, build-loaders)
          ├── download all artifacts
          └── twine upload dist/*
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.github/workflows/release.yml` | replaces | Complete rewrite for monorepo |
| `packages/ai-parrot/pyproject.toml` | reads | Core package build config |
| `packages/ai-parrot-tools/pyproject.toml` | reads | Pure Python package |
| `packages/ai-parrot-loaders/pyproject.toml` | reads | Pure Python package |
| PyPI `ai-parrot` project | publishes | Existing project |
| PyPI `ai-parrot-tools` project | publishes | **NEW** — must be created on PyPI |
| PyPI `ai-parrot-loaders` project | publishes | **NEW** — must be created on PyPI |

### New Public Interfaces

No code changes — this is a CI/CD workflow change only.

---

## 3. Module Breakdown

### Module 1: Core Package Build Job
- **Path**: `.github/workflows/release.yml` (build-core job)
- **Responsibility**: Build `ai-parrot` wheels with cibuildwheel (Cython + Rust/Maturin). Must `cd packages/ai-parrot` before building. Multi-Python matrix (3.10, 3.11, 3.12). Upload wheel artifacts.
- **Depends on**: none

### Module 2: Tools Package Build Job
- **Path**: `.github/workflows/release.yml` (build-tools job)
- **Responsibility**: Build `ai-parrot-tools` with `uv build` from `packages/ai-parrot-tools/`. Pure Python — no cibuildwheel needed. Single job, produces universal wheel + sdist.
- **Depends on**: none

### Module 3: Loaders Package Build Job
- **Path**: `.github/workflows/release.yml` (build-loaders job)
- **Responsibility**: Build `ai-parrot-loaders` with `uv build` from `packages/ai-parrot-loaders/`. Pure Python — same as Module 2.
- **Depends on**: none

### Module 4: Deploy Job
- **Path**: `.github/workflows/release.yml` (deploy job)
- **Responsibility**: Download all artifacts from the 3 build jobs. Publish all wheels/sdists to PyPI via twine. Use existing `NAV_AIPARROT_API_SECRET` or per-package tokens.
- **Depends on**: Module 1, Module 2, Module 3

### Module 5: Documentation
- **Path**: `docs/` or `README.md`
- **Responsibility**: Document the release process for the monorepo: how to create PyPI projects for `ai-parrot-tools` and `ai-parrot-loaders`, how the single token covers all 3, and how independent versioning works.
- **Depends on**: Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_version_sync` | Module 5 | Script that reads all 3 pyproject.toml and asserts same version |

### Integration Tests

| Test | Description |
|---|---|
| Dry-run build | Run `uv build` locally for each package, verify wheels are produced |
| Workflow syntax | `actionlint` on the workflow file |

---

## 5. Acceptance Criteria

- [ ] `release.yml` builds all 3 packages on release event
- [ ] `ai-parrot` core still builds with cibuildwheel (Cython + Rust)
- [ ] `ai-parrot-tools` builds as pure Python wheel + sdist
- [ ] `ai-parrot-loaders` builds as pure Python wheel + sdist
- [ ] All 3 published to PyPI in the deploy job
- [ ] Each package built with its own independent version from its `pyproject.toml`
- [ ] Workflow passes `actionlint` validation
- [ ] Existing `NAV_AIPARROT_API_SECRET` usage preserved (or documented token setup)

---

## 6. Implementation Notes & Constraints

### Key workflow structure

```yaml
jobs:
  build-core:
    # cd packages/ai-parrot && cibuildwheel

  build-tools:
    # cd packages/ai-parrot-tools && uv build

  build-loaders:
    # cd packages/ai-parrot-loaders && uv build

  deploy:
    needs: [build-core, build-tools, build-loaders]
    # twine upload all wheels (single token)
```

### cibuildwheel working directory

`cibuildwheel` must run from `packages/ai-parrot/` where `pyproject.toml` and `setup.py` live. The `CIBW_BEFORE_BUILD` step needs Rust installed for the yaml_rs extension. Cython extension source paths in `setup.py` are already updated to `src/parrot/utils/types.pyx` (done in TASK-398).

### Pure Python builds

For `ai-parrot-tools` and `ai-parrot-loaders`:
```bash
cd packages/ai-parrot-tools
uv build --out-dir ../../dist
```
This produces a universal `.whl` and `.tar.gz` — no compilation needed.

### PyPI token strategy

**Decision**: Single token (`NAV_AIPARROT_API_SECRET`) with upload scope for all 3 projects under the same PyPI account.

### Known Risks / Gotchas

- **New PyPI projects**: `ai-parrot-tools` and `ai-parrot-loaders` must be created on PyPI before first publish.
- **cibuildwheel working directory**: Must be set correctly or it will try to build the workspace root.
- **Version independence**: Each package version is bumped independently — no sync required.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| No new dependencies | — | CI/CD change only |

---

## 7. Open Questions

- [x] Which PyPI token strategy? — *Resolved: single token (`NAV_AIPARROT_API_SECRET`) for all 3 projects*
- [x] Should `ai-parrot-tools` and `ai-parrot-loaders` PyPI projects be created under the same PyPI account/org? — *Resolved: yes, same PyPI account for all 3*
- [x] Should we add a version-bump script that updates all 3 pyproject.toml at once? — *Resolved: no, version bump is independent per package*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (single worktree, sequential tasks)
- Only `.github/workflows/release.yml` and potentially a `scripts/check_versions.py` are modified.
- **Cross-feature dependencies**: FEAT-057 (monorepo-migration) must be merged first — the workspace structure must exist.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-23 | Jesus Lara | Initial draft |
