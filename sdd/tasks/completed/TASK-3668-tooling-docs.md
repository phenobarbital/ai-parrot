# TASK-3668: Docs: Agent Studio tooling API, Admin UI Tools tab, YAML toolkits entries

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3660, TASK-3661, TASK-3665
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 14; AC18.

---

## Scope

- `docs/agent_studio_api.md`: schema envelope (hard cut), GET/PUT/DELETE agent toolkits (final GET path),
  options endpoint (persisted-spec only), mcp-servers, `/me`; error codes `read_only_definition`,
  `not_overridable`, `not_configured`, `options_failed`, `vault_unavailable`, `use_studio_endpoint`;
  PBAC actions.
- `docs/admin-ui.md`: Tools tab, drawer, Reload flow, Datasets (kinds incl. parquet → delta), MCP panel,
  chat "My tool settings".
- `docs/agent_config_creation.md`: YAML `toolkits:` entry shape, secrets never in YAML (use Studio),
  top-level `mcp_servers` now consumed; DB agents' `tools` now registered (behaviour change note).
- A tiny pytest asserting key strings appear (keeps the validation contract).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent_studio_api.md` | MODIFY | New endpoints, envelope, error codes, PBAC actions |
| `docs/admin-ui.md` | MODIFY | Tools tab, Datasets/MCP panels, My tool settings |
| `docs/agent_config_creation.md` | MODIFY | YAML toolkits: str | {slug, params, user_overridable}; vault-only secrets |
| `packages/ai-parrot-server/tests/test_feat593_docs.py` | CREATE | Doc presence test (endpoints + codes mentioned) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
# docs only
```

### Existing Signatures to Use
```python
# docs/agent_studio_api.md already documents StudioError {message, code, details} and existing codes
#   (invalid_json, invalid_request, not_found, not_owner, unavailable, server_managed, invalid_params, vault_unavailable)
```

### Does NOT Exist
- ~~a `/agents/{name}/datasets` Studio endpoint~~ — do not document one.

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
      "path": "docs/admin-ui.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/agent_config_creation.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/test_feat593_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Match the existing heading style of each doc; append sections, do not restructure.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read the final route table from `handlers/studio/__init__.py` — *why*: document what exists.
2. Write the three sections + the presence test.

### `packages/ai-parrot-server/tests/test_feat593_docs.py` (CREATE)
```python
"""FEAT-593 docs presence check."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_studio_api_doc_mentions_endpoints():
    text = (ROOT / "docs/agent_studio_api.md").read_text(encoding="utf-8")
    for needle in ("/toolkits/{slug}/options/{param}", "/mcp-servers", "/me", "read_only_definition",
                   "not_overridable", "use_studio_endpoint"):
        assert needle in text, needle


def test_yaml_doc_mentions_toolkit_entries():
    text = (ROOT / "docs/agent_config_creation.md").read_text(encoding="utf-8")
    assert "user_overridable" in text and "vault" in text.lower()
```
FILL IN: the three doc sections (docs/*.md, append-only).

### FILL IN checklist
- [ ] Three doc sections; bounded by AC18 and the final routes

---

## Acceptance Criteria

- [ ] Docs updated (AC18); presence test passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/test_feat593_docs.py -q`

---

## Test Specification

```python
# see blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `qwen` (`qwen.qwen3-coder-480b-a35b-instruct`, MCP backend `nova`), delivered via `coder_run_chunk` job `job-b8862e0da9e6`, attempt `da6b137b6cf740039b89be538034f0ca`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `2146e1dd9` (`feat(tool-configuration-agentstudio): TASK-3668 — Docs: Agent Studio tooling API, Admin UI Tools tab, YAML toolkits entries`)
**Lint autofix SHA**: `0371a06e3` (`style(tool-configuration-agentstudio): TASK-3668 — engine lint autofix`, 0 residual, 0 errors)
**Merge commit**: `3d046faf9`

**Notes**: `coder_wait`/`coder_merge` returned `outcome: "merged"`, attempt `terminal: "completed"`, 1 attempt,
0 retries, 0 failures (116s), 0 lint residual. Diff verified against the task's file table: `docs/agent_studio_api.md`
(MODIFY, +200 — new endpoints/envelope/error codes/PBAC actions), `docs/admin-ui.md` (MODIFY, +35 — Tools tab,
Datasets/MCP panels, My tool settings), `docs/agent_config_creation.md` (MODIFY, +24/-2 — YAML toolkits
`str | {slug, params, user_overridable}`, vault-only secrets), and `tests/test_feat593_docs.py` (CREATE, 23
insertions — doc-presence test) — exactly the 4 declared files, no unlisted files, nothing else under `sdd/`
touched (this closure's own index/task-file moves are separate, tracked commits). This is the final task of
FEAT-593.

**Review**: `coder_record_review` recorded — `feedback_id: coder-review:cd18726f3aa78876ff2d8b65`, `fix_commits: []`.

**Deviations from spec**: none.
