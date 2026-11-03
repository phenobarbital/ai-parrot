# TASK-5140: AgentCrew: CREW_LLM, CREW_GOOGLE_API_KEY and CREW usage tag

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5138, TASK-5139
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (+M7 entry point). Removes the double `gemini-2.5-pro` hardcoding in `AgentCrew` and gives crews their own key `CREW_GOOGLE_API_KEY`, keeping `CREW_AI_KEY` as a silent alias (spec §8 resolved).

---

## Scope

- `run_sequential(model: Optional[str] = None)`; when None use `resolve_component_llm('CREW', builtin=_CREW_BUILTIN_LLM).model`.
- Replace the lazy client at crew.py:2146-2156 with a `SUPPORTED_CLIENTS` lookup for the resolved provider, `max_tokens=8192`, key = `self._google_api_key` (explicit wins) else `resolve_component_api_key(('CREW',), provider, legacy=('CREW_AI_KEY',))`.
- `get_crew_google_api_key()`: `CREW_GOOGLE_API_KEY` → `CREW_AI_KEY` → None; warn-once text names both.
- Tag crew runs: decorate `run_sequential`, `run_parallel`, `run_flow`, `run_loop`, `ask` with a private `_crew_usage_scope` decorator that wraps the call in `usage_component('CREW')`.
- Tests.

**NOT in scope**: Changing `CrewDefinition` or the HTTP handlers. Deprecating `CREW_AI_KEY`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | model/key resolution + tagging |
| `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` | MODIFY | CREW_GOOGLE_API_KEY first |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
from ....llm_defaults import resolve_component_llm, resolve_component_api_key  # created by TASK-5138 (relative from crew.py)
from ....observability.context import usage_component  # created by TASK-5139
from ....clients.factory import SUPPORTED_CLIENTS  # verified: crew.py:60
from ...abstract import AbstractBot, _resolve_supported_client  # verified: crew.py:58
```

### Existing Signatures to Use
```python
# crew.py
    async def run_sequential(..., model: Optional[str] = "gemini-2.5-pro", **kwargs) -> FlowResult:  # 1744 / 1755
    async def run_loop(...)  # 2090 — lazy client lines 2146-2156
    async def run_parallel(...)  # 2587
    async def run_flow(...)  # 2933
    async def ask(...)  # 3832
        self._google_api_key = google_api_key  # 234
            client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get(llm.lower(), None))  # 237 — pattern
# credentials.py
def get_crew_google_api_key() -> Optional[str]:  # 50; key read at 61; warning at 66
```

### Does NOT Exist
- ~~`GoogleGenAIClient` hardcoded in the lazy path~~ — removed by this task
- ~~`AgentCrew._resolve_llm`~~ — no such helper; inline per blueprint
- ~~an `EXPERT_*` key here~~ — experts are TASK-5141

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/crew.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#get_crew_google_api_key"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `if self._google_api_key:` occurs twice (2153, 4407); only the 2146-2156 block changes — quote its `GoogleGenAIClient(model="gemini-2.5-pro"` lines.
- If the decorator is applied to `ask`, `run_*` called from `ask` nest harmlessly (same value).
- `functools.wraps` the decorator so signatures/introspection stay intact.
- Existing crew key tests (`test_crew_credentials.py`) must stay green with only `CREW_AI_KEY` set (AC5).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. Add `_CREW_BUILTIN_LLM = "google:gemini-2.5-pro"` and `_crew_usage_scope` near the module top — *why*: single literal (AC8).
2. run_sequential default → None + resolution at the top of the body — *why*: env-driven.
3. Replace the lazy client block — *why*: provider no longer hardcoded.
4. credentials.py cascade — *why*: AC3/AC5.
5. Decorate the five entry points — *why*: AC10.
6. Tests.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY)
```python
# (a) module level, after the imports block:
_CREW_BUILTIN_LLM = "google:gemini-2.5-pro"


def _crew_usage_scope(func):
    """Tag every client call made inside a crew entry point as component ``CREW`` (FEAT-796)."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        with usage_component("CREW"):
            return await func(*args, **kwargs)
    return wrapper
# FILL IN: add `import functools` if not already imported (check crew.py:40-43)

# (b) occurrences: 1 — line 1755
        model: Optional[str] = None,
# and first statement of run_sequential body (after the docstring):
        model = model or resolve_component_llm("CREW", builtin=_CREW_BUILTIN_LLM).model

# (c) occurrences of 'GoogleGenAIClient(model="gemini-2.5-pro"': 2 (lines 2154, 2156) — replace lines 2146-2156 with:
        if not self._llm:
            resolved = resolve_component_llm("CREW", builtin=_CREW_BUILTIN_LLM)
            client_cls = _resolve_supported_client(SUPPORTED_CLIENTS.get(resolved.provider.lower(), None))
            # FILL IN: raise RuntimeError naming the provider when client_cls is None
            #          (satellite not installed) — bounded by spec §7
            api_key = self._google_api_key or resolve_component_api_key(
                ("CREW",), resolved.provider, legacy=("CREW_AI_KEY",)
            )
            client_kwargs = {"model": resolved.model, "max_tokens": 8192}
            if api_key:
                client_kwargs["api_key"] = api_key
            self._llm = client_cls(**client_kwargs)

# (d) decorate: put `@_crew_usage_scope` directly above
#     `async def run_sequential(` (1744), `async def run_loop(` (2090), `async def run_parallel(` (2587),
#     `async def run_flow(` (2933), `async def ask(` (3832) — each occurs once
```

### `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    key = getattr(conf, "CREW_AI_KEY", None)' credentials.py) — line 61
    from navconfig import config  # noqa: PLC0415
    key = config.get("CREW_GOOGLE_API_KEY") or getattr(conf, "CREW_AI_KEY", None)
# and line 66 warning text becomes:
        logger.warning("CREW_GOOGLE_API_KEY / CREW_AI_KEY not set; crew Google agents fall back to GOOGLE_API_KEY")
# FILL IN: update the function docstring to state the order CREW_GOOGLE_API_KEY -> CREW_AI_KEY -> None
```

### FILL IN checklist
- [ ] crew.py `import functools` presence
- [ ] RuntimeError for missing client class; bounded by spec §7
- [ ] credentials docstring

---

## Acceptance Criteria

- [ ] No `"gemini-2.5-pro"` literal in crew.py except `_CREW_BUILTIN_LLM` (AC8)
- [ ] `CREW_LLM` changes the lazy client provider/model and run_sequential default
- [ ] `CREW_GOOGLE_API_KEY` beats `CREW_AI_KEY`; explicit `google_api_key` beats both
- [ ] Unset env → identical behavior to today
- [ ] Crew client calls tagged `component="CREW"`
- [ ] Existing crew key tests green

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py -q`

---

## Test Specification

```python
def test_crew_google_key_precedence(monkeypatch): ...
def test_crew_ai_key_alias_still_works(monkeypatch): ...
async def test_crew_lazy_llm_uses_crew_llm(monkeypatch): ...  # patch SUPPORTED_CLIENTS with a fake client capturing kwargs
async def test_crew_sequential_default_model(monkeypatch): ...
async def test_crew_calls_tagged_crew(): ...  # inside run_*, current_component.get() == "CREW"
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5140 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
