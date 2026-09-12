# TASK-3179: Inject the conventions into the three dispatch prompt builders

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3178
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Every MCP seat receives only the `sdd-coder.md` body today.
This task pastes `load_project_conventions(cwd)` inline — never "go read the
file", which costs turns — right after `Subagent instructions:` in the three
builders that compose their own prompt. `NovaCodeDispatcher` and
`GoogleCompatCodeDispatcher` inherit `_initial_messages` and need no change.

---

## Scope

- Re-export `CODER_RULE_NAMES`, `CONVENTIONS_PREAMBLE`, `load_project_conventions`
  from `_subagent_defs.py` (no logic there).
- `LLMCodeDispatcher._initial_messages`: append the preamble + conventions to the
  system message after the body.
- `CodexCodeDispatcher._build_codex_prompt` and `GoogleCodingDispatcher._build_agy_prompt`:
  add `*, cwd: str = ""`, append the block between the body and the output
  prompt; pass `cwd=cwd` at the two call sites.
- Tests for the three builders and the re-export.

**NOT in scope**: installers/AGENTS.md (TASK-3180/3181), the loader itself
(TASK-3178), any change to what `load_subagent_definition` returns.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | re-export three names |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `_initial_messages` system content |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | `_build_codex_prompt(cwd=)` + call site |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `_build_agy_prompt(cwd=)` + call site |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs_conventions.py` | CREATE | re-export identity |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | one new test after `test_system_prompt_names_the_working_directory` |
| `packages/ai-parrot/tests/flows/dev_loop/test_prompt_builders_conventions.py` | CREATE | codex + agy builder tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.conventions import CODER_RULE_NAMES, CONVENTIONS_PREAMBLE, load_project_conventions  # TASK-3178 (must be completed)
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition   # verified: _subagent_defs.py:89
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher          # verified: llm.py:51
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher      # verified: codex.py:43
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher  # verified: google_coding.py:48
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile          # verified: models/llm.py:10
from parrot.flows.dev_loop.models.codex import CodexCodeDispatchProfile      # verified: models/codex.py:10
from parrot.flows.dev_loop.models.google_coding import GoogleCodingDispatchProfile  # verified: models/google_coding.py:15
from parrot.flows.dev_loop.models import DevelopmentOutput                   # used by test_llm_code_dispatcher.py:716
```

### Existing Signatures to Use
```python
# _subagent_defs.py
from importlib.resources import files                   # line 48 — add the new import directly below it
__all__ = ["load_subagent_definition"]                  # line 117 — replace

# dispatchers/llm.py
def _initial_messages(self, profile, brief, output_model, *, cwd: str = "") -> List[Dict[str, Any]]:   # line 891
    body = load_subagent_definition(profile.subagent)   # line 899
    ...                 f"Subagent instructions:\n{body}"                                             # line 940 — LAST f-string of the system content
# dispatchers/nova.py:66 NovaCodeDispatcher(LLMCodeDispatcher); google_compat.py:19 GoogleCompatCodeDispatcher(LLMCodeDispatcher) — inherit, no change

# dispatchers/codex.py
prompt = self._build_codex_prompt(profile, brief, output_model)                                        # line 118 (inside dispatch(); `cwd` is a parameter in scope)
def _build_codex_prompt(self, profile: CodexCodeDispatchProfile, brief: BaseModel, output_model: Type[BaseModel]) -> str:  # line 345
    body = load_subagent_definition(profile.subagent)                                                  # line 351
    output_prompt = self._build_prompt(brief, output_model)                                            # line 352
    return (f"You are the `{profile.subagent}` dev-loop subagent.\n\n" f"Subagent instructions:\n{body}\n\n" f"{output_prompt}")  # lines 353-357

# dispatchers/google_coding.py
prompt = self._build_agy_prompt(profile, brief, output_model)                                          # line 171 (inside dispatch(); `cwd` in scope)
def _build_agy_prompt(self, profile: GoogleCodingDispatchProfile, brief: BaseModel, output_model: Type[BaseModel]) -> str:  # line 317 — same body shape as codex, lines 323-329

# tests/flows/dev_loop/test_llm_code_dispatcher.py
def _dispatcher(monkeypatch, client: _FakeClient) -> LLMCodeDispatcher:   # line 91 — builds a dispatcher with fakes
@pytest.fixture def brief(_patch_worktree_base) -> ResearchOutput:        # line 79-80
def test_system_prompt_names_the_working_directory(monkeypatch, brief, tmp_path):   # line 711 — calls dispatcher._initial_messages(LLMCodeDispatchProfile(), brief, DevelopmentOutput, cwd=str(tmp_path)) and reads messages[0]["content"]
```

### Does NOT Exist
- ~~`LLMCodeDispatchProfile.conventions` / `.rules`~~ — no profile field; the text is composed in the builder.
- ~~`TaskScopedBrief.rules`~~ — the brief is `{research, task_id, task_file}` (models/base.py:458).
- ~~a second `Subagent instructions:` occurrence in any of the three files~~ — each has exactly one (verified `grep -c`), so the anchors are unique.
- ~~`_build_codex_prompt(..., cwd)` positional~~ — `cwd` is keyword-only with default `""` (spec AC-13).

---

## Implementation Notes

### Key Constraints
- Insertion point: AFTER the subagent body, BEFORE the output prompt (codex/agy) or as the tail of the system content (llm). Use `CONVENTIONS_PREAMBLE`, never a re-typed literal.
- `load_project_conventions(cwd or None)` — an empty `cwd` must fall back to the package copy, not to `Path("")`.
- Signatures of the three builders keep their positional parameters (spec AC-13).

### References in Codebase
- `dispatchers/llm.py:891-947` — the system-message assembly.

---

## Implementation Blueprint

### Steps (in order)
1. Add the re-export to `_subagent_defs.py` — *why*: dispatchers import from `_subagent_defs` today; keeping that import site stable avoids touching the package `__init__`.
2. Patch `llm.py` — *why*: nova/google-compat inherit it, so this one edit covers three seats.
3. Patch `codex.py` and `google_coding.py` (signature, body, call site) — *why*: they build a single prompt string, not messages.
4. Write the tests; run `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py packages/ai-parrot/tests/flows/dev_loop/test_prompt_builders_conventions.py packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs_conventions.py -v`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from importlib.resources import files' packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py)
# AFTER — insert below `from importlib.resources import files` (verified: _subagent_defs.py:48)
from parrot.flows.conventions import (  # FEAT-553 re-export; the loader lives in a stdlib-only leaf module
    CODER_RULE_NAMES,
    CONVENTIONS_PREAMBLE,
    load_project_conventions,
)

# occurrences: 1 (verified: grep -c '^__all__ = \["load_subagent_definition"\]' …/_subagent_defs.py)
# REPLACE `__all__ = ["load_subagent_definition"]` (verified: _subagent_defs.py:117) with:
__all__ = ["load_subagent_definition", "load_project_conventions", "CODER_RULE_NAMES", "CONVENTIONS_PREAMBLE"]
```
**Why**: spec §3 M2 fixes the re-export; `noqa` is not needed because the names are in `__all__`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'f"Subagent instructions:\\n{body}"' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# REPLACE the line `                    f"Subagent instructions:\n{body}"` (verified: llm.py:940) with:
                    f"Subagent instructions:\n{body}\n\n"
                    f"{CONVENTIONS_PREAMBLE}\n{load_project_conventions(cwd or None)}"
# and extend the existing import at llm.py:30:
#   from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
# → from parrot.flows.dev_loop._subagent_defs import CONVENTIONS_PREAMBLE, load_project_conventions, load_subagent_definition
```
**Why**: the system message is one implicit string concatenation; the new f-strings join it without changing the surrounding parentheses.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'prompt = self._build_codex_prompt(profile, brief, output_model)' …/codex.py)
# REPLACE call site (verified: codex.py:118) with:
                prompt = self._build_codex_prompt(profile, brief, output_model, cwd=cwd)

# occurrences: 1 — REPLACE the whole method (verified: codex.py:345-357) with:
    def _build_codex_prompt(
        self,
        profile: CodexCodeDispatchProfile,
        brief: BaseModel,
        output_model: Type[BaseModel],
        *,
        cwd: str = "",
    ) -> str:
        body = load_subagent_definition(profile.subagent)
        conventions = load_project_conventions(cwd or None)
        output_prompt = self._build_prompt(brief, output_model)
        return (
            f"You are the `{profile.subagent}` dev-loop subagent.\n\n"
            f"Subagent instructions:\n{body}\n\n"
            f"{CONVENTIONS_PREAMBLE}\n{conventions}\n\n"
            f"{output_prompt}"
        )
# extend the import at codex.py:22 the same way as llm.py:30
```
**Why**: codex also reads `AGENTS.md` natively; the duplicate is intentional (spec §7) so a hand-launched session and a dispatched one see the same rules.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` (MODIFY)
```python
# occurrences: 1 — REPLACE call site (verified: google_coding.py:171) with:
                prompt = self._build_agy_prompt(profile, brief, output_model, cwd=cwd)
# occurrences: 1 — REPLACE the whole method (verified: google_coding.py:317-329) with the same shape as the codex block, method name `_build_agy_prompt`, profile type `GoogleCodingDispatchProfile`; extend the import at google_coding.py:24.
```
**Why**: identical contract for the two CLI seats.

### `packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs_conventions.py` (CREATE)
```python
"""The dev-loop re-export is the SAME object as the leaf module's (FEAT-553)."""
from parrot.flows import conventions
from parrot.flows.dev_loop import _subagent_defs


def test_reexport_identity():
    assert _subagent_defs.load_project_conventions is conventions.load_project_conventions
    assert _subagent_defs.CONVENTIONS_PREAMBLE == conventions.CONVENTIONS_PREAMBLE
    assert _subagent_defs.CODER_RULE_NAMES == conventions.CODER_RULE_NAMES
```

### `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def test_system_prompt_names_the_working_directory' …/test_llm_code_dispatcher.py)
# AFTER — append this test below the end of `test_system_prompt_names_the_working_directory` (verified: :711-724)
def test_system_prompt_carries_the_conventions(monkeypatch, brief, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    messages = dispatcher._initial_messages(LLMCodeDispatchProfile(), brief, DevelopmentOutput, cwd=str(tmp_path))
    system = messages[0]["content"]
    # FILL IN: assert CONVENTIONS_PREAMBLE in system, "## Project rule: codebase-conventions" in system,
    #          and system.index("Subagent instructions:") < system.index("## Project rule: codebase-conventions") — bounded by AC-5
```

### `packages/ai-parrot/tests/flows/dev_loop/test_prompt_builders_conventions.py` (CREATE)
```python
"""Codex and agy prompt builders carry the conventions block (FEAT-553, spec AC-5)."""
from __future__ import annotations

from parrot.flows.conventions import CONVENTIONS_PREAMBLE
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher
from parrot.flows.dev_loop.models import DevelopmentOutput, TaskScopedBrief
from parrot.flows.dev_loop.models.codex import CodexCodeDispatchProfile
from parrot.flows.dev_loop.models.google_coding import GoogleCodingDispatchProfile


def _brief() -> TaskScopedBrief:
    # FILL IN: build a minimal ResearchOutput (see test_llm_code_dispatcher.py:79-89 `brief` fixture) and wrap it — bounded by models/base.py:458
    raise NotImplementedError


def test_codex_prompt_carries_the_conventions(tmp_path):
    d = CodexCodeDispatcher(redis_url="redis://localhost/0", max_concurrent=1, stream_ttl_seconds=60)  # FILL IN: mirror how existing codex tests construct it (grep 'CodexCodeDispatcher(' packages/ai-parrot/tests)
    prompt = d._build_codex_prompt(CodexCodeDispatchProfile(subagent="sdd-coder"), _brief(), DevelopmentOutput, cwd=str(tmp_path))
    assert CONVENTIONS_PREAMBLE in prompt
    assert prompt.index("Subagent instructions:") < prompt.index(CONVENTIONS_PREAMBLE) < prompt.index("TASK BRIEF")


def test_agy_prompt_carries_the_conventions(tmp_path):
    # FILL IN: same for GoogleCodingDispatcher._build_agy_prompt / GoogleCodingDispatchProfile(subagent="sdd-coder") — bounded by AC-5
    raise NotImplementedError
```
**Why**: the ordering assertion is the contract (body → conventions → output prompt); `"TASK BRIEF"` is the first line of both `_build_prompt` outputs (codex.py:557, google_coding.py:331).

### FILL IN checklist
- [ ] `test_llm_code_dispatcher.py::test_system_prompt_carries_the_conventions` — assertions; bounded by AC-5
- [ ] `test_prompt_builders_conventions.py::_brief` and dispatcher construction — copy from existing tests; bounded by existing fixtures
- [ ] `test_prompt_builders_conventions.py::test_agy_prompt_carries_the_conventions` — body; bounded by AC-5

---

## Acceptance Criteria

- [ ] All three builders emit `CONVENTIONS_PREAMBLE` + `## Project rule: codebase-conventions` after `Subagent instructions:` (spec AC-5)
- [ ] `NovaCodeDispatcher` / `GoogleCompatCodeDispatcher` unchanged and still pass `pytest packages/ai-parrot/tests/flows/dev_loop/ -k "nova or google_compat"`
- [ ] Builder signatures keep positional parameters; `cwd` keyword-only, default `""` (spec AC-13)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py packages/ai-parrot/tests/flows/dev_loop/test_prompt_builders_conventions.py packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs_conventions.py -v`
- [ ] `ruff check` clean on the four modified source files

---

## Test Specification

See the CREATE/MODIFY test blocks above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M2, §6, §7 "Inline, never go read")
2. **Check dependencies** — `TASK-3178` in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `grep -n 'Subagent instructions' …/llm.py …/codex.py …/google_coding.py` must return exactly one line each
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; never re-type the preamble literal
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3179-inject-conventions-into-prompt-builders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrator, attempt 2 — direct implementation after the MCP attempt ran out of turns)
**Date**: 2026-09-12
**Notes**: Re-exported `CODER_RULE_NAMES`/`CONVENTIONS_PREAMBLE`/
`load_project_conventions` from `_subagent_defs.py`. `LLMCodeDispatcher.
_initial_messages`, `CodexCodeDispatcher._build_codex_prompt` and
`GoogleCodingDispatcher._build_agy_prompt` all append the preamble +
conventions block right after `Subagent instructions:\n{body}`, before the
output prompt (codex/agy) or as the tail of the system content (llm); both
builder methods gained a keyword-only `cwd: str = ""` and their two call
sites pass `cwd=cwd`. `nova`/`google-compat` inherit `_initial_messages`
unchanged (verified: 93 tests pass under `-k "nova or google_compat"`).
66 new/extended tests pass; `ruff check` clean on all four modified
source files.

Orchestrator note: attempt 1 (gemini/google-compat) exhausted its turn
budget partway through — its uncommitted diff touched only
`_subagent_defs.py` and `llm.py`'s import line, matching the blueprint
exactly. The orchestrator reproduced those two edits and completed the
rest (codex.py, google_coding.py, all three test files) directly.
Separately, one Codebase Contract anchor in the task was stale: it
claimed `"TASK BRIEF"` is the first line of BOTH `_build_prompt` outputs,
but only `google_coding._build_prompt` uses that string —
`codex._build_prompt` actually starts with `"Input brief:"`. The new
`test_codex_prompt_carries_the_conventions` asserts the correct string;
no functional change was needed.

**Deviations from spec**: none in the merged code; one stale Codebase
Contract anchor (codex's output-prompt marker string) corrected in the
test that depends on it — see Notes.

Seat: gemini (attempt 1, exhausted turn budget, no commit) → orchestrator direct (attempt 2) · Backend: google-compat → n/a · Model: gemini-3.5-flash → n/a · Attempts: 1 (failed) + 1 direct · Duration: 77.1s (failed attempt) + orchestrator time · Tokens: 1285254 in / 6928 out (attempt 1, discarded)
