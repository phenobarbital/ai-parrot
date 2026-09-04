# TASK-2791: CI freshness gate for Tailwind CSS + vendored map assets

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2789
**Assigned-to**: unassigned

---

## Context

Spec §8 resolved decision: the CSS staleness check must **fail the build**
outright (no warn-and-allow-merge fallback). Spec §2/§3 Module 6 corrects the
brainstorm's original suggestion (mirror `release.yml`'s Node/pnpm build step) —
that job builds and ships the Admin UI *into the wheel* at release time, a
different shape than what's needed here. The right precedent is
`.github/workflows/ci.yml`'s existing `lint-and-registry` job, which already has
a "Check registry freshness" step (`uv run python
scripts/generate_tool_registry.py --check`) doing exactly this
generate-and-diff shape for a different asset (the tool registry).

This task wires TASK-2789's `scripts/generate_a2ui_css.py --check` into that
same job, as a new step immediately after "Check registry freshness".

## Scope

- Add a new step to `.github/workflows/ci.yml`'s `lint-and-registry` job,
  positioned after the existing "Check registry freshness" step
  (`ci.yml:29-30`) and before "Check SDD TASK-ID collisions":
  ```yaml
  - name: Check A2UI Tailwind CSS + map-asset freshness
    run: uv run python scripts/generate_a2ui_css.py --check
  ```
- Verify `lint-and-registry`'s existing `uv sync --all-packages` step (line 26)
  already installs `ai-parrot-visualizations` (needed for the script's AST scan
  of `interactive_html.py` and its CSS-generation dependencies) — if it does
  not, the workspace-wide sync should already cover it as a uv workspace
  member; confirm rather than assume, and add whatever minimal step is needed
  if the package isn't actually available in that job's environment (e.g. a
  Tailwind CLI binary the job needs to install — check whether
  `generate_a2ui_css.py` needs Node/the Tailwind CLI present in this job's
  runner, and if so add the minimal `actions/setup-node`+Tailwind CLI install
  steps this job is currently missing, following the exact
  `actions/setup-node@v4` pattern already used elsewhere in `release.yml` for
  consistency).
- The `--check` mode must ALSO surface a vendored-asset staleness failure (spec
  §3 Module 6: "a future `folium` version bump that silently adds/renames a
  default resource this feature hasn't vendored yet") — if TASK-2789 didn't
  already build this sub-check into `--check`, this task must extend
  `generate_a2ui_css.py --check` (or add a second, adjacent CI step calling a
  distinct check) to introspect the CI runner's installed `folium` package
  live and assert every `default_js`/`default_css` name has a corresponding
  vendored file (same assertion shape as TASK-2785's
  `test_all_folium_default_resources_have_a_vendored_path` unit test, but
  running as a CI gate, not just a pytest case, so it also catches drift that
  happens purely from a `folium` version bump in `pyproject.toml`/`uv.lock`
  with no code change at all).

**NOT in scope**:
- The script's core generation/scan logic (TASK-2789, already done).
- `DesignSystem` integration (TASK-2790, already done).
- Any other CI job/workflow file beyond `ci.yml`'s `lint-and-registry` job.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | New step in `lint-and-registry` job |

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```yaml
# .github/workflows/ci.yml — existing job (verify exact content before editing)
jobs:
  lint-and-registry:
    name: Lint & Registry Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - name: Sync all workspace packages
        run: uv sync --all-packages
      - name: Check registry freshness
        run: uv run python scripts/generate_tool_registry.py --check
      # <-- NEW STEP GOES HERE -->
      - name: Check SDD TASK-ID collisions (FEAT-387)
        run: |
          uv run python -m scripts.sdd.check_id_collisions \
            --baseline scripts/sdd/.collision_baseline.json
```

### Does NOT Exist
- ~~A `map-css-freshness`/similar dedicated CI job already~~ — confirmed
  absent by direct read of `ci.yml` at spec time; this task adds a step to the
  EXISTING `lint-and-registry` job, not a new job.
- ~~Node/pnpm/Tailwind CLI setup already present in `lint-and-registry`~~ —
  that job currently only sets up Python + uv (verify this remains true before
  implementing; if TASK-2789's script needs a Tailwind binary present in CI
  and it's not there yet, this task must add it).

---

## Implementation Notes

### Pattern to Follow
Mirror the "Check registry freshness" step exactly in shape (one `run:` line
invoking the script's `--check` flag, no extra job-level complexity) — this is
a proven, minimal pattern already working in this exact job for a structurally
identical problem (generate-from-source, diff, fail on drift).

### Key Constraints
- **Fail the build on drift — no warn-only mode** (spec §8 resolved decision,
  explicit). Do not add a `continue-on-error: true` or similar softening.
- Keep the new step inside the EXISTING `lint-and-registry` job rather than
  creating a new job — spec §3 Module 6 explicitly calls this out as "a closer
  match" than a separate release-style job.

### References in Codebase
- `.github/workflows/ci.yml` — file being modified.
- `.github/workflows/release.yml:273-295` — Node/pnpm setup pattern to borrow FROM (not mirror wholesale — only if a Tailwind CLI binary setup step turns out to be needed in this job).

---

## Acceptance Criteria

- [ ] `.github/workflows/ci.yml`'s `lint-and-registry` job runs `uv run python
  scripts/generate_a2ui_css.py --check` as a new step.
- [ ] The step fails the job (non-zero exit propagates to CI failure) when the
  committed `tailwind.generated.css` is stale relative to
  `interactive_html.py`'s current class vocabulary.
- [ ] The step (or a sibling step in the same job) fails when a vendored map
  asset is missing relative to the CI runner's installed `folium` package's
  live `default_js`/`default_css` names.
- [ ] The step passes on a clean checkout with no drift.
- [ ] No other existing `ci.yml` step/job is modified.
- [ ] `yamllint .github/workflows/ci.yml` (or equivalent, if configured in this
  repo) reports no new errors — verify what YAML validation, if any, this repo
  already runs before assuming a specific linter.

---

## Test Specification

This task's correctness is verified operationally (the CI job itself is the
test), but include a local dry-run check as part of implementation:

```bash
# Simulate the CI job locally before pushing:
uv sync --all-packages
uv run python scripts/generate_a2ui_css.py --check
echo "exit code: $?"
```

No new pytest file is required for this task specifically (TASK-2794 covers
the underlying script's own `--check` behavior as pytest cases; this task only
wires that already-tested behavior into the workflow YAML).

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §2, §3
   Module 6, §8.
2. **Check dependencies** — verify TASK-2789 is in `sdd/tasks/completed/`
   before starting (this task wires its `--check` mode into CI).
3. Read the current `.github/workflows/ci.yml` in full before editing.
4. Update status in the per-spec index → `"in-progress"`.
5. Implement per scope.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update the per-spec index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-09-03
**Notes**: Added two new steps (plus a Node.js setup step) to the existing
`lint-and-registry` job in `ci.yml`, positioned after "Check registry
freshness" and before "Check SDD TASK-ID collisions" — no other step/job
touched (verified via `git diff` scope). (1) `actions/setup-node@v4`
(`node-version: "24"`, matching `release.yml`'s pinned major version) since
`generate_a2ui_css.py` shells out to the Tailwind v4 CLI via `npm install`,
and this job otherwise only provisions Python/uv. (2) "Check A2UI Tailwind
CSS freshness" runs `generate_a2ui_css.py --check` (TASK-2789's output,
unmodified — no `--check` extension was needed there). (3) Per spec §3
Module 6, added the vendored-asset-staleness sub-check as "a second,
adjacent CI step" (the task's own sanctioned alternative to extending
`generate_a2ui_css.py --check` itself) rather than modifying that script —
this kept the change scoped to exactly the one file
(`.github/workflows/ci.yml`) TASK-2791's own Files-to-Modify table lists.
That step first syncs `ai-parrot-visualizations[map]` explicitly (folium is
an optional extra, not part of the workspace-wide `uv sync --all-packages`),
then runs an inline `uv run python -c "..."` script that introspects the
CI runner's actually-installed `folium`/`MarkerCluster`'s live
`default_js`/`default_css` names against `_map_vendor.VENDORED_ASSET_PATHS`
and exits 1 with a clear per-name message on any gap — same assertion shape
as TASK-2785's `test_all_folium_default_resources_have_a_vendored_path`
unit test, but as a CI gate that also catches a pure `folium` version bump
with zero code change. Verified end-to-end: (a) `python -c "import yaml;
yaml.safe_load(...)"` confirms the file parses as valid YAML and the
embedded Python block's indentation survives YAML's block-scalar
de-indentation correctly (confirmed by extracting `run:` step content and
`bash -n`-checking it, then executing it directly against this venv with
folium installed — exits 0, prints "Vendored map assets are up to date.");
(b) a simulated-drift run (empty vendored-mapping) exits 1 and names every
missing resource; (c) no `yamllint`/equivalent is configured anywhere in
this repo (verified — AC's "if configured" caveat does not apply). No
Cargo.build side effects landed in this commit (an earlier local `uv run`
verification pass accidentally regenerated `packages/navrules/rust/Cargo.lock`
and created a stray project-local `.venv/` in the worktree from `uv run`
building a fresh environment instead of using the pre-activated main-repo
venv — both were caught and reverted/discarded before this commit;
documented as a lesson for future `uv run` invocations in this worktree
setup).

**Deviations from spec**: none. One implementation choice the task
explicitly offered as an alternative: the vendored-asset staleness
sub-check was added as "a second, adjacent CI step" rather than folded
into `generate_a2ui_css.py --check` itself (both were explicitly sanctioned
by the task text) — chosen specifically to respect this task's own
Files-to-Modify table, which lists only `.github/workflows/ci.yml`.
