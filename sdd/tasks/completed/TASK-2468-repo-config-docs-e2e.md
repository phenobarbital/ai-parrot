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

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-27
**Notes**:

**Important discrepancy found and resolved**: the task's Codebase
Contract and the spec's §6/§7 both assert `.parrot/wiki.json` is
"currently... backend=arangodb, arango_database=wiki_ai-parrot... verified
2026-08-25, committed" in this repo. Verified this is **not true** in the
worktree: `.parrot/` does not exist at all (no file, tracked or
untracked), and `.gitignore:369` (`.parrot/`) ignores the whole directory
with no existing exception — `git check-ignore .parrot/wiki.json` and a
`git log --all -- .parrot/wiki.json` both confirm it was never committed
on `dev`. Given no base `wiki.json` exists, `load_project_config()`
already defaults to `backend="sqlite"` for this repo — there was no "dev
Arango" base to preserve. Resolution: did NOT fabricate a base
`wiki.json` (not requested by the Files table, and inventing arangodb
settings nobody asked for would be scope creep); proceeded with exactly
what the Files table specifies — created and committed
`.parrot/wiki.local.json` = `{"backend": "sqlite"}` only. Flagging this
for the spec/task author to reconcile: either the base config was meant
to be added by an earlier task and slipped through, or this repo's own
example was aspirational from the start.

**Necessary deviation beyond the Files table**: `.parrot/` is fully
gitignored with no existing exception, so `.parrot/wiki.local.json`
could not be committed at all without a `.gitignore` change (git refuses
a normal `add` for an ignored path, and force-adding into a directory
pattern that still fully excludes it would look like an anomaly to any
future `git status`/tooling). Changed the ignore rule from `.parrot/`
(directory pattern — stops git from ever descending in) to `.parrot/*`
plus a narrow `!.parrot/wiki.local.json` negation, so exactly one file is
tracked and everything else under `.parrot/` (the built plane, other
per-env overlays, etc.) stays ignored. Verified with `git check-ignore`
(exit 1 = not ignored) before/after. This is "Repo overlay config"
infrastructure, not an engine/CLI behavior change, so it stays within
this task's stated scope despite `.gitignore` not being explicitly
listed in the Files table.

**Docs**: added a new "### Environments — per-env overlays, precedence,
and sync (FEAT-461)" subsection to `docs/guides/llm-wiki-guide.md`
(the actual wikitoolkit docs home — 1250-line "Complete Guide", found by
grepping `docs/` for "wikitoolkit"; no dedicated smaller page existed, so
per the contract's fallback instruction this extends the existing guide
rather than inventing a new file). Covers env resolution order, overlay
files + fallback + build-time generation (with the "never clobbers" and
"never freezes a one-off flag" notes), the one backend precedence rule,
the plane-vs-credentials divergence warning (near-verbatim per the task's
Key Constraint), and the full sync workflow including the no-tombstones
limitation and its recovery path. Added `WIKI_ENV` and updated
`WIKI_STORE_BACKEND`'s description to the Environment Variables table.
`docs/runbooks/jira-issues-namespace.md` was greped for any
Arango/primary-plane assumption — found NONE (the `issues` namespace is
`--global`-registered, entirely independent of this repo's own
`.parrot/wiki.json`/env choice); rather than inventing a nonexistent
assumption to "fix", added a short clarifying note confirming and
documenting that independence explicitly, cross-linking the new guide
section.

**E2E tests**: 8 tests in `tests/knowledge/wiki/test_env_e2e.py` (5
scenarios from the spec's §4 table, `test_e2e_backward_compat_no_overlays`
split into 2 for clarity — one showing `build` additively generates the
`dev` overlay per this feature's design, one confirming a bare `status`
call BEFORE any build/overlay generation never writes anything and falls
back to base silently, which is the actual backward-compatibility
guarantee). All drive the real CLI end-to-end via `CliRunner`; the
arangodb backend is mocked exactly like `test_cli_arango.py` (no real
server, runs unconditionally in CI). The sync-roundtrip test uses the
full `remember` → `sync push` → direct-remote-mutation → `sync pull` →
`page` pipeline through the actual CLI commands (not mocked, unlike
TASK-2467's CLI tests) and confirms the merged body contains both the
original content and the teammate's note.

**Final feature sweep**: `pytest tests/knowledge/wiki/ -v` → 1129 passed,
1 pre-existing unrelated failure (`test_claude_code.py::TestInstaller::
test_fresh_install_writes_all_artifacts`, confirmed via `git stash`
against the pre-FEAT-461 baseline — same assertion, same line), 7
skipped (no ArangoDB test server). TASK-2464's guard test
(`test_env_call_sites.py::TestGuard`) re-run explicitly: passes. `ruff
check` on `test_env_e2e.py`: clean.

**Spec §5 acceptance criteria — evidence locations:**
- No-ENV local sqlite, no Arango attempted: `test_env_e2e.py::
  test_e2e_local_default_no_arango`.
- Env resolution `WIKI_ENV`>`ENV`>`"local"`, charset validated:
  `test_env_config.py::TestResolveWikiEnv`.
- Missing overlay → base fallback, `status` shows `base (no overlay)`:
  `test_env_config.py`, `test_cli_env.py::test_status_env_header_base_fallback`.
- `build` generates missing overlay, never clobbers: `test_cli_env.py::
  TestBuildGeneration`, `test_env_e2e.py::TestProdBuildGeneratesOverlay`.
- No secrets in overlays: `test_env_config.py::test_overlay_rejects_secret_keys`.
- One precedence rule everywhere, TODO removed: `cli.py` (grep confirms
  no `cli.py:352` TODO text remains), `test_cli_env.py::TestPrecedence`.
- All 11 call sites migrated: TASK-2464 diff + `test_env_call_sites.py::
  TestGuard` (grep-based, re-verified this task).
- Offline namespace degrades gracefully: `test_env_call_sites.py::
  TestOfflineDegradation`, `test_env_e2e.py::test_e2e_offline_namespace_skip`.
- Invalid overlay → `WikiConfigError` naming file: `test_env_config.py::
  test_invalid_overlay_fails_loud_naming_file`.
- `updated_at` round-trip both backends, legacy sorts oldest:
  `test_updated_at.py`; "sorts oldest" semantic exercised by `sync.py`'s
  `page.get("updated_at") or ""` LWW comparison (empty string sorts
  before any ISO-8601 stamp) — no `NULL` row can occur in practice
  (`NOT NULL` sqlite columns), so this is defensive-path coverage, not a
  reachable production case.
- Sync push/pull selection, LWW, author filter, note merge, no deletes:
  `test_sync.py` (TASK-2466), `test_env_e2e.py::TestSyncRoundtrip`.
- `--dry-run` + bookkeeper audit + counts printed: `test_sync.py::
  TestAudit`/`TestSafety`, `test_cli_sync.py::test_summary_rendering`.
- `.parrot/wiki.local.json` committed: this task, verified `git status`
  shows it staged; base `wiki.json` absence documented above as a
  pre-existing discrepancy, not a regression.
- Backwards compatible: `test_env_e2e.py::TestBackwardCompatNoOverlays`;
  `test_cli.py`/`test_cli_arango.py` full suites still pass (2
  pre-existing tests were updated in TASK-2463 to reflect this feature's
  intentionally-changed default — documented there).
- `project.py` hook-safe: TASK-2462's completion note (module-scope
  import check).
- Docs updated: this task.
- Full suite green: this task's final sweep above.
- No breaking changes to existing public API: `load_project_config`/
  `save_project_config`/`resolve_arango_params` signatures unchanged
  throughout; every new symbol is additive.

**Deviations from spec**: (1) did not create/modify a base
`.parrot/wiki.json` — none exists in this repo, contrary to the spec's
stated assumption (see discrepancy note above); (2) added a narrow
`.gitignore` exception (not in the Files table) — the only way to
actually commit the file the Files table DOES list.
