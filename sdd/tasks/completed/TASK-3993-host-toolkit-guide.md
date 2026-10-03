# TASK-3993: Host-toolkit guide page — conventions, policy registration, GLOBAL-partition statement (M6 docs)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3989, TASK-3991
**Assigned-to**: unassigned
**Wave**: 4 (spec §9) · **Module**: M6 host-conventions (guide)

---

## Context

Spec §3 M6: one host-toolkit guide page stating the conventions that are **not** enforced (Pydantic return models;
row cap `max_rows` in `config_model` plus `truncated: bool` in the result; no secrets in results; no resource
acquisition in a tenant-bound constructor — resources belong in `_open()`), plus the enforced ones (prefix,
`read_tools`, strict write confirmation). Spec §2 "When it applies" makes a **mandatory** host-guide statement: the
GLOBAL partition is intentionally outside tenant policy and is not a tenant-compatible deployment mode; a host
serving tenants must not expose GLOBAL Studio rows to tenant users and should set `apply_to_global=True` if any exist.

---

## Scope

- Create `docs/toolkits/host-toolkits.md`: `plugins/tools/__init__.py` (`HOST_TOOL_PREFIX`, `TOOL_REGISTRY`), resolver
  rules (no shadowing, walk fallback deprecated one minor version — Q3), `tenant_bound`, `require_tool_scope` and
  `host_tenant_mismatch` in `_pre_execute`, `server_managed_params`, `read_tools` and strict confirmation (zero writes
  without a guard; `app["studio_confirmation_guard"]`), `set_tenant_tooling_policy` example, the error codes (X14),
  the unenforced conventions, and the mandatory GLOBAL-partition statement verbatim in substance.

**NOT in scope**: code changes; FieldSync-specific toolkits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/toolkits/host-toolkits.md` | CREATE | host-toolkit guide page |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# none (documentation)
```

### Existing Signatures to Use
```python
# Documented public names (created by TASK-3975/02/03/07/08/11/15): get_toolkit_resolver, require_tool_scope,
# ensure_tool_scope, ToolScopeUnavailable, ServerParam, server_managed_params, read_tools, TenantToolingPolicy,
# set_tenant_tooling_policy, enforce_tenant_tooling, current_confirmed_call
```

### Does NOT Exist
- ~~a `register_host_toolkits(app, …)` API~~ — rejected in Q1; the registry is declarative.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/toolkits/host-toolkits.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Cross-feature ordering
- Wave 4 per spec §9; publishing the guide as "tenant-ready" waits for the package release gate (X16).

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Write the page from the spec sections cited in Scope — *why*: M6 requires one guide page.
2. Include the GLOBAL-partition statement — *why*: mandatory per spec v0.2.2.

### `docs/toolkits/host-toolkits.md` (CREATE)
```markdown
# Host toolkits for Agent Studio
<!-- FILL IN: sections listed in Scope -->
```

### FILL IN checklist
- [ ] Every section of Scope present; GLOBAL statement present.

---

## Acceptance Criteria

- [ ] Page exists and covers every Scope bullet, including the mandatory GLOBAL-partition statement.
- [ ] Code samples use only names that exist after Waves 1–4.
- [ ] Existing docs test still passes: `pytest packages/ai-parrot-server/tests/test_feat593_docs.py -q`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/test_feat593_docs.py -q`

---

## Test Specification

```python
# Docs-only task: no new test. Validation runs the existing docs test.
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback loop, tramo B2)
**Date**: 2026-10-02
**Notes**: `docs/toolkits/host-toolkits.md`: declaring host tools (`HOST_TOOL_PREFIX`, `TOOL_REGISTRY`, the resolver rules as they are
implemented — prefix = `tool_prefix` without the trailing underscore, no shadowing, deprecated walk fallback), `tenant_bound` and the
scope gate (what is enforced before any side effect, refusal reasons, `host_tenant_mismatch` raised in `_pre_execute`),
`server_managed_params`, `read_tools` + strict confirmation (zero writes without a guard / approval, `app["studio_confirmation_guard"]`),
the tenant tooling policy (`set_tenant_tooling_policy` example), opting in to scope resolution, the error codes, the unenforced
conventions (Pydantic returns, `max_rows` + `truncated`, no secrets, no resource acquisition in a tenant-bound constructor — use
`_open()`), and the mandatory GLOBAL-partition statement at the top. Every name used in the samples exists on this branch.
Validation: `test_feat593_docs.py` passes. Docs-only task: no mutation to record.

**Deviations from spec**: none.
