# TASK-2331: Document the `FlowResult` fidelity contract and `output` shape rule

**Feature**: FEAT-447 — AgentsFlow Result Fidelity
**Spec**: `sdd/specs/agentsflow-result-fidelity.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2328, TASK-2329
**Assigned-to**: unassigned

---

## Context

Satisfies spec **AC17**, the only acceptance criterion not covered by tasks
2326-2330.

FEAT-447 turns `FlowResult` from "a dataclass whose population depends on
which executor you happened to use" into a documented contract. That contract
needs to be written down where users look — `docs/architecture/07-agentcrew.md`,
which already covers `AgentCrew`/`AgentsFlow` results.

Two things to document:

1. **The fidelity contract** — which `FlowResult` fields are populated, by
   which executor, and the one deliberate asymmetry (`summary`, empty for
   AgentsFlow because it does not inherit `SynthesisMixin`).
2. **The `output` shape rule** — scalar when the run has a single executed
   leaf, `dict[node_id, Any]` on a fan-out. FEAT-447 deliberately KEPT this
   polymorphism rather than changing it or adding a parallel `outputs` field
   (spec §8 Q2, Non-Goals), so the documentation is the deliverable that makes
   the decision legible.

Runs last because it documents behaviour that tasks 2328/2329 establish.
Touches only `docs/`, so it is the one task in FEAT-447 that CAN run in a
parallel worktree.

---

## Scope

- Update `docs/architecture/07-agentcrew.md` with:
  - A `FlowResult` field table: field, meaning, populated by `AgentCrew`,
    populated by `AgentsFlow`, notes.
  - The `summary` exemption, with the reason (no `SynthesisMixin`) and the
    pointer to the standalone `synthesize_results` util.
  - The `output` scalar-vs-dict rule, with a short worked example of each case.
  - The `metadata` keys AgentsFlow writes (`mode`, `node_count`,
    `completed_count`, `failed_count`, `skipped`, `leaves`) and the
    `execution_log` entry shape.
  - A note that `node_results` always returns scalars for both executors, and
    that `responses` may hold either `AgentResponse` objects (crew) or
    `AgentNode.execute()` envelope dicts (flow).
- Verify every code reference in the new documentation against the
  post-implementation source before committing.

**NOT in scope**:
- Any production-code or test change.
- Rewriting unrelated sections of `07-agentcrew.md`.
- Documenting the FEAT-447 internals (`_unwrap_response`, `_aggregate_result`
  parameters) — those are private. Document the *contract*, not the mechanism.
- Adding new documentation files. Extend the existing architecture doc.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/architecture/07-agentcrew.md` | MODIFY | Add the `FlowResult` fidelity contract and `output` shape sections |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ee44c175d` on 2026-08-22, i.e. BEFORE tasks
> 2326-2329 land. Because this task documents the POST-implementation
> behaviour, you MUST re-read the sources and confirm the final shapes rather
> than transcribing the table below verbatim.

### Sources of truth to read before writing

```
packages/ai-parrot/src/parrot/bots/flows/core/result.py     — FlowResult @353, NodeExecutionInfo @270
packages/ai-parrot/src/parrot/bots/flows/flow/flow.py       — _aggregate_result @955
packages/ai-parrot/src/parrot/bots/flows/crew/crew.py       — crew FlowResult assembly @2079-2087
packages/ai-parrot/src/parrot/bots/flows/core/node.py       — the envelope @321-325
sdd/specs/agentsflow-result-fidelity.spec.md                — §2 Data Models, §8 resolved questions
```

### Field table to verify and document

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class FlowResult:                              # line 353
    output: Any                                # line 368  — polymorphic, DOCUMENT THE RULE
    responses: Dict[str, Any] = {}             # line 371  — AgentResponse (crew) | envelope (flow)
    summary: str = ""                          # line 374  — crew only; flow leaves "" BY DESIGN
    nodes: List[NodeExecutionInfo] = []        # line 377  — both
    execution_log: List[Dict[str, Any]] = []   # line 380  — both (flow: after TASK-2328)
    total_time: float = 0.0                    # line 383  — both (flow: after TASK-2328)
    status: FlowStatus = FlowStatus.COMPLETED   # line 386  — both
    errors: Dict[str, str] = {}                # line 389  — both
    metadata: Dict[str, Any] = {}              # line 392  — both (different `mode` vocabularies)
```

### Documented shapes (from spec §2 Data Models — CONFIRM against final code)

```python
# AgentsFlow metadata keys
{"mode": str, "node_count": int, "completed_count": int,
 "failed_count": int, "skipped": list[str], "leaves": list[str]}

# execution_log entry
{"node_id": str, "node_name": str, "status": str,
 "execution_time": float, "error": str | None}
```

### Does NOT Exist

- ~~`FlowResult.outputs`~~ (plural) — FEAT-447 explicitly did NOT add one
  (spec §8 Q2). Do not document a field that does not exist.
- ~~A `summary` for AgentsFlow~~ — it stays `""`. Document the reason
  (`flow/flow.py:11-12,217`: no `SynthesisMixin`), not a workaround.
- ~~`NodeExecutionInfo.status == "skipped"`~~ — not a valid literal
  (`core/result.py:298`). Skipped nodes appear ONLY in `metadata["skipped"]`.
- ~~A shared executor base class~~ — `AgentCrew` and `AgentsFlow` share only
  `FlowResult` and `build_node_metadata`. Do not imply an inheritance
  relationship in the docs.
- ~~`docs/architecture/07-flowresult.md`~~ — does not exist and is not being
  created. Extend `07-agentcrew.md`.

---

## Implementation Notes

### Key Constraints

- **Documentation must match the shipped code, not the spec.** Tasks
  2328/2329 may have settled the open `metadata["mode"]` vocabulary question
  differently from the spec's default. Read the code; document what it does.
- Match the existing voice and structure of `docs/architecture/07-agentcrew.md`
  — read it fully before adding sections.
- Keep the `output` rule unambiguous about the *single executed leaf* case:
  the scalar branch requires exactly one leaf AND that leaf being present in
  the results (`flow/flow.py:1028`), and explicit mode is skip-aware, falling
  back to the terminal nodes of the path actually taken.
- Prefer a short worked example over prose for the `output` rule.

### References in Codebase

- `sdd/specs/agentsflow-result-fidelity.spec.md` §2 (Data Models), §8
  (resolved questions) — the decisions this documentation makes public.

---

## Acceptance Criteria

- [ ] `docs/architecture/07-agentcrew.md` documents the `FlowResult` fidelity contract as a field table (spec AC17)
- [ ] The `summary` exemption is documented with its reason and the `synthesize_results` alternative
- [ ] The `output` scalar-vs-dict rule is documented with a worked example of each case (spec AC9, docs half)
- [ ] The AgentsFlow `metadata` keys and `execution_log` entry shape are documented and match the shipped code
- [ ] `node_results` (always scalar) vs `responses` (executor-dependent) is explained
- [ ] Every code reference in the new prose was verified against source post-implementation
- [ ] No production code or test file was modified by this task

---

## Test Specification

No automated tests — this is a documentation task. Verification is manual:

```bash
# Confirm every symbol named in the new docs actually exists
grep -n "class FlowResult" packages/ai-parrot/src/parrot/bots/flows/core/result.py
grep -n "def _aggregate_result" packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
grep -n "metadata=" packages/ai-parrot/src/parrot/bots/flows/flow/flow.py

# Confirm nothing outside docs/ changed
git diff --name-only    # expected: docs/architecture/07-agentcrew.md only
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-result-fidelity.spec.md` (§2 Data Models, §5 AC17, §8)
2. **Check dependencies** — TASK-2328 and TASK-2329 MUST be in `sdd/tasks/completed/`
3. **Read the shipped code** — document what it does, not what the spec proposed
4. **Update status** in `sdd/tasks/index/agentsflow-result-fidelity.json` → `"in-progress"`
5. **Implement** per scope — documentation only
6. **Verify** every acceptance criterion, including that `git diff --name-only` shows only the docs file
7. **Move this file** to `sdd/tasks/completed/TASK-2331-docs-flowresult-contract.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**`metadata["mode"]` vocabulary as shipped**: (what TASK-2328 actually chose)

**Deviations from spec**: none | describe if any
