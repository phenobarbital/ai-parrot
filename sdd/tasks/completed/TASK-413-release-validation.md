# TASK-413: Validation — Actionlint & Dry-Run Builds

**Feature**: migrate-github-release
**Spec**: `sdd/specs/migrate-github-release.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-412
**Assigned-to**: unassigned

---

## Context

After the full `release.yml` is assembled (TASK-410 through TASK-412), this task validates the workflow end-to-end: syntax checking with `actionlint`, YAML validation, and local dry-run builds for each package to confirm they produce the expected artifacts.

Implements the **Test Specification** section of the spec.

---

## Scope

- Run `actionlint` on `.github/workflows/release.yml` and fix any issues.
- Validate YAML syntax programmatically.
- Dry-run `uv build` for `packages/ai-parrot-tools/` and `packages/ai-parrot-loaders/` to confirm wheel + sdist are produced.
- Verify the workflow structure: 3 build jobs + 1 deploy job, correct `needs:` dependencies.
- Fix any issues found during validation.

**NOT in scope**: Actually running the workflow on GitHub, PyPI project creation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/release.yml` | MODIFY | Fix any issues found during validation |

---

## Implementation Notes

### Validation Steps

```bash
# 1. YAML syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"

# 2. actionlint (install if needed)
# actionlint .github/workflows/release.yml

# 3. Structural checks
python -c "
import yaml
wf = yaml.safe_load(open('.github/workflows/release.yml'))
jobs = wf['jobs']
assert 'build-core' in jobs, 'Missing build-core job'
assert 'build-tools' in jobs, 'Missing build-tools job'
assert 'build-loaders' in jobs, 'Missing build-loaders job'
assert 'deploy' in jobs, 'Missing deploy job'
assert set(jobs['deploy']['needs']) == {'build-core', 'build-tools', 'build-loaders'}
print('All structural checks passed')
"

# 4. Dry-run builds
cd packages/ai-parrot-tools && uv build --out-dir /tmp/validate-dist
cd packages/ai-parrot-loaders && uv build --out-dir /tmp/validate-dist
ls -la /tmp/validate-dist/
```

### Key Constraints

- `actionlint` may not be installed — install it or skip gracefully.
- Dry-run for `ai-parrot` core requires Rust + Cython, which may not be available locally. Validate the YAML config instead.

---

## Acceptance Criteria

- [ ] Workflow passes YAML syntax validation
- [ ] Workflow passes `actionlint` (or issues documented if actionlint unavailable)
- [ ] `uv build` succeeds for `ai-parrot-tools` (produces .whl + .tar.gz)
- [ ] `uv build` succeeds for `ai-parrot-loaders` (produces .whl + .tar.gz)
- [ ] Workflow structure verified: 4 jobs, correct dependencies
- [ ] Any issues found are fixed in `release.yml`

---

## Test Specification

The validation steps above ARE the tests for this task.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-github-release.spec.md`
2. **Check dependencies** — TASK-412 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Run** all validation steps
5. **Fix** any issues found in `release.yml`
6. **Move this file** to `sdd/tasks/completed/TASK-413-release-validation.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-23
**Notes**: All validations passed. YAML syntax OK, structural checks OK (4 jobs, correct depends), uv build dry-run produced .whl and .tar.gz for both ai-parrot-tools and ai-parrot-loaders. actionlint not installed locally but YAML is clean. No fixes needed in release.yml.
**Deviations from spec**: none

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
