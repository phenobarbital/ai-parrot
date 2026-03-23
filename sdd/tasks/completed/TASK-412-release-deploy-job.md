# TASK-412: Add Deploy Job — Publish All Packages to PyPI

**Feature**: migrate-github-release
**Spec**: `sdd/specs/migrate-github-release.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-410, TASK-411
**Assigned-to**: unassigned

---

## Context

After TASK-410 and TASK-411 create the three build jobs, this task adds the `deploy` job that downloads all artifacts and publishes them to PyPI. This replaces the old deploy job that only published `ai-parrot`.

Implements **Module 4** from the spec.

---

## Scope

- Add `deploy` job to `release.yml`:
  - `needs: [build-core, build-tools, build-loaders]`
  - Downloads all artifacts from the three build jobs.
  - Publishes all wheels and sdists to PyPI using `twine`.
  - Uses the existing `NAV_AIPARROT_API_SECRET` secret (single token for all 3 projects).
  - Sets up the `pypi` environment with `id-token: write` permission.
- Ensure artifact download merges all dist files into a single directory.

**NOT in scope**: Build jobs (TASK-410, TASK-411), documentation (TASK-413).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/release.yml` | MODIFY | Add deploy job |

---

## Implementation Notes

### Pattern to Follow

```yaml
deploy:
  needs: [build-core, build-tools, build-loaders]
  runs-on: ubuntu-latest
  if: github.event_name == 'release'
  environment:
    name: pypi
  permissions:
    id-token: write
  steps:
    - name: Install uv
      uses: astral-sh/setup-uv@v4
      with:
        version: "latest"

    - name: Download all artifacts
      uses: actions/download-artifact@v4
      with:
        path: dist-artifacts

    - name: Collect all distributions
      run: |
        mkdir -p dist
        find dist-artifacts -name '*.whl' -o -name '*.tar.gz' | xargs -I{} mv {} dist/

    - name: List distributions
      run: ls -l dist

    - name: Publish to PyPI
      run: |
        uv tool install twine
        uv tool run twine upload dist/* --username __token__ --password ${{ secrets.NAV_AIPARROT_API_SECRET }}
```

### Key Constraints

- Single PyPI token (`NAV_AIPARROT_API_SECRET`) must have upload scope for all 3 projects.
- `ai-parrot-tools` and `ai-parrot-loaders` PyPI projects must exist before the first deploy (manual step, documented in TASK-413).
- Upload all files (`dist/*`), not just `*-manylinux*.whl` — pure Python packages produce platform-independent wheels.

### References in Codebase

- `.github/workflows/release.yml` — current deploy job pattern
- Spec section 6: "PyPI token strategy"

---

## Acceptance Criteria

- [ ] `deploy` job depends on all three build jobs
- [ ] Downloads artifacts from `build-core`, `build-tools`, and `build-loaders`
- [ ] Publishes all wheels and sdists (not just manylinux)
- [ ] Uses `NAV_AIPARROT_API_SECRET` secret
- [ ] `pypi` environment configured with `id-token: write`
- [ ] Workflow YAML remains valid

---

## Test Specification

```bash
# YAML validation
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"

# Verify deploy job structure
python -c "
import yaml
wf = yaml.safe_load(open('.github/workflows/release.yml'))
deploy = wf['jobs']['deploy']
assert set(deploy['needs']) == {'build-core', 'build-tools', 'build-loaders'}
print('deploy.needs OK')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-github-release.spec.md` for full context
2. **Check dependencies** — TASK-410 and TASK-411 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** the current `.github/workflows/release.yml`
5. **Add** the `deploy` job
6. **Verify** YAML is valid and job dependencies are correct
7. **Move this file** to `sdd/tasks/completed/TASK-412-release-deploy-job.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-23
**Notes**: Added deploy job that depends on all 3 build jobs. Downloads all artifacts, collects them into dist/, publishes all wheels and sdists to PyPI using NAV_AIPARROT_API_SECRET.
**Deviations from spec**: none

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
