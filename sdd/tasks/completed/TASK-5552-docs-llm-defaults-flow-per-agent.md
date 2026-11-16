# TASK-5552: Documentation — `wiki/operations/configuration/llm-defaults.md` (FLOW + per-agent env)

**Feature**: FEAT-882 — Per-Agent Env LLM Credentials + AgentsFlow Default Key
**Spec**: `sdd/specs/per-agent-env-llm-credentials.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5548, TASK-5549, TASK-5550
**Assigned-to**: unassigned

---

## Context

Spec §10 (`docs.policy: required`, page `wiki/operations/configuration/llm-defaults.md`) and §3 Module 4.
The page documents FEAT-796's per-component defaults. It must now also document the FLOW component, the
per-agent variables, the full precedence table and D3's limitation. The page is guarded by
`packages/ai-parrot/tests/test_llm_defaults_documented.py`, whose parametrized list gets the new names.

---

## Scope

- Update the page in place (keep its frontmatter and the FEAT-796 sections):
  - `## Variables`: add a `FLOW_LLM` row (Component: AgentsFlow, builtin `google:gemini-4-argon`, applied only when set).
  - `## API keys`: add `FLOW_<PROVIDER>_API_KEY` (no legacy alias) and the rule that component defaults are
    injected only into agents without an explicit credential.
  - New `## Per-agent variables` section: `<AGENT>_MODEL`, `<AGENT>_<PROVIDER>_API_KEY`, the name -> token rule
    (`odoo-helpdesk` -> `ODOO_HELPDESK`), reserved names (`AGENT`, `CREW`, `FLOW`, `DEFAULT`, `EXPERT_*` tiers)
    and the token-collision caveat.
  - New `## Precedence` section: the 7-row table from spec §2, including "component-default keys are not explicit".
  - New `## AgentsFlow and already-configured agents` section: D3 — FLOW defaults reach only unconfigured
    agents (programmatic flows); registry agents are configured before the flow sees them, so use
    `<AGENT>_<PROVIDER>_API_KEY`; one INFO log per skipped agent.
  - `## Usage attribution`: add the `FLOW` tag value.
  - Retitle the H1/frontmatter title to cover FEAT-882 too (e.g. "Per-component and per-agent LLM defaults").
- Extend the parametrized list in `test_llm_defaults_documented.py`.

**NOT in scope**: any code change; other wiki pages.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/operations/configuration/llm-defaults.md` | MODIFY | FLOW + per-agent + precedence sections |
| `packages/ai-parrot/tests/test_llm_defaults_documented.py` | MODIFY | add the new variable names |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none in production code. The docs test uses only:
import pathlib   # verified: tests/test_llm_defaults_documented.py:3
import pytest    # verified: tests/test_llm_defaults_documented.py:5
```

### Existing Signatures to Use
```text
wiki/operations/configuration/llm-defaults.md
  frontmatter title: "Per component LLM defaults (FEAT 796)"   (:2)
  # Per-component LLM defaults (FEAT-796)                       (:5)
  ## Variables                                                  (:7)
  ## API keys                                                   (:21)
  ## Usage attribution                                          (:32)

packages/ai-parrot/tests/test_llm_defaults_documented.py
  @pytest.mark.parametrize(
      "name", ["DEFAULT_LLM", "CREW_LLM", "AGENT_LLM", "EXPERT_JUDGMENT_LLM", "CREW_GOOGLE_API_KEY", "CREW_AI_KEY"]   (:11)
  )
  def test_llm_defaults_documented(name: str) -> None           (:13)

sdd/templates/techwiki-page.md  — page conventions for wiki pages
Facts to document (verify against the merged code of TASK-5548/5549/5550 before writing):
  parrot.llm_defaults: COMPONENTS, agent_env_token, resolve_agent_llm, resolve_agent_api_key,
                       is_component_default_key, apply_component_api_key
  AbstractBot._apply_agent_env_overrides (configure-time), flow.py _apply_flow_defaults / _flow_usage_scope
```

### Does NOT Exist
- ~~`FLOW_AI_KEY`~~ — FLOW has no legacy alias; only `CREW_AI_KEY` exists.
- ~~`<AGENT>_LLM`~~ — the per-agent model variable is `<AGENT>_MODEL`; `_LLM` is the component suffix.
- ~~`docs/configuration/llm-defaults.md`~~ — the page lives under `wiki/operations/configuration/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/operations/configuration/llm-defaults.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_llm_defaults_documented.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/test_llm_defaults_documented.py#test_llm_defaults_documented"
  ]
}
```

---

## Implementation Notes

- Write for operators: what to set, what wins, what the limitation is. No implementation internals beyond
  the function names an integrator may call.
- Every variable name in the test list must appear verbatim in the page.
- Do not change the `FEAT-796` facts that are still true (builtins, `gemini-4-argon` caching note).

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged code of TASK-5548/5549/5550 and confirm names and behaviour — *why*: the page documents what shipped, not the plan.
2. Edit the page section by section as listed in Scope — *why*: keeps FEAT-796 content intact.
3. Extend the test list and run both validation commands.

### `packages/ai-parrot/tests/test_llm_defaults_documented.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"name", \["DEFAULT_LLM", "CREW_LLM", "AGENT_LLM", "EXPERT_JUDGMENT_LLM", "CREW_GOOGLE_API_KEY", "CREW_AI_KEY"\]' test_llm_defaults_documented.py)
# REPLACE the parametrize list at test_llm_defaults_documented.py:11 with:
    "name",
    [
        "DEFAULT_LLM",
        "CREW_LLM",
        "AGENT_LLM",
        "EXPERT_JUDGMENT_LLM",
        "CREW_GOOGLE_API_KEY",
        "CREW_AI_KEY",
        "FLOW_LLM",
        "FLOW_GOOGLE_API_KEY",
        "<AGENT>_MODEL",
        "<AGENT>_<PROVIDER>_API_KEY",
    ],
```

### `wiki/operations/configuration/llm-defaults.md` (MODIFY)
```markdown
<!-- occurrences: 1 each (verified: grep -c '^## API keys$' / '^## Usage attribution$' llm-defaults.md) -->
<!-- AFTER the `## API keys` section body, BEFORE `## Usage attribution` (verified: llm-defaults.md:21,32) insert: -->
## Per-agent variables
<!-- FILL IN: <AGENT>_MODEL / <AGENT>_<PROVIDER>_API_KEY, token rule, reserved names, collision caveat -->

## Precedence
<!-- FILL IN: the 7-row table from spec §2 + "component-default keys are not explicit" -->

## AgentsFlow and already-configured agents
<!-- FILL IN: D3 limitation and the per-agent workaround -->
```
**Why**: the new sections sit between the key rules and usage attribution so the page reads model -> key ->
precedence -> caveat -> attribution.

### FILL IN checklist
- [ ] `## Variables` FLOW row; `## API keys` FLOW rule; `## Usage attribution` FLOW tag; H1/title.
- [ ] Three new sections — content from spec §2/§7/§8 (D3).

---

## Acceptance Criteria

- [ ] Every name in the extended test list appears in the page; the test passes.
- [ ] Precedence table matches spec §2 exactly (7 rows).
- [ ] D3 limitation documented with the per-agent workaround.
- [ ] `parrot sdd techwiki check --spec sdd/specs/per-agent-env-llm-credentials.spec.md --root .` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_llm_defaults_documented.py -q`

> Also run (not a test-runner command, so not listed above): `parrot sdd techwiki check --spec sdd/specs/per-agent-env-llm-credentials.spec.md --root .`

---

## Test Specification

The existing parametrized test covers it once the list is extended (see blueprint).

---

## Agent Instructions

1. Work in the feature worktree; TASK-5548, TASK-5549, TASK-5550 must be `done`.
2. Set the task `in-progress`; implement; run the Validation Commands.
3. Commit only the listed files; `parrot sdd task close TASK-5552 per-agent-env-llm-credentials verified`; fill the Completion Note.

---

## Completion Note


- Task: TASK-5552
- Feature: per-agent-env-llm-credentials
- Implementation SHA: acc147616667144a605503672cffbb0423b1f990
- Closed at (UTC): 2026-11-12T19:38:59+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 184s · Tokens: n/a |
