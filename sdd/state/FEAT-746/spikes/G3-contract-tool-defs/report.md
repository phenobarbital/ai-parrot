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

Run 2026-10-30, `PARROT_TEST_REAL_LLM=1`, one tool-forcing `ask()` per provider:

| Provider | Model | Result |
| --- | --- | --- |
| Anthropic | client default | PASS — 1 tool call, known name, dict args |
| Google | client default | PASS — 1 tool call, known name, dict args |
| OpenAI | `gpt-4.1-mini` (`SQUAWK_G3_MODEL_OPENAI`) | PASS — 1 tool call |
| Groq | `openai/gpt-oss-120b` (`SQUAWK_G3_MODEL_GROQ`) | PASS — 1 tool call |

All four providers accept the compiled schemas and call the tool with valid
arguments. The client defaults were not usable, for reasons unrelated to tool
definitions (filed as client defects in the ledger):

- `OpenAIClient` default `gpt-5-mini` → 400: the client sends `max_tokens`, which that
  model rejects (`max_completion_tokens` required).
- `GroqClient` default `llama-3.3-70b-versatile` → 404 (model no longer available).
  The first run's "`'model'` doesn't match any schema" came from the spike passing the
  `GroqModel` enum object; the spike now sends `.value`.

The spike opens each client with `async with client:` and records a provider error as
`failed` instead of aborting the run.

## Amendment

**No wording change to `compile_capability` is proposed.** The schemas pass offline
for all four formats and live on all four providers. M7 should note that
`SquawkRemoteToolkit` inherits whatever model its host client resolves, so the two
client defects above block OpenAI/Groq defaults until fixed.

Raw output of the recorded run: `sdd/state/FEAT-746/spikes/G3-contract-tool-defs/results.json`.
