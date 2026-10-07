# TASK-4127: End-to-end prompt matrix for `JiraSpecialist` across languages

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4121, TASK-4122
**Assigned-to**: unassigned

---

## Context

Implements the spec §4 integration test `test_jira_specialist_prompt_language_matrix`
(design research **S8**). The unit tests of TASK-4120..4122 check layers and a `MockBot`;
existing grounding tests stub `agent.ask` with hand-written replies. Nothing yet builds a
**real `JiraSpecialist`** and inspects the system prompt it actually renders. This task does,
for every language case, through the real `_configure_prompt_builder()` → `_build_prompt()`
path.

The test lives at the tests root (not under `tests/bots/prompts/`), next to
`test_jira_callbacks.py`, which already constructs a real `JiraSpecialist` with three patches.
The root conftest's `parrot.bots.abstract` stub is an **opt-in** fixture (`fake_parrot_bots`,
`tests/conftest.py:505`) and is not used here.

Scope bound (spec Non-Goals): this proves the directive and sentinels are **present** in the
prompt; it never proves the model obeys them.

---

## Scope

- Create `packages/ai-parrot/tests/test_jira_specialist_output_language.py` with a language
  matrix over the real rendered system prompt.

**NOT in scope**: live LLM calls; callback/escalation text (TASK-4124); model compliance.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_jira_specialist_output_language.py` | CREATE | Real-agent prompt matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.jira_specialist import JiraSpecialist    # verified: tests/test_jira_callbacks.py:7
from unittest.mock import AsyncMock, MagicMock, patch
```

### Existing Signatures to Use
```python
# Patches that make JiraSpecialist() constructible — tests/test_jira_callbacks.py:12-25
patch("redis.asyncio.from_url")
patch("parrot.bots.jira_specialist.JiraToolkit")
patch("parrot.bots.jira_specialist.config")            # then mock_config.get.return_value = "dummy"
# Prompt tests patch dynamic values — tests/bots/prompts/test_abstractbot_integration.py:69-72
patch("parrot.bots.abstract.dynamic_values")           # then mock_dv.get_all_names.return_value = []

# packages/ai-parrot/src/parrot/bots/abstract.py
    async def _configure_prompt_builder(self) -> None: ...                 # line 1356
    def _build_prompt(self, user_context="", vector_context="", kb_context="",
                      pageindex_context="", metadata=None, **kwargs) -> Union[str, List]: ...  # line 1419
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                            # line 152
    self.prompt_builder / self._prompt_builder          # the Jira layer stack (jira_workflow + jira_grounding)
    self._init_kwargs: Dict[str, Any]                   # line 240 — copy of constructor kwargs (feeds clone_for_user)
```

### Does NOT Exist
- ~~A live/real LLM call in this test~~ — none; `_build_prompt()` renders locally.
- ~~`agent.system_prompt_template`~~ — removed in FEAT-138; inspect `_build_prompt()` output.
- ~~`fake_parrot_bots` in this test~~ — do not use it; it replaces `parrot.bots.abstract` with a stub.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/test_jira_specialist_output_language.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#JiraSpecialist",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._configure_prompt_builder",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._build_prompt"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every case must also assert that **no `$`-placeholder survives** (`$output_language`,
  `$sentinel_not_found`, `$sentinel_error`) — the strongest single regression signal for the
  configure-time wiring.
- Use exact strings from the catalogs (`GROUNDING_SENTINELS`) rather than retyping them.

---

## Implementation Blueprint

### Steps (in order)
1. Write the fixture that builds a configured agent for a given language — *why*: one helper keeps every case on the same real code path.
2. Write the matrix — *why*: spec §4 integration test, S8.

### `packages/ai-parrot/tests/test_jira_specialist_output_language.py` (CREATE)
```python
"""FEAT-638: the real JiraSpecialist system prompt across languages (TASK-4127)."""
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS

PLACEHOLDERS = ("$output_language", "$sentinel_not_found", "$sentinel_error")


async def _rendered_prompt(language):
    """Build a real JiraSpecialist, run configure-time prompt resolution, return the prompt."""
    with patch("redis.asyncio.from_url"), \
         patch("parrot.bots.jira_specialist.JiraToolkit"), \
         patch("parrot.bots.jira_specialist.config") as mock_config, \
         patch("parrot.bots.abstract.dynamic_values") as mock_dv:
        mock_config.get.return_value = "dummy"
        mock_dv.get_all_names.return_value = []
        agent = JiraSpecialist(language=language) if language is not None else JiraSpecialist()
        await agent._configure_prompt_builder()
        return agent, agent._build_prompt()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "language,directive,sentinel_lang",
    [
        (None, None, "en"),
        ("en", "English", "en"),
        ("es", "Spanish", "es"),
        ("es-MX", "Spanish", "es"),
        ("fr", None, "en"),            # unsupported → treated as unset
    ],
)
async def test_jira_specialist_prompt_language_matrix(language, directive, sentinel_lang):
    agent, prompt = await _rendered_prompt(language)
    assert isinstance(prompt, str)
    for token in PLACEHOLDERS:
        assert token not in prompt, token
    sentinels = GROUNDING_SENTINELS[sentinel_lang]
    assert sentinels["not_found"] in prompt
    assert sentinels["error"] in prompt
    if directive is None:
        assert "<output_language_policy>" not in prompt
    else:
        assert "<output_language_policy>" in prompt
        assert directive in prompt
    # FILL IN: for sentinel_lang == "es", also assert the English sentinels are ABSENT;
    #   assert "jira_workflow" and "jira_grounding" are still in agent.prompt_builder.layer_names
    #   — bounded by spec AC "grounding sentinels render per language".


@pytest.mark.asyncio
async def test_language_survives_into_clone_kwargs():
    agent, _ = await _rendered_prompt("es")
    assert agent._init_kwargs.get("language") == "es"   # clone_for_user rebuilds from _init_kwargs
```

### FILL IN checklist
- [ ] Spanish case: English sentinels absent; Jira layers still installed

---

## Acceptance Criteria

- [ ] For unset / `en` / `es` / `es-MX` / `fr`, the real `JiraSpecialist` prompt carries the expected directive (or none) and the expected sentinel language.
- [ ] No `$`-placeholder survives in any case.
- [ ] `jira_workflow` and `jira_grounding` remain installed in every case.
- [ ] `language` is preserved in `_init_kwargs` for `clone_for_user`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_jira_specialist_output_language.py -q`

---

## Test Specification

See the blueprint block above (complete test file except one FILL IN).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug jiraspecialist-agent-multilang --feature-id FEAT-638`)
2. **Read the spec** at `sdd/specs/jiraspecialist-agent-multilang.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/jiraspecialist-agent-multilang.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor check; a count of `0` means the anchor is gone — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/jiraspecialist-agent-multilang.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (add `packages/ai-parrot-server/src` for server files)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> jiraspecialist-agent-multilang verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
