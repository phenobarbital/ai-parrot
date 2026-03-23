# TASK-414: Release Process Documentation

**Feature**: migrate-github-release
**Spec**: `sdd/specs/migrate-github-release.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-412
**Assigned-to**: unassigned

---

## Context

The monorepo release process differs from the original single-package workflow. This task documents how to create releases, the PyPI setup required for the two new packages, and how versioning works across the three packages.

Implements **Module 5** from the spec.

---

## Scope

- Add a **Release Process** section to `README.md` (in the Contributing area) documenting:
  - How to create a GitHub release that triggers the workflow.
  - PyPI project setup: `ai-parrot-tools` and `ai-parrot-loaders` must be created on PyPI before first publish.
  - Token configuration: single `NAV_AIPARROT_API_SECRET` with upload scope for all 3 projects.
  - Independent versioning: each package has its own version in its `pyproject.toml`.
  - What the workflow does (3 parallel builds + 1 deploy).
- Keep documentation concise and actionable.

**NOT in scope**: Workflow implementation (TASK-410–412), version sync scripts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `README.md` | MODIFY | Add Release Process section under Contributing |

---

## Implementation Notes

### Content Outline

```markdown
### Releasing to PyPI

AI-Parrot publishes three packages on every GitHub release:

| Package | PyPI Project | Build Method |
|---------|-------------|-------------|
| `ai-parrot` | [ai-parrot](https://pypi.org/p/ai-parrot) | cibuildwheel (Cython + Rust) |
| `ai-parrot-tools` | [ai-parrot-tools](https://pypi.org/p/ai-parrot-tools) | uv build (pure Python) |
| `ai-parrot-loaders` | [ai-parrot-loaders](https://pypi.org/p/ai-parrot-loaders) | uv build (pure Python) |

**To create a release:**
1. Update the version in each package's `pyproject.toml` (or use `make bump-patch`)
2. Create a GitHub release — the workflow runs automatically

**First-time PyPI setup:**
- Create `ai-parrot-tools` and `ai-parrot-loaders` projects on PyPI
- Ensure `NAV_AIPARROT_API_SECRET` token has upload scope for all 3 projects
```

### Key Constraints

- Do not duplicate information already in the README.
- Keep it under the existing Contributing section.
- Reference `make bump-patch` for version management.

### References in Codebase

- `README.md` — existing Contributing section
- `.github/workflows/release.yml` — the workflow being documented
- `Makefile` — `bump-patch` target

---

## Acceptance Criteria

- [ ] README contains a Release Process section
- [ ] Documents PyPI project creation for the two new packages
- [ ] Documents token configuration
- [ ] Documents independent versioning
- [ ] Explains what the release workflow does
- [ ] Concise and actionable

---

## Test Specification

No automated tests — review documentation for accuracy and completeness.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-github-release.spec.md`
2. **Check dependencies** — TASK-412 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** the current `README.md` Contributing section
5. **Add** the Release Process documentation
6. **Move this file** to `sdd/tasks/completed/TASK-414-release-documentation.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-23
**Notes**: Added "Releasing to PyPI" section to README.md under Contributing. Documents PyPI project setup, token configuration (NAV_AIPARROT_API_SECRET), workflow structure (3 parallel builds + deploy), and independent versioning.
**Deviations from spec**: none

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
