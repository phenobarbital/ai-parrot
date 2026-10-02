# TASK-3974: [W4.3] Docs finalise, changelog, lockstep version bump

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3973
**Assigned-to**: unassigned
**Spec task label**: W4.3 (spec §3 "Task plan")

---

## Context

Spec §3 W4.3, Module 12, AC21, AC30; §8 Q7 (deferred: version number chosen by the maintainer).
Finish the W0.3 contract doc against the merged code, list the plain-host behaviour changes in
CHANGELOG (`name_taken` replacing `duplicate`/`name_collision`/`not_owner`, D1/D3 refusals, additive
visibility fields), and bump `ai-parrot` and `ai-parrot-server` in lockstep.

Unblocks: **U-FS** (version pin).

---

## Scope

- Reconcile `docs/agent_studio_api.md` with the code (every route, code, field, mount hook); keep the release-gate statement (AC30).
- `CHANGELOG.md` `[Unreleased]`: FEAT-605 entry incl. plain-host behaviour changes.
- Lockstep version bump in `packages/ai-parrot/src/parrot/version.py` and `packages/ai-parrot-server/src/parrot/server/version.py` (both `1.0.7` today) — number decided by the ai-parrot maintainer (§8 Q7).
- Extend `test_feat605_contract_doc.py` with the behaviour-change and route assertions.

**NOT in scope**: Declaring any release tenant-ready (AC30 — only when the §3 release gate across FEAT-605/621/622 is met).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent_studio_api.md` | MODIFY | Finalise the FEAT-605 contract against the code |
| `CHANGELOG.md` | MODIFY | FEAT-605 entry + plain-host behaviour changes |
| `packages/ai-parrot/src/parrot/version.py` | MODIFY | Lockstep version bump (core) |
| `packages/ai-parrot-server/src/parrot/server/version.py` | MODIFY | Lockstep version bump (server) |
| `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` | MODIFY | Assert behaviour-change list and final route rows |

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
# none (docs, changelog, version constants, a doc test)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/version.py:8                 __version__ = "1.0.7"
# packages/ai-parrot-server/src/parrot/server/version.py:3   __version__ = "1.0.7"
# packages/ai-parrot-server/pyproject.toml:100 version = {attr = "parrot.server.version.__version__"}
# packages/ai-parrot/pyproject.toml:949       version = {attr = "parrot.version.__version__"}
# CHANGELOG.md — "## [Unreleased]" section at the top
```

### Does NOT Exist
- ~~a tenant-ready label for any partial release~~ — forbidden by AC30

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
      "path": "CHANGELOG.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/version.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/version.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Existing `CHANGELOG.md` `[Unreleased]` entries.

### Key Constraints
- Both packages bump together (lockstep).
- Do not edit `pyproject.toml` or lockfiles (versions are attribute-driven).

### Cross-feature ordering (package X16)
- Cross-feature ordering: the doc cross-links FEAT-621's host guide (`docs/agentstudio/db-storage.md`, FEAT-621 W4) and FEAT-622's host-toolkit guide page — link them if merged, otherwise name them.
- Cross-feature ordering: the release gate (X16) — this task never enables or documents a tenant-ready release unless FEAT-621 W0–W4 and FEAT-622 Waves 1–4 are merged.

### References in Codebase
- `CHANGELOG.md`, `docs/agent_studio_api.md`

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Diff the doc against the code; fix every mismatch.
2. Write the CHANGELOG entry; bump both versions to the maintainer-chosen number.
3. Extend the doc test.

### `CHANGELOG.md` (MODIFY)
```markdown
<!-- under "## [Unreleased]" -->
### Agent Studio — tenant scope, visibility & host mount (FEAT-605)
<!-- FILL IN: features (scope seam, /me, visibility PATCH, host mount hooks, registry-only mount, assistant partition)
     and "Behaviour changes for hosts without a scope resolver": name_taken replaces duplicate/name_collision/not_owner;
     D1/D3 refusals; additive visibility fields on GETs and lists; reload and files GET stay ungated. -->
```
**Why**: AC21 CHANGELOG part.

### `packages/ai-parrot/src/parrot/version.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__version__ = "1.0.7"' version.py) — :8
__version__ = "FILL IN: maintainer-chosen version (§8 Q7)"
```
**Why**: Lockstep with the server package.

### `packages/ai-parrot-server/src/parrot/server/version.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__version__ = "1.0.7"' version.py) — :3
__version__ = "FILL IN: same version as ai-parrot core"
```
**Why**: Lockstep.

### `docs/agent_studio_api.md` (MODIFY)
```markdown
<!-- FILL IN: reconcile every table of the FEAT-605 part with the merged code (routes, codes, fields, mount hooks). -->
```
**Why**: AC21 final.

### `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` (MODIFY)
```python
def test_plain_host_behaviour_changes_documented(): ...   # FILL IN: name_taken replaces duplicate/name_collision/not_owner
def test_visibility_patch_routes_documented(): ...        # FILL IN
```
**Why**: Pins the final doc.

### FILL IN checklist
- [ ] doc reconciliation, CHANGELOG text, version number (ask the maintainer if not decided), two doc tests

---

## Acceptance Criteria

- [ ] AC21: doc covers host modes, route table, mount hooks, `/me`, context keys and every new error code; CHANGELOG lists plain-host behaviour changes
- [ ] AC30: no tenant-ready wording unless the release gate is complete
- [ ] Both version files carry the same new version

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
# packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py — adds 2 tests
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3974 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

`docs/agent_studio_api.md` reconciled with the code (status block, tenant-None answers, `not_manageable`, `groups_not_allowed` without the "open question",
plain-host behaviour now final, `version` in toolkit/MCP write responses, cross-links to the FEAT-621/622 guides, release-gate statement kept — AC30).
CHANGELOG: FEAT-605 under `## [Unreleased]` (Added / Changed incl. every plain-host change). Contract-doc test extended (specs identical, X14 codes, schema 8, CHANGELOG).
Owner decisions (C1-C4): C1 `not_manageable` 403 on every Studio route (TASK-3972 commit); C2 `ToolkitPersistResponse.version` (additive, Studio agents only, a legacy agent's body is
unchanged; the value comes from the service's own return of the committed version) — own commit; C3 `groups_not_allowed` + `not_manageable` added to X14 in the three byte-identical
"Cross-spec contract (package)" sections (verified identical by a test), X1 now says required versions 1..8 for the `database` backend, storage spec wording/skeleton/manifest
example fixed (`STUDIO_SCHEMA_REQUIRED = 8`, no `_PHASE2` constant — the code has none), doc 'open question' removed.
**C4 — VERSION BUMP NOT DONE (owner decision):** `parrot/version.py` and `parrot/server/version.py` are UNTOUCHED; the changes sit under `Unreleased`. Jesus chooses the number at release.
FLAG: the spec host-mode row says "resolver + tenant None: addressed routes 404"; the code answers 422 `tenant_required` on every addressed route (identical for existing/absent names);
the doc states the code's behaviour; the matrix test asserts it.

**Completed by**: sdd-worker (tramo C)
**Date**: 2026-10-02

**Deviations from spec**: version files not bumped (C4); touched toolkit_config.py / models.py / tooling_store.py / three specs (owner requirements C2, C3).
