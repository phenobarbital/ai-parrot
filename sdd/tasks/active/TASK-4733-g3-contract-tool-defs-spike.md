# TASK-4733: G3 — contract → tool definitions across four providers spike

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4742, TASK-4737
**Assigned-to**: unassigned

---

## Context

Spec §3 gate **G3 — S3 contract to tool defs**. A `SquawkCapability` must compile (via core `compile_capability`, TASK-4742) into a `ToolDefinition` that OpenAI, Anthropic, Google and Groq accept after `ToolManager.get_tool_schemas(ToolFormat.*)` cleaning. G3 validates the four schemas offline and, under `PARROT_TEST_REAL_LLM=1`, makes one real call per provider; its amendment may change only the compiler's description wording (spec §3 dependency graph).

---

## Scope

- `spike.py`: build the HR contract fixture (3 capabilities: `hr.reports.headcount_by_dept` artifact/arrow, `hr.reports.manager_of` inline, `hr.people.lookup` llm_backed), compile each, register in a fresh `ToolManager`, dump `get_tool_schemas()` for `OPENAI`, `ANTHROPIC`, `GOOGLE`, `GROQ`, and validate each against the provider's schema constraints that `ToolSchemaAdapter` encodes (no `$ref`/`anyOf` for Google, no `additionalProperties` for Groq, etc.).
- Under `PARROT_TEST_REAL_LLM=1`: one `ask()` per configured provider through the existing clients forcing a tool call; record whether the model called the tool with valid args.
- `report.md` with the per-provider table and the amendment (wording changes to `compile_capability`, if any).
- `packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py`: offline part only, opt-in `PARROT_SPIKE=1`.

**NOT in scope**: editing `compile_capability` (an amendment proposes; TASK-4742 is already done — a follow-up task applies), `SquawkRemoteToolkit` (M7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-746/spikes/G3-contract-tool-defs/spike.py` | CREATE | Compile + per-provider schema validation (+ optional real calls) |
| `sdd/state/FEAT-746/spikes/G3-contract-tool-defs/report.md` | CREATE | Gate report + amendment |
| `packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py` | CREATE | Opt-in offline regression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager, ToolDefinition, ToolFormat, ToolSchemaAdapter   # verified: packages/ai-parrot/src/parrot/tools/manager.py:289, :31, :75, :87
from parrot.interagent import SquawkCapability, ReturnsSpec, PolicyAnnotations, MediaType, compile_capability   # TASK-4740 / TASK-4742 (parrot/interagent/contract.py, compiler.py)
from parrot.clients.base import AbstractClient   # verified: packages/ai-parrot/src/parrot/clients/base.py (real-LLM path only; never a provider SDK directly)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolFormat(Enum): OPENAI, ANTHROPIC, GOOGLE, GROQ, VERTEX, GENERIC, BEDROCK            # lines 75-84
class ToolSchemaAdapter:  # line 87 — clean_schema_for_provider(schema, provider_format) line 93; _clean_for_google :126; _clean_for_groq :151; _clean_for_openai :194
class ToolManager:
    def register_tool(self, tool=None, name=None, description=None, input_schema=None, function=None) -> None   # line 853 (accepts a ToolDefinition)
    def get_tool_schemas(self, provider_format: ToolFormat = ToolFormat.GENERIC) -> List[Dict[str, Any]]      # line 1313 — injects schema["_tool_instance"] (:1335): strip it before validating
```

### Does NOT Exist
- ~~`ToolManager.mount_category`~~ — M7 (gated on G4); register with `register_tool(tool=<ToolDefinition>)` here.
- ~~`parrot.squawk.contract.compiler`~~ — the compiler is core `parrot.interagent.compiler` since spec rev 0.2.
- ~~`ToolFormat.OPENAI` producing a schema free of `_tool_instance`~~ — it is injected; pop it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-746/spikes/G3-contract-tool-defs/spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G3-contract-tool-defs/report.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolFormat",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolSchemaAdapter",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolDefinition"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Exclusive task (real-LLM quota) when `PARROT_TEST_REAL_LLM=1`; the offline validation needs no network.
- Provider "acceptance" offline = the cleaned schema satisfies the rules `ToolSchemaAdapter._clean_for_*` enforce AND passes a `jsonschema`-style structural check (`type: object`, `properties`, `required ⊆ properties`); real acceptance is the opt-in call.
- The LLM-backed capability's input schema may contain free text — the spike confirms the description never instructs the model to treat it as a prompt (D9).

### References in Codebase
- `packages/ai-parrot/tests/tools/test_bedrock_tool_format.py` — existing per-provider schema test idiom.

---

## Implementation Blueprint

### Steps (in order)
1. Write the fixture contract in `spike.py` as a function `hr_capabilities()` — *why*: the same three capabilities are the spec's `hr_contract` fixture (§4) and reused by later tasks' tests.
2. Compile, register, dump per format, validate — *why*: that is the pass criterion.
3. Optional real calls behind `PARROT_TEST_REAL_LLM=1` — *why*: the only true acceptance evidence; must not run in CI.
4. Report + amendment — *why*: wording changes feed TASK-4742's follow-up.

### `sdd/state/FEAT-746/spikes/G3-contract-tool-defs/spike.py` (CREATE)
```python
"""G3 — one Squawk contract, four provider tool formats (FEAT-746)."""
from __future__ import annotations

import json
import os
import sys

from parrot.interagent import MediaType, PolicyAnnotations, ReturnsSpec, SquawkCapability, compile_capability
from parrot.tools.manager import ToolFormat, ToolManager

FORMATS = (ToolFormat.OPENAI, ToolFormat.ANTHROPIC, ToolFormat.GOOGLE, ToolFormat.GROQ)


def hr_capabilities() -> list[SquawkCapability]:
    """The spec §4 `hr_contract` fixture: artifact, inline and llm_backed capabilities."""
    return [
        SquawkCapability(cap_id="hr.reports.headcount_by_dept", category="hr.reports", description="Headcount grouped by department.",
                         input_schema={"type": "object", "properties": {"as_of": {"type": "string", "format": "date"}}, "required": []},
                         returns=ReturnsSpec(kind="artifact", media_type=MediaType.ARROW), backing="deterministic",
                         policy=PolicyAnnotations(data_class="hr", aggregation_min=5)),
        SquawkCapability(cap_id="hr.reports.manager_of", category="hr.reports", description="Manager of an employee id.",
                         input_schema={"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
                         returns=ReturnsSpec(kind="inline", schema={"type": "object", "properties": {"manager_id": {"type": "string"}}}), backing="deterministic",
                         policy=PolicyAnnotations(data_class="hr")),
        SquawkCapability(cap_id="hr.people.lookup", category="hr.people", description="Free-text lookup of a person (LLM-backed, structured output).",
                         input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                         returns=ReturnsSpec(kind="inline", schema={"type": "object", "properties": {"matches": {"type": "array"}}}), backing="llm_backed",
                         policy=PolicyAnnotations(data_class="pii", token_budget=2000)),
    ]


async def _noop(**kwargs):
    return {"ok": True, "args": kwargs}


def schemas_per_format() -> dict[str, list[dict]]:
    tm = ToolManager()
    for cap in hr_capabilities():
        tm.register_tool(tool=compile_capability(cap, function=_noop))
    out: dict[str, list[dict]] = {}
    for fmt in FORMATS:
        schemas = tm.get_tool_schemas(fmt)
        for s in schemas:
            s.pop("_tool_instance", None)
        out[fmt.value] = schemas
    return out


def validate(fmt: str, schema: dict) -> list[str]:
    """Return a list of violations (empty = accepted offline)."""
    problems: list[str] = []
    # FILL IN: per-format structural rules mirroring ToolSchemaAdapter._clean_for_google/_clean_for_groq/_clean_for_openai (manager.py:126-227) — bounded by: a rule may only reject, never rewrite
    return problems


def main() -> int:
    report = {fmt: [{"name": s.get("name") or s.get("function", {}).get("name"), "problems": validate(fmt, s)} for s in schemas] for fmt, schemas in schemas_per_format().items()}
    print(json.dumps(report, indent=2))
    if os.environ.get("PARROT_TEST_REAL_LLM") == "1":
        pass  # FILL IN: one tool-forcing ask() per configured provider via the existing AbstractClient subclasses — bounded by one request per provider
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: the compiler is core and already fixed (TASK-4742); G3 only measures acceptance. `_tool_instance` is popped because the adapter injects it (manager.py:1335) and it is not part of the wire schema (S4).

### `packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py` (CREATE)
```python
"""G3 regression — four formats accept the HR contract offline (opt-in)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G3-contract-tool-defs/spike.py"


def _load():
    spec = importlib.util.spec_from_file_location("g3_spike", SPIKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_formats_accept_offline():
    g3 = _load()
    for fmt, schemas in g3.schemas_per_format().items():
        assert len(schemas) == 3, fmt
        for s in schemas:
            assert g3.validate(fmt, s) == [], (fmt, s)
```

### FILL IN checklist
- [ ] `spike.py::validate` — per-format rules; bounded by the adapter's own cleaning rules (reject-only)
- [ ] `spike.py::main` real-LLM branch — one request per provider; bounded by `PARROT_TEST_REAL_LLM=1`
- [ ] `report.md` — per-provider table, verdict, wording amendment for `compile_capability` (or "none")

---

## Acceptance Criteria

- [ ] Three capabilities compile and register; four formats produce three schemas each with zero offline violations
- [ ] Under `PARROT_TEST_REAL_LLM=1`, each configured provider calls the tool with valid args (recorded per provider; unconfigured providers are reported as skipped, never as passed)
- [ ] `report.md` carries the amendment (or explicitly "no wording change")
- [ ] `PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py -q`

---

## Test Specification

See the blueprint test (offline only).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 G3, §3 M1 compiler skeleton, §7 pattern "Remote tools become local AbstractTools"
3. **Check dependencies** — TASK-4742 `"done"`
4. **Verify the Codebase Contract** (re-grep `manager.py` line anchors)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement** from the blueprint
7. **Verify** — Validation Commands with `PARROT_SPIKE=1`; real-LLM part only if the operator set the env
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4733 inter-agent-protocol verified`
10. **Completion Note** — quote the amendment verbatim

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
