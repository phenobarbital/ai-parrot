# TASK-5079: FEAT-783 leftovers — client cache/reasoning counters, dead hasattr, codex codec spike

**Feature**: FEAT-783 — unified-usage
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M
**Depends-on**: TASK-5077
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:488dc2435ab8`

## Context
Split from `issue:d95710046fd7` (TASK-5077). The user approved editing `clients/base.py` and running a
real codex stream (spike S1) on 2026-11-01.

## Scope
1. `AbstractClient._emit_after_call` accepts `usage=` and copies `cache_read_tokens`,
   `cache_creation_tokens` and `reasoning_output_tokens` onto `AfterClientCallEvent`; cached tokens are
   priced at the cache tier via `_compute_call_cost`.
2. Every client call site of `_emit_after_call` that has a usage object passes it (26 sites).
3. Remove the dead `hasattr(self, "_price_revision_fields")` guard; fix the test double it masked.
4. `CodexUsageCodec._find_value` skips `item`/`items` payload subtrees; verify against a real
   `codex exec --json` stream (spike S1, fixture `real_exec.jsonl`) plus a structured-tool-output decoy.

### NOT in scope
- `google/live.py` and the `openai_base.py` stream-fallback site, which report no token counts at all.

## Files to Modify
- `packages/ai-parrot/src/parrot/clients/base.py`, `packages/ai-parrot/src/parrot/clients/openai_base.py`
- client call sites in `ai-parrot-client-{amazon,anthropic,gemma4,google,grok,groq,hf,jev,openai,zai}`
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex_usage.py`
- `packages/ai-parrot/tests/unit/observability/test_client_event_tenant_cost.py`
- `packages/ai-parrot/tests/flows/dev_loop/test_codex_usage_codec.py`
- `packages/ai-parrot/tests/fixtures/codex_usage/{real_exec,structured_tool_decoy}.jsonl`

## Acceptance Criteria
- [x] An API-client event emitted with a `CompletionUsage` carries its cache/reasoning counters.
- [x] Without `usage=`, the counters stay `None`.
- [x] The codec reports the real stream's usage (30115 in / 27008 cached / 51 out) and ignores usage,
      auth and cost keys inside an MCP tool result.

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot/src pytest -q packages/ai-parrot/tests/unit/observability/ \
  packages/ai-parrot/tests/flows/dev_loop/test_codex_usage_codec.py \
  packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py packages/ai-parrot/tests/unit/clients/test_client_emits_agent_name.py
```

## Completion Note
Implemented in the TASK-5079 fix commit. Observability + codec + client-event tests pass apart from two
failures this task does not touch: `test_attributes::test_every_shipped_client_name_is_mapped` (jev/meta
unmapped) and `test_bootstrap_hook::test_hook_import_is_deferred`. Neither involves the changed code paths.
