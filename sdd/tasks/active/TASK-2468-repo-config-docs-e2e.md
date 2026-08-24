# TASK-2468: Repo overlay config, documentation, and end-to-end tests

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2463, TASK-2464, TASK-2467
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 — the closing task: ship this repo's committed local
overlay (the actual no-VPN payoff), document the env model and sync
workflow, and prove the whole feature end-to-end.

---

## Scope

- Create and COMMIT `.parrot/wiki.local.json` in this repo with exactly:
  ```json
  {
    "backend": "sqlite"
  }
  ```
  Verify `.parrot/` files are not gitignored (`.parrot/wiki.json` is already
  tracked — confirm with `git check-ignore`); leave the base `wiki.json`
  (dev Arango) untouched.
- Documentation:
  - Extend the wiki docs (wherever the wikitoolkit usage docs live — check
    `docs/` and the CLAUDE.md wiki section pointers) with: the env model
    (`WIKI_ENV` → `ENV` → `local`), overlay files + fallback + build-time
    generation, the **plane-vs-credentials divergence** (unset `ENV` selects
    the *local plane* while navconfig still loads `env/.env` credentials for
    shared namespaces — must be stated prominently, spec §7), the precedence
    rule, and the sync workflow (push/pull, author filter, note merge,
    no-tombstones limitation).
  - Update `docs/runbooks/jira-issues-namespace.md` where it assumes the
    primary plane is the dev Arango.
- End-to-end integration tests (spec §4 Integration table) in
  `tests/knowledge/wiki/test_env_e2e.py`:
  - `test_e2e_local_default_no_arango` — no `ENV`, local overlay → sqlite
    plane opens, query path works fully offline.
  - `test_e2e_offline_namespace_skip` — local mode + unreachable Arango
    namespace → skip note, local results returned, bounded time.
  - `test_e2e_env_prod_build_generates_and_uses_overlay`.
  - `test_e2e_sync_roundtrip_two_planes` — remember → push → mutate remote →
    pull; LWW + author filter + note union observed.
  - `test_e2e_backward_compat_no_overlays` — base-only repo + explicit
    `WIKI_ENV=dev` behaves as before the feature.
- Final feature sweep: run the full wiki test suite
  (`pytest tests/knowledge/wiki/ -v`) and the TASK-2464 guard test; confirm
  every spec §5 acceptance criterion has a passing check or a documented
  location.

**NOT in scope**: any engine/CLI behavior changes (file bugs back to the
owning task instead of patching here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.parrot/wiki.local.json` | CREATE | committed local overlay: `{"backend": "sqlite"}` |
| `docs/` wiki/wikitoolkit docs (locate exact file) | MODIFY | env model + sync workflow |
| `docs/runbooks/jira-issues-namespace.md` | MODIFY | primary-plane assumptions |
| `tests/knowledge/wiki/test_env_e2e.py` | CREATE | five e2e scenarios |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Everything consumed here was created by TASK-2462..2467 — verify each
# landed (files exist, imports resolve) before starting:
from parrot.knowledge.wiki.project import load_effective_config, resolve_wiki_env
from parrot.knowledge.wiki.sync import sync_push, sync_pull, SyncReport
```

### Existing Signatures to Use
```python
# .parrot/wiki.json (THIS repo, committed): backend="arangodb",
#   arango_database="wiki_ai-parrot", arango_credentials_env="ARANGODB",
#   namespaces={}  — verified 2026-08-25. Do NOT modify it.
# docs/runbooks/jira-issues-namespace.md — exists (referenced from CLAUDE.md).
# CLI entry: `wikitoolkit` (see cli.py); CliRunner tests in
#   tests/knowledge/wiki/test_cli.py show invocation conventions.
```

### Does NOT Exist
- ~~`.parrot/wiki.local.json`~~ — created (and committed) by THIS task.
- ~~`tests/knowledge/wiki/test_env_e2e.py`~~ — created by THIS task.
- ~~a dedicated wikitoolkit docs page~~ — LOCATE the real docs home first
  (grep `docs/` for "wikitoolkit"); do not invent a path — if none exists,
  create `docs/wikitoolkit-environments.md` and link it from the runbook.

---

## Implementation Notes

### Key Constraints
- The committed overlay is the feature's user-visible payoff — the commit
  message must make clear every teammate now defaults to local sqlite.
- E2E tests must not require a live ArangoDB: the "remote"/unreachable cases
  use a second local plane and a non-routable address with the bounded
  federation timeout.
- Documentation must include the divergence warning verbatim-ish: "unset
  `ENV` selects the local *plane*; navconfig still resolves *credentials*
  from `env/.env` for anything that reaches Arango (shared namespaces,
  sync)".

### References in Codebase
- `tests/knowledge/wiki/test_namespaces_e2e.py` — e2e test style (FEAT-450).
- Spec §4 Integration Tests table — the five scenarios to implement.
- Spec §5 — the checklist this task closes out.

---

## Acceptance Criteria

- [ ] `.parrot/wiki.local.json` committed; `wikitoolkit status` on a clean
  checkout with no `ENV` reports env=local, backend=sqlite.
- [ ] All five e2e tests pass without a live ArangoDB.
- [ ] Docs updated (env model incl. divergence warning; sync workflow incl.
  no-tombstones limitation); runbook updated.
- [ ] Full suite green: `pytest tests/knowledge/wiki/ -v`
- [ ] Spec §5 checklist review: every criterion checked or its evidence
  location noted in the Completion Note.

---

## Test Specification

```python
# tests/knowledge/wiki/test_env_e2e.py

async def test_e2e_local_default_no_arango(tmp_path, monkeypatch): ...
async def test_e2e_offline_namespace_skip(tmp_path, monkeypatch): ...
def test_e2e_env_prod_build_generates_and_uses_overlay(tmp_path, monkeypatch): ...
async def test_e2e_sync_roundtrip_two_planes(tmp_path): ...
def test_e2e_backward_compat_no_overlays(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§3 Module 6, §4, §5).
2. **Check dependencies** — TASK-2463, TASK-2464, TASK-2467 must be in
   `sdd/tasks/completed/` (TASK-2466 transitively via 2467).
3. **Verify the Codebase Contract** before writing ANY code.
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
