# HOTFIX-97d065c34ef4-1: Tighten AgentCrew.__init__ Google credential guards to all four signals

**Feature**: issue:97d065c34ef4 — Crew-level default Google client injection doesn't check credentials_file/credentials/vertexai, only api_key
**Spec**: `sdd/briefs/crew-google-credential-guards.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-575 gave `AgentCrew` a crew-level `google_api_key` that is injected into
every default-built Google client. The per-agent path
(`apply_google_api_key`, `credentials.py:102-135`) refuses injection when the
agent brought its own credential — any truthy `api_key`, `credentials_file`,
`credentials`, or `vertexai` in its `llm_kwargs`. The two inline injection
sites in `AgentCrew.__init__` (crew.py:238 and crew.py:246) only check
`"api_key" not in kwargs`, so an explicit `credentials_file=...`,
`credentials=...`, or `vertexai=True` passed to the crew's orchestration
client is overridden-alongside by the injected `api_key`, violating
`docs/crew_handler.md:581-591` ("An explicit credential always wins").

This task implements the brief's single fix chunk: one shared guard helper in
`credentials.py`, used by both `__init__` sites and by `apply_google_api_key`.

---

## Scope

- Add `has_explicit_google_credential(kwargs: Mapping[str, Any]) -> bool` to
  `parrot/bots/flows/crew/credentials.py`: returns `True` when any of
  `api_key`, `credentials_file`, `credentials` is truthy OR `vertexai` is
  truthy in the given mapping. Google-style docstring, exported (no leading
  underscore).
- Refactor `apply_google_api_key` to delegate its credential check
  (`credentials.py:129-132`) to the new helper — behavior unchanged.
- Modify both `AgentCrew.__init__` injection guards (crew.py:238, crew.py:246)
  to use `has_explicit_google_credential(kwargs)` instead of
  `"api_key" not in kwargs`.
- Extend `packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py`
  with cases for `credentials_file`, `credentials`, `vertexai=True`, and an
  explicit `api_key=None` on both the string-LLM (`llm="google"`) and
  default-LLM branches.

**NOT in scope**:
- The run_loop / executive-summary lazy fallbacks (crew.py:2153, crew.py:4407)
  — no caller kwargs flow there.
- `AgentCrew.from_definition` / per-agent injection behavior (already correct).
- `docs/crew_handler.md` wording changes.
- Any change to `CrewDefinition`, `BotManager`, or `CrewHandler`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` | MODIFY | Add `has_explicit_google_credential()`; refactor `apply_google_api_key` to use it |
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | Use the helper in both `__init__` injection guards |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py` | MODIFY | Add credentials_file / credentials / vertexai / api_key=None cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .credentials import GOOGLE_PROVIDER_KEYS, apply_google_api_key  # verified: crew.py:61 (extend this line with has_explicit_google_credential)
from parrot.bots.flows.crew import AgentCrew  # verified: test_crew_google_key.py:5
from parrot.clients.factory import SUPPORTED_CLIENTS  # verified: test_crew_google_key.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py
_CREDENTIAL_KWARGS: tuple[str, ...] = ("api_key", "credentials_file", "credentials")  # line 27
def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool:  # line 102
    # lines 128-132 — the check to extract into the helper:
    #   llm_kwargs = getattr(agent, "_llm_kwargs", None) or {}
    #   if any(llm_kwargs.get(key) for key in _CREDENTIAL_KWARGS): return False
    #   if llm_kwargs.get("vertexai"): return False

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — AgentCrew.__init__ (lines 158-320)
# line 238: if google_api_key and llm.lower() in GOOGLE_PROVIDER_KEYS and "api_key" not in kwargs:
# line 239:     client_kwargs = {**kwargs, "api_key": google_api_key}
# line 246: if google_api_key and "api_key" not in kwargs:
# line 247:     client_kwargs = {**kwargs, "api_key": google_api_key}
```

### Does NOT Exist
- ~~`parrot.bots.flows.crew.credentials.has_explicit_google_credential`~~ — this task CREATES it
- ~~a crew-level `llm_kwargs` parameter on `AgentCrew.__init__`~~ — orchestration client kwargs arrive via `**kwargs`
- ~~`AgentCrew._credential_kwargs`~~ — the signal list lives only in credentials.py

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/crew.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#apply_google_api_key",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.__init__"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# credentials.py — the new helper mirrors the existing check verbatim:
def has_explicit_google_credential(kwargs: Mapping[str, Any]) -> bool:
    """Report whether ``kwargs`` carries an explicit Google credential signal.

    True when any of ``api_key``/``credentials_file``/``credentials`` is truthy,
    or ``vertexai`` is truthy (docs/crew_handler.md "Precedence").
    """
    if any(kwargs.get(key) for key in _CREDENTIAL_KWARGS):
        return True
    return bool(kwargs.get("vertexai"))
```

### Key Constraints
- Truthiness semantics, not key presence — identical to `apply_google_api_key`.
  An explicit `api_key=None` must NOT block injection after this change (this
  is an intentional, documented behavior change; cover it with a test).
- `apply_google_api_key`'s public signature and return contract are unchanged;
  only its internal check delegates to the helper.
- Never mutate `kwargs`; keep the existing `client_kwargs = {**kwargs, ...}`
  rebinding pattern (see memory: AbstractBot mutates llm_kwargs hazard).
- The key value is never logged (module docstring invariant, credentials.py:9).
- 120-column lines, Google-style docstrings, strict type hints
  (`from collections.abc import Mapping` or `typing.Mapping` — match the
  module's existing `typing` imports).

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` — helper home,
  check to extract (lines 128-132)
- `docs/crew_handler.md:581-591` — the Precedence contract this enforces
- `packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py` —
  `_FakeClient` + `monkeypatch.setitem(SUPPORTED_CLIENTS, ...)` test pattern

---

## Implementation Blueprint

### Steps (in order)
1. Add `has_explicit_google_credential()` to credentials.py below
   `_CREDENTIAL_KWARGS` — *why*: single source of truth for the four signals.
2. Replace `apply_google_api_key`'s inline check (lines 129-132) with a call to
   the helper on `llm_kwargs` — *why*: both paths must share semantics.
3. In crew.py:61 extend the import; replace `"api_key" not in kwargs` with
   `not has_explicit_google_credential(kwargs)` at lines 238 and 246 — *why*:
   the fix itself.
4. Add the new test cases — *why*: lock the contract for both branches.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY)
```python
# occurrences: 1 (verified: crew.py:238)
# REPLACE
            if google_api_key and llm.lower() in GOOGLE_PROVIDER_KEYS and "api_key" not in kwargs:
# WITH
            if google_api_key and llm.lower() in GOOGLE_PROVIDER_KEYS and not has_explicit_google_credential(kwargs):
```
```python
# occurrences: 1 (verified: crew.py:246)
# REPLACE
            if google_api_key and "api_key" not in kwargs:
# WITH
            if google_api_key and not has_explicit_google_credential(kwargs):
```
**Why this shape**: the guard change is the entire crew.py diff; the
`client_kwargs = {**kwargs, "api_key": google_api_key}` lines below each guard
stay untouched.

### FILL IN checklist
- [ ] `credentials.py::has_explicit_google_credential` — exact docstring wording; bounded by the Pattern above
- [ ] `test_crew_google_key.py` — the eight new cases; bounded by Test Specification

---

## Acceptance Criteria

- [ ] `AgentCrew(google_api_key="k", credentials_file="f.json")` (default
  branch) and `AgentCrew(llm="google", google_api_key="k", credentials_file="f.json")`
  (string branch) construct the client WITHOUT `api_key` in its kwargs
- [ ] Same for `credentials={...}` and `vertexai=True`
- [ ] `AgentCrew(google_api_key="k", api_key=None)` now injects `api_key="k"`
  (truthiness semantics, matching `apply_google_api_key`)
- [ ] `apply_google_api_key` behavior unchanged — existing
  `test_crew_from_definition_google_key.py` passes untouched
- [ ] All tests pass; no linting errors (`ruff check` on the three files)
- [ ] Import works: `from parrot.bots.flows.crew.credentials import has_explicit_google_credential`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_from_definition_google_key.py -q`
- `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py`

---

## Test Specification

```python
# Extend packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py
# (reuses the module's _FakeClient + monkeypatch.setitem(SUPPORTED_CLIENTS, ...) pattern)

@pytest.mark.parametrize(
    "cred_kwargs",
    [
        {"credentials_file": "sa.json"},
        {"credentials": {"client_email": "x"}},
        {"vertexai": True},
    ],
)
def test_crew_default_llm_explicit_credential_blocks_key(monkeypatch, cred_kwargs):
    """Any explicit credential signal suppresses crew-key injection (default branch)."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    _FakeClient.last_kwargs = {}
    AgentCrew(google_api_key="k", **cred_kwargs)
    assert "api_key" not in _FakeClient.last_kwargs


@pytest.mark.parametrize(
    "cred_kwargs",
    [
        {"credentials_file": "sa.json"},
        {"credentials": {"client_email": "x"}},
        {"vertexai": True},
    ],
)
def test_crew_string_llm_explicit_credential_blocks_key(monkeypatch, cred_kwargs):
    """Same suppression on the llm='google' string branch."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    _FakeClient.last_kwargs = {}
    AgentCrew(llm="google", google_api_key="k", **cred_kwargs)
    assert "api_key" not in _FakeClient.last_kwargs


def test_crew_explicit_none_api_key_now_injects(monkeypatch):
    """api_key=None is not a credential — truthiness semantics (behavior change)."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    AgentCrew(google_api_key="k", api_key=None)
    assert _FakeClient.last_kwargs["api_key"] == "k"


def test_has_explicit_google_credential_helper():
    from parrot.bots.flows.crew.credentials import has_explicit_google_credential

    assert has_explicit_google_credential({"api_key": "x"})
    assert has_explicit_google_credential({"credentials_file": "f"})
    assert has_explicit_google_credential({"credentials": {"a": 1}})
    assert has_explicit_google_credential({"vertexai": True})
    assert not has_explicit_google_credential({})
    assert not has_explicit_google_credential({"api_key": None, "vertexai": False})
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the brief worktree**
   (`.claude/worktrees/fix-97d065c34ef4-crew-google-credential-guards`) — never
   on `dev`.
2. **Read the brief** at `sdd/briefs/crew-google-credential-guards.brief.md`.
3. **Verify the Codebase Contract** — confirm crew.py:238/246 and
   credentials.py:27/102/128-132 still match before editing; if lines drifted,
   re-grep and update the contract first.
4. **Implement** per the blueprint; touch only the three listed files.
5. **Verify** — run every Validation Command with
   `PYTHONPATH=packages/ai-parrot/src`.
6. **Commit code** staging only the three files:
   `fix(crew): HOTFIX-97d065c34ef4-1 — honor all four Google credential signals in AgentCrew.__init__`.
7. **Update** this file's Completion Note and the per-brief index status, then
   commit the SDD state.
8. Done → the owner runs `/sdd-done 97d065c34ef4`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
