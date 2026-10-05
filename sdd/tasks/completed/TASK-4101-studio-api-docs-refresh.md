# TASK-4101: Refresh docs/agent_studio_api.md (B12)

**Feature**: FEAT-634 — Agent Studio — UI Backend Gaps
**Spec**: `sdd/specs/agentstudio-ui-backend-gaps.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-4096, TASK-4097, TASK-4098, TASK-4099, TASK-4100
**Assigned-to**: unassigned

---

## Context

Implements spec Module 5 / G8 (B12) / AC16. Documentation only, after all code tasks fix the names.

---

## Scope

- Endpoints Overview (`:49-105`): add `PATCH /agents/{name}`, the three `…/visibility` PATCH routes, `GET /me`, `GET /sharing/groups`; correct the `/catalog` row.
- `GET/POST/DELETE /agents*` (`:152-213`): database-mode shapes, Studio item keys incl. `llm`/`description`/`category`/`definition`; DELETE is no longer '409 delegated'.
- Draft pipeline (`:215-261`): bundle drafts, not `source` only. BYOK (`:353-387`): replace 'DocumentDB' with the real store; fix the 'BYOK is out of scope' line in the route-policy `/keys` row (`:900` area). Testing (`:389-410`): `byok`. Skills import (`:339`): `version`. Files list: `entries`.
- Reference Catalogs (`:677-701`): `models`, `deprecated_models`, `allowed`, host rows, tenant filtering of `tools`. Visibility (`:932`): `expected_version` NOT supported, last-write-wins. Error codes (`:903-923`): `tooling_not_permitted` details.
- New subsection 'Host toolkit allow-list' (`tenant_toolkits`: sync, no I/O, `None` = unrestricted, fail closed, never phase `build`) with the refusal-shape table; short 'Known limits' list naming B3 and B10. No release/version numbers anywhere.
- Extend `tests/studio/test_feat605_contract_doc.py` so the doc-parity test pins the new fields/shape; run it after the edit (it may pin existing fragments).

**NOT in scope**: any code change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent_studio_api.md` | MODIFY | fix stale sections + document new surface |
| `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` | MODIFY | pin new doc fragments |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `e840b4b44` (2026-10-05). Use these VERBATIM; verify anything else with grep first.

### Verified Imports
```python
# none — documentation task
```

### Existing Signatures to Use
```python
# docs/agent_studio_api.md: `## Endpoints Overview` at :49 (occurrences: 1); stale line numbers in the scope above were verified at spec time — re-grep each heading before editing
# tests/studio/test_feat605_contract_doc.py: existing doc-parity test (read it first)
```

### Does NOT Exist
- ~~`StudioAgentPatch.tools` / `POST /agents/{name}/tools` on a tenant (B3, out of scope)~~
- ~~`config` or `schema_version` in any readable response (deliberately not exposed)~~
- ~~`expected_version` support on the visibility PATCH routes (last-write-wins, B7)~~
- ~~`TenantToolingPolicy.tenant_toolkits`~~ before TASK-4098 lands (added by this feature)

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
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Additive only: no existing field, route or error code is renamed or removed. Async-first, Pydantic v2, `self.logger`, Google docstrings, type hints, 120 cols.
- Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.
- Viewers of a tenant-shared agent do NOT read `system_prompt` (Resolved 2026-10-05, Juan).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature or path the blueprint fixes. Re-run each `grep -c` before editing; a count other than the one stated means the anchor moved — stop and report.

### Steps (in order)
1. Re-locate each section by heading (line numbers drift) — because the spec's numbers date from 2026-10-05.
2. Edit sections in the order listed in Scope — because later sections reference earlier field names.
3. Run the doc-parity test after editing — because it may pin removed fragments.

### `docs/agent_studio_api.md` (MODIFY)
```markdown
<!-- anchor: `## Endpoints Overview` (occurrences: 1, verified: grep -c '^## Endpoints Overview' docs/agent_studio_api.md; line :49) -->
FILL IN: per-section edits listed in Scope — bounded by AC16 (no 'DocumentDB', no '409 delegated', no 'BYOK is out of scope', every new field documented, B3/B10 as known limits, refusal-shape table)
```
**Why**: pure prose edits; the content is fully specified by spec §2/§3 Module 5.

### `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` (MODIFY)
```python
# FILL IN: add assertions that the doc text mentions `definition`, `deprecated_models`, `tenant_toolkits`, `toolkit_unavailable`, `entries`, `byok`, 'last-write-wins' and no longer contains the AC16 stale statements — bounded by AC16
```
**Why**: follows the existing doc-parity pattern in that file.

### FILL IN checklist
- [ ] `agent_studio_api.md` — every Scope bullet; AC16
- [ ] `test_feat605_contract_doc.py` — new parity assertions

---

## Acceptance Criteria

- [ ] AC16 holds
- [ ] Doc-parity test passes
- [ ] Validation Commands pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py
def test_doc_mentions_new_fields(): ...
```
Text-parity test, no app needed.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agentstudio-ui-backend-gaps --feature-id FEAT-634`), never on `dev`.
2. Read the spec `sdd/specs/agentstudio-ui-backend-gaps.spec.md`; check every `Depends-on` task is `done` in `sdd/tasks/index/agentstudio-ui-backend-gaps.json`.
3. Verify the Codebase Contract before writing code; update it first if stale.
4. Mark `in-progress` in the index (set `started_at`), commit only that file.
5. Implement from the Blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
6. Commit only the files this task lists; close with `scripts/sdd/close_task.sh TASK-4101 agentstudio-ui-backend-gaps verified`; fill the Completion Note; commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*


## Completion Note

Two MCP attempts failed (qwen: request timeout; glm: max_turns) — attempt 3 done by the orchestrator. Doc refreshed; doc-parity test passes. `/sharing/groups` is documented as host-provided (no such route in parrot Studio).
