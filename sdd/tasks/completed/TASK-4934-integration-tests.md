# TASK-4934: End-to-end integration tests for the expert pipeline

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4923, TASK-4926, TASK-4927, TASK-4929, TASK-4930, TASK-4931
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. Unit tests prove each module; these prove the chain: bundle → `ExpertRegistry.load()` →
`ExpertAgent.configure()` → rendered system prompt, the fresh-install path with both shipped experts, tenant
overlays, ADR consume/propose, concurrency isolation, and the CVE download → next-resolve loop. Everything runs
offline: `InMemoryWikiStore`, recorded CVE fixtures (TASK-4929), a stubbed LLM client (no `ask()` against a provider —
only prompt rendering is asserted).

This task is where the request-time knowledge gap noted in TASK-4918/TASK-4923 gets an observed answer: assert what the
rendered prompt contains for an expert with a registered KB and record the result in the Completion Note.

---

## Scope

- Write `packages/ai-parrot/tests/experts/test_integration.py` with the seven tests below.

**NOT in scope**: changing production code. If a test exposes a defect, fix it only when it is a one-line slip in
a FEAT-778 file; otherwise mark the test `xfail(strict=True, reason=…)`, open a ledger issue
(`wikitoolkit ledger open … --discovered-from spec:FEAT-778`) and describe it in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/experts/test_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry.registry import AgentRegistry                 # verified: registry.py:302 — use a fresh instance per test
from parrot.knowledge.wiki.file_store import InMemoryWikiStore     # verified: wiki/file_store.py:74
from parrot.observability.context import current_agent_name, current_seat   # verified: context.py:67,158
from parrot.experts.registry import ExpertRegistry                 # TASK-4926
from parrot.experts.activation import activate_expert              # TASK-4924
from parrot_tools.security.cve import CVEToolkit                   # TASK-4929
from parrot_tools.experts import ExpertKnowledgeToolkit            # TASK-4927
```

### Existing Signatures to Use
```python
# AgentRegistry (registry.py): register_instance (633), has (668), get_bots_by_tag (1565), register_db_bot_policies (507)
# PromptBuilder.build(context: Dict[str, Any]) -> str   # builder.py:288
# AbstractBot.prompt_builder property                    # abstract.py:1394
```

### Does NOT Exist
- ~~the global `agent_registry` singleton in these tests~~ — never mutate it; build `AgentRegistry()` per test.
- ~~network access~~ — monkeypatch `CVEToolkit._get_json`; no provider client may be called.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/experts/test_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. A module fixture: fresh `AgentRegistry`, fake wiki toolkit whose `_store_for` returns one `InMemoryWikiStore`,
   an LLM stub so `ExpertAgent.configure()` builds no provider client.
2. The seven tests, one per spec §4 integration row plus the plain-agent guarantee.

### `packages/ai-parrot/tests/experts/test_integration.py` (CREATE)
```python
"""FEAT-778 end-to-end tests — offline: in-memory wiki, recorded CVE fixtures, stubbed LLM."""
from __future__ import annotations

import pytest

# FILL IN: fixtures (registry, wiki store, llm stub, expert_bundle/governance_dir from conftest)


async def test_bundle_to_prompt_roundtrip(expert_bundle, governance_dir): ...
    # FILL IN: prompt contains identity, <governance_rules> (org before expert) and Tier-1 text with revisions


async def test_tenant_overlay_changes_knowledge_not_rules(expert_bundle, governance_dir): ...
    # FILL IN: tenant file text replaces Tier-1 text; org rules unchanged


async def test_adr_consume_then_propose(): ...
    # FILL IN: accepted hit inline; propose_adr result is inferred/unreviewed and not inline on re-resolve


async def test_concurrent_activations_do_not_share_builders(): ...
    # FILL IN: asyncio.gather two activate_expert scopes; distinct builders, names, seats


async def test_fresh_install_loads_both_cve_experts(tmp_path): ...
    # FILL IN: empty store, no AGENTS_DIR/experts → both registered with origin:bundled, namespaces seeded (AC27)


async def test_cve_analyst_download_then_resolve(tmp_path, monkeypatch): ...
    # FILL IN: inside activate_expert(cve-analyst) download_cve("CVE-2026-98432") → next resolve() wiki handle
    # "documents" incremented by one


async def test_expert_with_kb_request_time_knowledge(expert_bundle): ...
    # FILL IN: record (assert) whether request-time KB results reach the rendered prompt — see Context
```

### FILL IN checklist
- [ ] Fixtures and seven test bodies.
- [ ] Completion Note: the request-time knowledge observation.

---

## Acceptance Criteria

- [ ] AC27 — fresh install registers `cve-analyst` and `cve-remediation` and each renders identity, rules and Tier-1 knowledge.
- [ ] AC18 — concurrent activations never share builders or leak attribution.
- [ ] All seven tests pass offline (or are `xfail(strict=True)` with a ledger issue, per Scope).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_integration.py -q`

---

## Test Specification

See the blueprint above — the seven test names are fixed by spec §4 (plus the request-time knowledge check).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4934 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-terra (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier and chunk merge-tier validation green.

**Deviations from spec**: none
