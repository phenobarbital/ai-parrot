# TASK-4121: Install the layer in the builders and wire it through `AbstractBot`

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4118, TASK-4119, TASK-4120
**Assigned-to**: unassigned

---

## Context

Implements the **installation + wiring** half of spec §3 **Module 3** and the injection
half of **Module 5**. This is the task that makes `language` actually change a prompt.

Installation and wiring are one task on purpose: adding `OUTPUT_LANGUAGE_LAYER` to
`PromptBuilder.default()` without teaching `AbstractBot` to remove it when unset would make
every agent render a literal `$output_language`. Shipped together, the rendered prompt of an
agent with no language set stays **byte-identical** to today's.

This task also starts injecting `$sentinel_not_found` / `$sentinel_error` into the configure
context. Nothing consumes them yet — TASK-4122 parameterizes `JIRA_GROUNDING_LAYER` after
this lands, so no intermediate commit renders an unresolved sentinel.

---

## Scope

- Add `OUTPUT_LANGUAGE_LAYER` to `PromptBuilder.default()` and `PromptBuilder.voice()`
  (`agent()` and `rag()` inherit it through `default()`; `minimal()` is deliberately untouched).
- In `AbstractBot._configure_prompt_builder()`: resolve the language once, inject
  `output_language`, `sentinel_not_found`, `sentinel_error`; **remove** the layer when unset.
- Update `test_builder.py`'s hard-coded default layer count (8 → 9).
- Write wiring tests, including the S4 regression test.

**NOT in scope**: changing `JIRA_GROUNDING_LAYER`'s template (TASK-4122); the JiraSpecialist
end-to-end matrix (TASK-4127); `minimal()` (excluded by decision); exporting new names.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | MODIFY | Install layer in `default()` and `voice()` |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Resolve, inject, remove-when-unset in `_configure_prompt_builder()` |
| `packages/ai-parrot/tests/bots/prompts/test_builder.py` | MODIFY | Default layer count 8 → 9 |
| `packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py` | CREATE | Wiring + S4 regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Created by dependencies of this task:
from parrot.bots.prompts.language import FALLBACK_LANGUAGE, normalize_language, resolve_language_name  # TASK-4118
from parrot.bots.prompts.domain_layers import OUTPUT_LANGUAGE_LAYER, GROUNDING_SENTINELS              # TASK-4120
# Existing:
from parrot.bots.prompts.builder import PromptBuilder          # verified: builder.py:34
from parrot.bots.prompts.presets import get_preset              # verified: test_abstractbot_integration.py:41
# Inside abstract.py and builder.py use RELATIVE local imports (see blueprint), matching
# the existing lazy-import precedent: builder.agent() does `from .domain_layers import ...` (builder.py:114).
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                   # line 34
    @classmethod
    def default(cls) -> PromptBuilder: ...             # line 66 — 8 layers today
    @classmethod
    def voice(cls) -> PromptBuilder: ...               # line 86 — list ends with `voice_behavior,` at line 108
    @classmethod
    def agent(cls) -> PromptBuilder: ...               # line 112 — default() + AGENT_BEHAVIOR_LAYER
    @classmethod
    def rag(cls) -> PromptBuilder: ...                 # line 120 — default(), removes "tools"
    @classmethod
    def minimal(cls) -> PromptBuilder: ...             # line 80 — DO NOT CHANGE
    def remove(self, name: str) -> PromptBuilder: ...  # line 177 — no-op if absent
    def get(self, name: str) -> Optional[PromptLayer]: ...  # line 210
    @property layer_names -> List[str]                 # line 328

# packages/ai-parrot/src/parrot/bots/prompts/presets.py:28-35
_PRESETS = {"default": PromptBuilder.default, "minimal": PromptBuilder.minimal, "voice": PromptBuilder.voice,
            "agent": PromptBuilder.agent, "rag": PromptBuilder.rag, "identity": _identity_preset}
# "identity" = default() + CAPABILITIES_LAYER → also gets the layer.

# packages/ai-parrot/src/parrot/bots/abstract.py
    async def _configure_prompt_builder(self) -> None:          # line 1356
        configure_context = {                                   # line 1384
            "rationale": _resolve(getattr(self, "rationale", "")),   # line 1400
            **dynamic_context,
        }
        if self._prompt_caching: ...                            # line 1405
        self._prompt_builder.configure(configure_context)       # line 1417
    def _build_prompt(self, user_context="", vector_context="", kb_context="",
                      pageindex_context="", metadata=None, **kwargs) -> Union[str, List]:  # line 1419
        # spreads **kwargs into request_context, then self._prompt_builder.build(request_context)

# Test pattern — tests/bots/prompts/test_abstractbot_integration.py:13-41, 68-77:
#   _RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot   (loaded by the package conftest.py)
#   MockBot binds the unbound _configure_prompt_builder / _build_prompt and sets name/role/goal/
#   capabilities/backstory/rationale/pre_instructions/enable_tools/tool_manager/logger/_prompt_builder.
#   Tests patch 'parrot.bots.abstract.dynamic_values' with get_all_names.return_value = [].
```

### Does NOT Exist
- ~~`self.language` on `MockBot`~~ — the existing `MockBot` has no `language`; the wiring **must** use `getattr(self, "language", None)` or `test_abstractbot_integration.py` breaks.
- ~~A `condition=` on `OUTPUT_LANGUAGE_LAYER`~~ — forbidden (S4); unset is handled by `remove()`.
- ~~`PromptBuilder.jira()`~~ — no such factory.
- ~~A `language` parameter on `ask()` / `ask_stream()`~~ — none; the value is static (CONFIGURE).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/prompts/builder.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/prompts/test_builder.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder.default",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder.voice",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder.remove",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._configure_prompt_builder",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._build_prompt"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Remove, never condition-gate (S4).** `partial_render()` returns a false-condition layer
  unchanged (`layers.py:116-117`) and `_build_prompt()` spreads `**kwargs` into the request
  context, so a request-time `language=` would reactivate a gated layer with configure-only
  placeholders unresolved. `remove()` is irrevocable.
- **Always inject the sentinel variables**, English when unset. They are unused by every
  layer until TASK-4122, and harmless to layers that never reference them.
- Use `getattr(self, "language", None)` — see Does NOT Exist.
- **Known risk — shared builders:** `configure()` already mutates the builder in place, and so
  does this `remove()`. A single `PromptBuilder` instance passed to two bots with different
  languages would be affected by whichever configures first. This matches existing
  `configure()` behavior; do not add cloning here — record it in the Completion Note if you hit it.

---

## Implementation Blueprint

### Steps (in order)
1. Install the layer in `default()` and `voice()` — *why*: spec decision "all builders except minimal"; `agent()`/`rag()`/`identity` inherit via `default()`.
2. Add the resolve block above `configure_context = {` — *why*: compute once, reuse for the layer and the sentinels.
3. Add three keys to `configure_context` — *why*: CONFIGURE-phase variables are only resolved from this dict.
4. Add the removal right before `configure()` — *why*: removal must precede `partial_render` so nothing of the layer survives.
5. Update `test_builder.py:55`, write the wiring tests.

### `packages/ai-parrot/src/parrot/bots/prompts/builder.py` (MODIFY — `default()`)
```python
# occurrences: 1 (verified: grep -cF '        """Standard layer stack for most bots."""' builder.py)
# REPLACE the body of default() (verified: builder.py:66-77) with:
    @classmethod
    def default(cls) -> PromptBuilder:
        """Standard layer stack for most bots."""
        from .layers import (
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            OUTPUT_LAYER, BEHAVIOR_LAYER,
        )
        from .domain_layers import OUTPUT_LANGUAGE_LAYER  # FEAT-638; removed by AbstractBot when unset
        return cls([
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            OUTPUT_LANGUAGE_LAYER, OUTPUT_LAYER, BEHAVIOR_LAYER,
        ])
```

### `packages/ai-parrot/src/parrot/bots/prompts/builder.py` (MODIFY — `voice()`)
```python
# occurrences: 1 (verified: grep -cF '            voice_behavior,' builder.py)
# BEFORE — insert above `            voice_behavior,` (verified: builder.py:108); also add
#   `from .domain_layers import OUTPUT_LANGUAGE_LAYER` next to voice()'s existing `from .layers import (...)`.
            OUTPUT_LANGUAGE_LAYER,
```
**Why**: `voice()` builds its own list rather than calling `default()`, so it needs its own entry.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — resolve block)
```python
# occurrences: 1 (verified: grep -cF '        configure_context = {' abstract.py)
# BEFORE — insert above `        configure_context = {` (verified: abstract.py:1384)
        # FEAT-638: resolve the bot-level output language once (CONFIGURE phase).
        from .prompts.language import FALLBACK_LANGUAGE, normalize_language, resolve_language_name
        from .prompts.domain_layers import GROUNDING_SENTINELS

        _language_code = normalize_language(getattr(self, "language", None))
        _sentinels = GROUNDING_SENTINELS.get(_language_code or FALLBACK_LANGUAGE, GROUNDING_SENTINELS[FALLBACK_LANGUAGE])
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — context keys)
```python
# occurrences: 1 (verified: grep -cF '            "rationale": _resolve(getattr(self, "rationale", "")),' abstract.py)
# AFTER — insert below that line (verified: abstract.py:1400)
            # FEAT-638: output-language directive + localized FEAT-138 grounding sentinels.
            "output_language": resolve_language_name(_language_code) or "",
            "sentinel_not_found": _sentinels["not_found"],
            "sentinel_error": _sentinels["error"],
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — removal)
```python
# occurrences: 1 (verified: grep -cF '        self._prompt_builder.configure(configure_context)' abstract.py)
# BEFORE — insert above that line (verified: abstract.py:1417)
        if _language_code is None:
            # Unset → remove the layer; never condition-gate it (S4): a false-condition
            # CONFIGURE layer survives partial_render() and _build_prompt() forwards
            # **kwargs into build(), so a request-time `language=` could reactivate it.
            self._prompt_builder.remove("output_language")
```

### `packages/ai-parrot/tests/bots/prompts/test_builder.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        assert len(builder.layer_names) == 8' test_builder.py)
# REPLACE line 55 with:
        assert len(builder.layer_names) == 9  # FEAT-638 adds output_language
```

### `packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py` (CREATE)
```python
"""Wiring tests for the output-language directive (FEAT-638 TASK-4121)."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.presets import get_preset

_RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot  # loaded by conftest.py


class MockBot:
    """Mirrors tests/bots/prompts/test_abstractbot_integration.py::MockBot, plus `language`."""

    _configure_prompt_builder = _RealAbstractBot._configure_prompt_builder
    _build_prompt = _RealAbstractBot._build_prompt

    def __init__(self, prompt_preset="default", language=None):
        self.name = "TestBot"
        self.role = "helpful assistant"
        self.goal = "help users"
        self.capabilities = "- Can search"
        self.backstory = "Expert in AI"
        self.rationale = "Be concise"
        self.pre_instructions = []
        self.enable_tools = True
        self.tool_manager = MagicMock()
        self.tool_manager.tool_count.return_value = 3
        self.logger = MagicMock()
        self._prompt_caching = False
        self.language = language
        self._prompt_builder = get_preset(prompt_preset)


@pytest.mark.parametrize("factory", ["default", "agent", "rag", "voice", "identity"])
def test_layer_in_builder(factory):
    assert "output_language" in get_preset(factory).layer_names


def test_layer_absent_from_minimal():
    assert "output_language" not in PromptBuilder.minimal().layer_names
    assert "output_language" not in get_preset("minimal").layer_names


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_prompt_byte_identical_when_unset(mock_dv):
    mock_dv.get_all_names.return_value = []
    # FILL IN: configure MockBot(language=None); configure a second MockBot whose builder is
    #   get_preset("default").remove("output_language") (= the pre-feature stack); assert both
    #   _build_prompt() outputs are EQUAL, and that "output_language_policy" and "$" do not appear
    #   — bounded by spec AC "byte-identical when unset".


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_prompt_contains_directive_when_set(mock_dv):
    mock_dv.get_all_names.return_value = []
    # FILL IN: MockBot(language="es-MX"); configure; build; assert "Spanish" and
    #   "<output_language_policy>" present and no "$output_language" — bounded by spec §3 M3.


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_configure_none_then_build_with_language_kwarg(mock_dv):
    """S4 regression: a request-time language= must not reactivate a removed layer."""
    mock_dv.get_all_names.return_value = []
    bot = MockBot(language=None)
    await bot._configure_prompt_builder()
    prompt = bot._build_prompt(language="es", output_language="Spanish")
    assert "<output_language_policy>" not in prompt
    assert "$output_language" not in prompt


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_unsupported_language_is_treated_as_unset(mock_dv):
    mock_dv.get_all_names.return_value = []
    # FILL IN: MockBot(language="<b>fr</b>"); configure; assert "output_language" not in
    #   layer_names and the raw value never appears in the built prompt — bounded by S3.
```

### FILL IN checklist
- [ ] `test_prompt_byte_identical_when_unset` — equality against the pre-feature stack
- [ ] `test_prompt_contains_directive_when_set` — directive present, no surviving placeholder
- [ ] `test_unsupported_language_is_treated_as_unset` — removal + no raw value leak

---

## Acceptance Criteria

- [ ] `output_language` is in `default`, `agent`, `rag`, `voice` and `identity`; absent from `minimal()` and the `"minimal"` preset.
- [ ] With `language` unset, the built prompt equals the pre-feature stack's output byte for byte.
- [ ] With `language="es"`/`"es-MX"`, the prompt names "Spanish" and states the four rules.
- [ ] Configuring with `None` then calling `_build_prompt(language="es")` yields neither the directive nor a `$` leak.
- [ ] Unsupported values are treated as unset; the raw value never reaches the prompt.
- [ ] `sentinel_not_found` / `sentinel_error` are always in the configure context (English when unset).
- [ ] `test_abstractbot_integration.py` and `test_builder.py` pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/prompts/test_output_language_wiring.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_builder.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_abstractbot_integration.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_presets.py -q`

---

## Test Specification

See the `test_output_language_wiring.py` blueprint block above.

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
