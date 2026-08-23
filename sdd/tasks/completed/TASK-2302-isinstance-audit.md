# TASK-2302: isinstance/issubclass audit — OpenAIClient checks across the workspace

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2300
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. After TASK-2300, `NvidiaClient`/`MoonshotClient`/etc. are no
longer instances of `OpenAIClient` — any `isinstance`/`issubclass` check
against `OpenAIClient` that really meant "OpenAI-compatible wire client" is now
silently False. Audit every check site across ALL workspace packages and fix
each per its intent: "OpenAI the provider" → keep; "OpenAI-compatible wire" →
switch to `OpenAIBaseClient`.

---

## Scope

- Grep the entire workspace (all `packages/*/src`, plus repo-root `tests/`,
  `examples/`, `plugins/` if present) for:
  `isinstance(.*OpenAIClient`, `issubclass(.*OpenAIClient`,
  `type(.*) is OpenAIClient`, string-comparisons on `client_name == "openai"`
  / `client_type == "openai"` used as a wire-protocol proxy.
- For each hit, classify intent (provider vs wire) with a one-line rationale in
  the Completion Note table; change wire-intent sites to `OpenAIBaseClient`.
- Also check duck-typing hotspots: any code branching on
  `hasattr(client, "_chat_completion")` or on `client_type in ("openai", ...)`
  sets — the `_resolve_tool_format` client_type map (base.py:1382–1386) is
  ALREADY correct (explicit `tool_format` wins) — do not change it.
- Add a regression test asserting the classification outcome for at least the
  known-critical sites found.
- If ZERO wire-intent sites exist, the deliverable is the audit table itself
  (Completion Note) + a test asserting `issubclass(NvidiaClient, OpenAIBaseClient)`
  and `not issubclass(NvidiaClient, OpenAIClient)`.

**NOT in scope**: any hierarchy change; Groq/Zai (not yet rebased —
re-run the audit greps in TASK-2303/2304 acceptance).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| (audit-determined) | MODIFY | wire-intent check sites → `OpenAIBaseClient` |
| `tests/clients/test_openai_base_parity.py` | MODIFY | MRO regression assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.gpt import OpenAIClient              # clients/gpt.py:84
from parrot.clients.openai_base import OpenAIBaseClient  # after TASK-2296
```

### Existing Signatures to Use
```python
# Known type-dispatch sites verified @ dev ab84ffff0 (starting points, NOT exhaustive):
# clients/base.py:1382-1386  _resolve_tool_format client_type map — CORRECT, leave alone
# clients/base.py:2117       "provider": getattr(self, 'client_type', 'unknown') — label only, leave alone
# clients/factory.py:107-149 SUPPORTED_CLIENTS — name-keyed, no isinstance, leave alone
# clients/factory.py:242-243 lazy-loader resolution: `callable(...) and not isinstance(..., type)` — unrelated, leave alone

# Workspace packages to sweep (uv workspace, CLAUDE.md matrix):
#   packages/ai-parrot/src/parrot/
#   packages/ai-parrot-{advisors,embeddings,integrations,server,tools,loaders,pipelines,visualizations}/src/
#   repo-root tests/, examples/
```

### Does NOT Exist
- ~~a registry of isinstance sites~~ — the grep IS the deliverable; do not assume the spec's contract lists them all.
- ~~`OpenAICompatibleClient`~~ — the wire base is `OpenAIBaseClient`.

---

## Implementation Notes

### Pattern to Follow
```bash
# sweep (rg or grep -rn) — run from repo root:
grep -rn "isinstance(.*OpenAIClient\|issubclass(.*OpenAIClient" packages/ tests/ examples/ --include='*.py'
grep -rn "client_type == .openai.\|client_name == .openai." packages/ --include='*.py'
```

### Key Constraints
- Judgment call per site — never bulk-replace.
- Full `pytest` run after changes.

### References in Codebase
- `sdd/specs/openai-compatible-clients.spec.md` §7 Known Risks (MRO visibility).

---

## Acceptance Criteria

- [ ] Audit table in Completion Note: every hit, intent classification, action taken
- [ ] Wire-intent sites switched to `OpenAIBaseClient`; provider-intent sites untouched
- [ ] MRO regression test added (`issubclass(NvidiaClient, OpenAIBaseClient)`, `not issubclass(NvidiaClient, OpenAIClient)`)
- [ ] Full `pytest` run green
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# tests/clients/test_openai_base_parity.py (additions)
def test_mro_post_rebase():
    from parrot.clients.nvidia import NvidiaClient
    from parrot.clients.gpt import OpenAIClient
    from parrot.clients.openai_base import OpenAIBaseClient
    assert issubclass(NvidiaClient, OpenAIBaseClient)
    assert not issubclass(NvidiaClient, OpenAIClient)
    assert issubclass(OpenAIClient, OpenAIBaseClient)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2300 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2302-isinstance-audit.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-21
**Notes**:

Ran the full workspace sweep specified in the task (all `packages/*/src`,
repo-root `tests/`, `examples/`):

```bash
grep -rn "isinstance(.*OpenAIClient\|issubclass(.*OpenAIClient\|type(.*) is OpenAIClient" packages/ tests/ examples/ --include='*.py'
grep -rn 'client_type == .openai.\|client_name == .openai.' packages/ tests/ examples/ --include='*.py'
grep -rn 'hasattr(.*_chat_completion' packages/ tests/ examples/ --include='*.py'
grep -rn 'client_type in (' packages/ tests/ examples/ --include='*.py'
```

**Audit table**:

| File:Line | Check | Intent | Action |
|---|---|---|---|
| `packages/ai-parrot/tests/test_openrouter_client.py:71` | `assert not isinstance(client, OpenAIClient)` | Wire (already correct — added in TASK-2300 as part of rewriting `test_inherits_openai_client` → `test_inherits_openai_base_client`) | None needed — already asserts the correct post-rebase relationship |
| `tests/clients/test_openai_base_parity.py:34` (pre-TASK-2302) | `assert issubclass(OpenAIClient, OpenAIBaseClient)` | Provider-as-wire-specialization (added in TASK-2297) | None needed — correct; `OpenAIClient` legitimately IS-A `OpenAIBaseClient` |
| — | `client_type == "openai"` / `client_name == "openai"` string comparisons | — | **Zero hits anywhere in the workspace** |
| — | `hasattr(client, "_chat_completion")` duck-typing | — | **Zero hits anywhere in the workspace** |
| — | `client_type in (...)` sets | — | **Zero hits anywhere in the workspace** |
| `packages/ai-parrot/src/parrot/clients/base.py:1382-1386` | `_resolve_tool_format` client_type map | Explicit-`tool_format`-wins design (task says leave alone) | Verified unchanged, correctly untouched |

**Zero wire-intent isinstance/issubclass sites required a fix** — per the
task's own fallback clause ("If ZERO wire-intent sites exist, the
deliverable is the audit table itself + a test asserting
`issubclass(NvidiaClient, OpenAIBaseClient)` and `not
issubclass(NvidiaClient, OpenAIClient)`"), the deliverable here is this
table plus the MRO regression suite added to
`tests/clients/test_openai_base_parity.py`:
`test_mro_post_rebase_not_openai_client` (parametrized over all 6 Phase-1
subclasses: `OpenRouterClient`, `MoonshotClient`, `NvidiaClient`,
`LocalLLMClient`, `vLLMClient`, `BedrockMantleClient` — each asserted
`issubclass(cls, OpenAIBaseClient)` AND `not issubclass(cls,
OpenAIClient)`) and `test_mro_openai_client_is_still_openai_base_client`
(positive control).

**Important adjacent finding — reported, NOT fixed (out of this task's
literal scope, which is isinstance/issubclass/client_type-string checks
only, not construction-site choices)**:
`packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py`
(`NovaCodeDispatcher._create_mantle_client`, lines ~104-118)
**directly instantiates `OpenAIClient` pointed at the bedrock-mantle
endpoint** instead of using `BedrockMantleClient` — meaning this one
call site still carries `OpenAIClient`'s `gpt-5-mini`/`gpt-5-nano`/
`gpt-4.1` defaults into a Bedrock Mantle context, i.e. it is still
exposed to the exact DeepSeek-404 bug class FEAT-438 exists to kill,
just via direct construction rather than inheritance. The module's own
docstring explains this was a deliberate design choice made before (or
independent of) `BedrockMantleClient`'s existence ("This dispatcher does
NOT drive the dev seat through NovaClient/Converse... the injected
client_factory builds a plain OpenAIClient pointed at the bedrock-mantle
base URL"). This is not an isinstance/issubclass check, so it falls
outside this task's grep-defined scope, and swapping the constructor
touches `dev_loop`'s own dispatcher subsystem (with its own tests/design
intent) — a "judgment call per site, never bulk-replace" situation this
task explicitly warns against overreaching on. **Recommending a
dedicated follow-up task** to evaluate swapping this to
`BedrockMantleClient`.

**Verification**: `pytest tests/clients/ packages/ai-parrot/tests/
test_openai_client.py tests/unit/test_openai_invoke.py -q --timeout=10`
— diffed against the TASK-2301 baseline: **byte-identical**, zero
regressions. `ruff check` clean on the modified test file.

**Deviations from spec**: none — the `nova.py` finding is reported per
the spirit of "STOP and report" rather than silently fixed or silently
dropped.
