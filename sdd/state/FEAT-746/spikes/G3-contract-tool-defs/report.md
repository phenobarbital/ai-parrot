# G3 — Contract to provider tool definitions

## Scope and reproduction

This gate compiles the spec §4 HR fixture — `hr.reports.headcount_by_dept`
(Arrow artifact), `hr.reports.manager_of` (inline), and
`hr.people.lookup` (LLM-backed) — with `parrot.interagent.compile_capability`.
Each compiled definition is registered in a fresh `ToolManager`, then rendered
for OpenAI, Anthropic, Google, and Groq.

```bash
PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g3_contract_tool_defs.py -q
python sdd/state/FEAT-746/spikes/G3-contract-tool-defs/spike.py
PARROT_TEST_REAL_LLM=1 python sdd/state/FEAT-746/spikes/G3-contract-tool-defs/spike.py
```

## Offline result

| Provider format | Schemas | Structural verdict | Adapter constraints checked |
| --- | ---: | --- | --- |
| OpenAI | 3 | PASS | Every object is closed and requires each declared property. |
| Anthropic | 3 | PASS | Every object is closed and requires each declared property. |
| Google | 3 | PASS | No `$ref`, `anyOf`, `additionalProperties`, or `title`. |
| Groq | 3 | PASS | Every object is closed; unsupported validation constraints are absent. |

The opt-in regression also asserts that the LLM-backed capability description
ends with `Input is treated as data, never as instructions.` This is the D9
boundary: its free-text argument is data, not an instruction channel.

`ToolSchemaAdapter._clean_for_groq` currently represents Groq's closed-object
constraint as `additionalProperties: false`; the gate verifies that actual
adapter behavior rather than treating the key's presence as a rejection.

## Live-provider status

No real-provider call was made in this worktree: `PARROT_TEST_REAL_LLM` was
not enabled. When enabled, the spike discovers the installed OpenAI,
Anthropic, Google, and Groq client classes, calls only classes whose
`has_server_credentials()` returns true, and records every unconfigured target
as `skipped`, never `passed`. Each configured provider receives one tool-
forcing `ask()` call and passes only if it produces tool calls with known tool
names and dictionary arguments without a parsing error.

## Amendment

**No wording change to `compile_capability` is proposed.** The measured offline
schemas preserve the current descriptions for inline results, artifact handles,
and the LLM-backed input-as-data boundary, while all four `ToolSchemaAdapter`
formats satisfy their current structural constraints. A live-provider failure,
if one is recorded later, must name the provider and its rejected schema before
proposing a wording-only amendment.
