# TASK-3958: [W0.3] Agent Studio API contract doc first (part of M12)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Spec task label**: W0.3 (spec §3 "Task plan") — **early subset** (§3 "Early subset and release gate"; no sibling-spec dependency)

---

## Context

Spec §3 W0.3 / Module 12 and AC21. The UI (navigator-svelte) and the host (FieldSync) must code
against a written contract before the implementation lands. This task writes the FEAT-605 contract
into `docs/agent_studio_api.md` from the spec, **before** the code: host modes, the exhaustive route
policy table, error codes and statuses (X14), `GET /me`, PATCH bodies, visibility fields on GETs,
mount hooks and mount order, request-context keys (`studio_scope`), the behaviour matrix opted-in
vs plain host, and the release gate (AC30).

Unblocks: **U-SV** (UI mocks against it).

---

## Scope

- Add a "Tenant scope & visibility (FEAT-605)" part to `docs/agent_studio_api.md` covering: host modes
  table (§2), access rule summary, exhaustive route-policy table (§2 "Route policy"), error codes with
  HTTP statuses (FEAT-605 codes + the TOOLKITS/STORAGE codes that pass through, X14), `GET {prefix}/me`
  body, `PATCH …/visibility` body (`VisibilityUpdateRequest`), the six visibility fields on single-record
  GETs, mount hooks (`setup_studio_routes(prefix=, view_wrapper=)`, `BotManager.setup(studio_routes=)`,
  `setup_registry_only(app, *, import_modules=False, load_definitions=False)`) and the documented mount order,
  `RequestContext.kwargs["studio_scope"]` shape, plain-host behaviour changes, release gate.
- Mark `setup_registry_only` **"incomplete lifecycle — not recommended to tenant hosts"** (removed by TASK-3965).
- Mark the early subset as "not tenant-ready; keep `studio_enabled=False` for tenants" (C34, AC30).
- Add a small doc-check test that pins the presence of every error code, every route row and the
  "incomplete lifecycle" warning.

**NOT in scope**: CHANGELOG and version bump (TASK-3974); finalising the doc against the code (TASK-3974); storage (`docs/agentstudio/db-storage.md`, FEAT-621 W4) and host-toolkit guide pages (FEAT-622).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent_studio_api.md` | MODIFY | Add the FEAT-605 contract part (host modes, route table, codes, /me, PATCH, mount hooks, context keys) |
| `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` | CREATE | Doc-presence test: codes, routes, `/me` fields, mount-hook names, 'incomplete lifecycle' marker |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified for this task at `32b1a45d4`, `dev`). The implementing agent MUST use these
> exact imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed, VERIFY it
> exists first with `grep` or `read`. Paths are relative to the repo root unless a line says
> otherwise; `S/` = `packages/ai-parrot-server/src/parrot/handlers/`.

### Verified Imports
```python
from pathlib import Path  # stdlib — the doc test reads docs/agent_studio_api.md relative to the repo root
```

### Existing Signatures to Use
```python
# docs/agent_studio_api.md — existing FEAT-467/FEAT-593 API doc (29 KB); append a new top-level section
# packages/ai-parrot-server/tests/test_feat593_docs.py — precedent for a doc-presence test
```

### Does NOT Exist
- ~~`GET /astudio/me`~~ (only `/agents/{name}/toolkits/{slug}/me` exists today) — document as NEW
- ~~`/api/v1/{tenant}/astudio`~~ — new mount shape, document as host-chosen prefix
- ~~`STUDIO_VISIBILITY_DDL`~~, ~~`ensure_studio_visibility_schema`~~, ~~tenant columns on `navigator.ai_bots`~~ — v0.1 only; do NOT document
- ~~a composite `on_startup` hook~~ — dropped by C39; do not document

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/agent_studio_api.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
`packages/ai-parrot-server/tests/test_feat593_docs.py` — a doc test that greps the API doc for required strings.

### Key Constraints
- Copy names and codes verbatim from spec §2 / X14: `name_taken` 409, `declarative_only` 422, `studio_disabled` 404, `tenant_mismatch` 403, `authoring_denied` 403, `reserved_config_key` 400, `tenant_required` 422, `groups_required` 422, plus `groups_not_allowed` 422 (§8 Q2); pass-through TOOLKITS codes `tooling_not_permitted`, `confirmation_required`, `server_managed`, `tool_scope_unavailable`; storage codes pass through unchanged.
- The doc states the release gate (§3) and that the early subset ships only with Studio disabled for tenants (AC30).
- English only.

### Cross-feature ordering (package X16)
- Cross-feature ordering: none required — this task is in the spec's early subset (X16 "No sibling dependency"); it may merge before any FEAT-621 (storage) or FEAT-622 (toolkits) task.
- Cross-feature ordering: cross-link (by section name only) FEAT-621's host guide `docs/agentstudio/db-storage.md` once FEAT-621 W4 lands; until then write "see the storage host guide (FEAT-621)".

### References in Codebase
- `sdd/specs/agentstudio-tenant-visibility.spec.md` §2 (normative text), §5 (ACs), X14 (codes)
- `docs/agent_studio_api.md` — existing structure to extend

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read the current `docs/agent_studio_api.md` headings and pick the insertion point (after the route overview) — *why*: keep one doc, as AC21 requires.
2. Write the FEAT-605 part section by section from spec §2 (tables copied, not paraphrased) — *why*: UI/host code against exact codes and fields.
3. Add the doc-presence test — *why*: TASK-3974 must not silently drop a row.

### `docs/agent_studio_api.md` (MODIFY)
```markdown
<!-- anchor: FILL IN — choose the section after the existing route overview (section-level; spec §6 Edit Sites row) -->
## Tenant scope & visibility (FEAT-605)

### Host modes
<!-- FILL IN: copy spec §2 "Host modes" table -->

### Route policy (relative to the mount prefix)
<!-- FILL IN: copy spec §2 "Route policy" table, every row -->

### Error codes
| Code | HTTP | Owner |
|---|---|---|
| `name_taken` | 409 | FEAT-605 |
<!-- FILL IN: remaining FEAT-605 codes, then TOOLKITS + storage pass-through codes (X14) -->

### `GET {prefix}/me`
<!-- FILL IN: body {user_id, tenant, may_author, may_administer, enabled, is_superuser}; exempt from studio_disabled -->

### Mounting Studio in a host
<!-- FILL IN: setup_studio_routes(prefix=, view_wrapper=), BotManager.setup(studio_routes=False),
     setup_registry_only(app, *, import_modules=False, load_definitions=False) — **incomplete lifecycle:
     not recommended to tenant hosts until W2.2**; mount order resolver → setup_registry_only → setup_studio_routes -->

### Request context for tools
<!-- FILL IN: RequestContext.kwargs["studio_scope"] = StudioToolScope(caller, agent) built by build_tool_scope -->

### Release gate
<!-- FILL IN: spec §3 "Release gate"; early subset is not tenant-ready (studio_enabled=False for tenants) -->
```
**Why**: AC21 requires one doc covering host modes, route table, mount hooks, `/me`, context keys and every new code.

### `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` (CREATE)
```python
"""FEAT-605 — the API contract doc carries every code, route and mount hook (AC21)."""
from __future__ import annotations

from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[4] / "docs" / "agent_studio_api.md"  # FILL IN: verify depth to repo root

CODES = ["name_taken", "declarative_only", "studio_disabled", "tenant_mismatch", "authoring_denied",
         "reserved_config_key", "tenant_required", "groups_required", "groups_not_allowed",
         "tooling_not_permitted", "confirmation_required", "server_managed", "tool_scope_unavailable"]


@pytest.mark.parametrize("code", CODES)
def test_every_error_code_documented(code):
    assert f"`{code}`" in DOC.read_text(encoding="utf-8")


def test_mount_hooks_and_me_documented(): ...      # FILL IN: setup_studio_routes, view_wrapper, studio_routes, setup_registry_only, /me fields
def test_registry_only_marked_incomplete(): ...    # FILL IN: "incomplete lifecycle" present (TASK-3965 flips this test)
```
**Why**: Pins AC21 so later doc edits cannot drop a code.

### FILL IN checklist
- [ ] doc section anchor — pick the insertion point; bounded by keeping existing sections intact
- [ ] doc tables — verbatim from spec §2/X14; bounded by AC21
- [ ] `test_feat605_contract_doc.py` — repo-root path depth and the two stub tests; bounded by AC21

---

## Acceptance Criteria

- [ ] `docs/agent_studio_api.md` documents host modes, the exhaustive route table, mount hooks + order, `/me`, `studio_scope` context keys and every new error code with its status (AC21, contract-first part)
- [ ] `setup_registry_only` is marked "incomplete lifecycle — not recommended to tenant hosts" (C32)
- [ ] The release gate and "early subset is not tenant-ready" are stated (AC30)
- [ ] `test_feat605_contract_doc.py` passes

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py
def test_every_error_code_documented(code): ...
def test_mount_hooks_and_me_documented(): ...
def test_registry_only_marked_incomplete(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-tenant-visibility --feature-id FEAT-605`)
2. **Read the spec** at the path listed above for full context (§2 is normative; §3 has the task table)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-tenant-visibility.json`, AND every
   "Cross-feature ordering" item in Implementation Notes must hold (sibling feature tasks merged)
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor; a count of `0` means drift — stop and report
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-tenant-visibility.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands, and run each
   listed mutation check (revert the guard, see the named test go RED, restore by re-applying
   the edit — never with `git checkout` of the file)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3958 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
