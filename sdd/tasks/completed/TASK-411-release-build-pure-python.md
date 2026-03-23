# TASK-411: Add Pure Python Build Jobs (build-tools, build-loaders)

**Feature**: migrate-github-release
**Spec**: `sdd/specs/migrate-github-release.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-410
**Assigned-to**: unassigned

---

## Context

After TASK-410 establishes the `build-core` job, this task adds the two pure Python build jobs for `ai-parrot-tools` and `ai-parrot-loaders`. These packages have no Cython or Rust extensions, so they use `uv build` instead of `cibuildwheel`.

Implements **Module 2** and **Module 3** from the spec.

---

## Scope

- Add `build-tools` job to `release.yml`:
  - Runs `uv build` from `packages/ai-parrot-tools/`.
  - Produces a universal wheel + sdist.
  - Uploads artifacts.
- Add `build-loaders` job to `release.yml`:
  - Runs `uv build` from `packages/ai-parrot-loaders/`.
  - Same structure as build-tools.
  - Uploads artifacts.
- Both jobs run in parallel with `build-core` (no `needs:` dependency).

**NOT in scope**: build-core job (TASK-410), deploy job (TASK-412).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/release.yml` | MODIFY | Add build-tools and build-loaders jobs |

---

## Implementation Notes

### Pattern to Follow

```yaml
build-tools:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - name: Install uv
      uses: astral-sh/setup-uv@v4
      with:
        version: "latest"

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: "3.12"

    - name: Build package
      run: |
        cd packages/ai-parrot-tools
        uv build --out-dir ../../dist

    - name: Upload artifacts
      uses: actions/upload-artifact@v4
      with:
        name: dist-tools
        path: dist/*
```

### Key Constraints

- No `cibuildwheel` needed — these are pure Python.
- Only one Python version needed (universal wheel).
- `uv build --out-dir ../../dist` outputs to a shared dist directory.
- Artifact names must not collide with `build-core` artifacts.

### References in Codebase

- `packages/ai-parrot-tools/pyproject.toml` — tools package config
- `packages/ai-parrot-loaders/pyproject.toml` — loaders package config

---

## Acceptance Criteria

- [ ] `build-tools` job builds `ai-parrot-tools` with `uv build`
- [ ] `build-loaders` job builds `ai-parrot-loaders` with `uv build`
- [ ] Both jobs run in parallel with `build-core` (no `needs:`)
- [ ] Artifacts uploaded with unique names (`dist-tools`, `dist-loaders`)
- [ ] Workflow YAML remains valid

---

## Test Specification

```bash
# Local dry-run: verify each package builds
cd packages/ai-parrot-tools && uv build --out-dir /tmp/test-dist
cd packages/ai-parrot-loaders && uv build --out-dir /tmp/test-dist
ls /tmp/test-dist/  # Should show .whl and .tar.gz for each

# YAML validation
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-github-release.spec.md` for full context
2. **Check dependencies** — TASK-410 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** the current `.github/workflows/release.yml` (already rewritten by TASK-410)
5. **Add** `build-tools` and `build-loaders` jobs
6. **Verify** YAML is valid
7. **Move this file** to `sdd/tasks/completed/TASK-411-release-build-pure-python.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-23
**Notes**: Added build-tools and build-loaders jobs to release.yml. Both run in parallel with build-core using uv build from their respective package directories.
**Deviations from spec**: none

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
