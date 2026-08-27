# TASK-2531: Release integration — CI Node stage, wheel-content checks, docs

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2523, TASK-2525
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + §7 Known Risks. A wheel built without the Node stage
silently ships no UI — the resolved decision is a DUAL check: a
`@pytest.mark.wheel_build` test AND a release-workflow assert. Plus the
adopter/developer documentation.

---

## Scope

- **Wheel-content test**: extend
  `packages/ai-parrot-server/tests/test_wheel_layout.py` with a
  `@pytest.mark.wheel_build` test asserting the built wheel contains
  `parrot/server/ui/dist/index.html` and ≥1 file under
  `parrot/server/ui/dist/assets/`. It must FAIL when the UI build was
  skipped and pass after `pnpm build`.
- **Release pipeline**: add the UI build stage before `uv build` /
  `uv publish` for `ai-parrot-server`:
  - Steps: setup Node **24 LTS** + pnpm **9** (corepack) → `pnpm install
    --frozen-lockfile` → `pnpm generate` → `pnpm build` → assert
    `src/parrot/server/ui/dist/index.html` exists → proceed to wheel build.
  - Locate the actual release path first: `Makefile` publish targets
    (`Makefile:312-323`, `uv publish dist/ai_parrot_server-*` at `:320`)
    and any `.github/workflows/*` release/publish workflow — wire the stage
    into whichever actually builds the server wheel (inspect, then decide;
    record the choice in the completion note).
- **Docs**: create `docs/admin-ui.md`:
  - Adopter view: what `/admin` is, auth model (navigator-auth, any
    authenticated user), pip-install-and-run, the git-install caveat
    (WARNING + no UI without Node build).
  - Developer view: `cd packages/ai-parrot-server/ui && pnpm install &&
    pnpm dev` with API proxy to a running server; `pnpm generate` codegen;
    where dist lands; how the wheel check works.
- Update `packages/ai-parrot-server/README`/docs index if one references
  features (check first).

**NOT in scope**: any UI/Python feature code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | MODIFY | add wheel-content test |
| `Makefile` and/or `.github/workflows/<release>.yml` | MODIFY | Node build stage + assert |
| `docs/admin-ui.md` | CREATE | adopter + developer docs |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot-server/tests/test_wheel_layout.py
FORBIDDEN_INIT_PATHS  # :16-25 — do not touch
class TestWheelHasNoInitAtNamespaceLevels:  # :42, marked @pytest.mark.wheel_build
class TestSatelliteSourceLayout:            # :57
# Follow this file's existing wheel-building fixture/marker mechanics for the
# new test — read the file first; reuse its wheel-build helper rather than
# inventing a new one.
```

```make
# Makefile:312-323 — publish targets; :320:
#   uv publish dist/ai_parrot_server-*.tar.gz dist/ai_parrot_server-*.whl
# Makefile has NO npm/vite/frontend targets today (:808/:814 npm lines are
# MCP-server installs, unrelated).
```

### Verified environment facts
- `dist/` is gitignored (TASK-2523) — release MUST build it; installs from
  git legitimately lack it (spec acceptance criterion).
- UI project: `packages/ai-parrot-server/ui/`, pnpm 9, Node 24 LTS engines,
  committed `pnpm-lock.yaml` (TASK-2525); `pnpm generate` real after
  TASK-2526.
- **Pushing branches that touch `.github/workflows/*` requires the SSH
  remote** — the gh OAuth token lacks `workflow` scope. The feature branch
  push at /sdd-done time must use `git@github.com`.

### Does NOT Exist
- ~~frontend build tooling in the Python build today~~ — no setuptools
  hook, no Makefile target; this task adds the FIRST one.
- ~~a `wheel_build` CI job guaranteed to run on PRs~~ — check how
  `@pytest.mark.wheel_build` is invoked (grep CI configs / Makefile for the
  marker) and document where the new test actually executes.
- ~~`parrot/server/ui/dist/` in package-data before TASK-2523~~ — verify
  TASK-2523 landed the pyproject entry before asserting wheel contents.

---

## Implementation Notes

### Key Constraints
- The release stage must fail LOUDLY if Node/pnpm are unavailable — never
  fall through to publishing a UI-less wheel.
- Use corepack (`corepack enable && corepack prepare pnpm@9 --activate`) or
  the setup-node pnpm cache in workflows — match whatever the repo's
  existing workflows use for tool setup (inspect `.github/workflows/` first).
- Docs in English; concise; link from the spec's acceptance criterion.

### References in Codebase
- Spec §5 acceptance criteria (wheel/no-Node, git-install caveat, docs).
- `docs/migration/feat-201-ai-parrot-embeddings.md` — docs tone/structure
  precedent.

---

## Acceptance Criteria

- [ ] Wheel built WITH the UI stage passes the new test; wheel built
  without it fails the test (demonstrate both in the completion note).
- [ ] Release path (Makefile target and/or workflow) runs
  install→generate→build→assert before `uv build`, pinned Node 24 + pnpm 9.
- [ ] `docs/admin-ui.md` covers adopter + developer flows incl. the
  git-install caveat.
- [ ] `pytest packages/ai-parrot-server/tests/test_wheel_layout.py -v -m wheel_build` passes locally after `pnpm build`.
- [ ] No other Makefile/workflow behavior changed.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_wheel_layout.py (addition)
@pytest.mark.wheel_build
class TestWheelContainsAdminUI:
    def test_dist_index_present(self, built_wheel):  # reuse existing fixture
        names = built_wheel.namelist()
        assert "parrot/server/ui/dist/index.html" in names
        assert any(n.startswith("parrot/server/ui/dist/assets/") for n in names)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2523 and TASK-2525 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `test_wheel_layout.py` and the
   existing workflows/Makefile targets before modifying anything
4. **Update status** in `sdd/tasks/index/ui-server-backend.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
