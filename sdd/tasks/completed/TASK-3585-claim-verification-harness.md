# TASK-3585: Add metadata cross-check and hello-world tests to the claim harness

**Feature**: FEAT-586 — Public Install & Getting-Started Guide for AI-Parrot
**Spec**: `sdd/specs/parrot-install-guide.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3584
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. Extends the test module created by TASK-3584 with
the checks that pin the guide's factual claims to live package metadata — the
whole point of Option C (spec §2). This task **depends on TASK-3584** because it
imports `extract_claims`/`DocClaim` and reads `docs/getting-started.md`; both are
delivered there. It adds tests only — no new fixtures file (fixtures live inline
to avoid a shared `conftest.py` that other tasks' tests would load).

---

## Scope

- MODIFY `packages/ai-parrot/tests/docs/test_getting_started_claims.py`, adding:
  - `test_python_range_matches_pyproject` — every `python-range` claim equals
    `requires-python` in `packages/ai-parrot/pyproject.toml`.
  - `test_named_extras_exist` — every `extra` claim is a key of
    `[project.optional-dependencies]`.
  - `test_named_scripts_exist` — every `script` claim is a key of `[project.scripts]`.
  - `test_named_providers_are_registered` — every `provider` claim resolves in
    `entry_points(group="parrot.clients")`.
  - `test_named_dep_floors_match` — every `dep=<dist>:<req>` claim matches that
    satellite's declared dependency floor (spec AC18).
  - `test_hello_world_snippet_executes` — the guide's hello-world runs against a
    stub provider (no network, no key).
  - `test_failure_message_names_file_and_line` — a stale claim fails naming
    `file:line` and the offending value (spec AC12).

**NOT in scope**: the extractor/`DocClaim` (TASK-3584 owns them); the guide text;
the installer scripts; CI wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/docs/test_getting_started_claims.py` | MODIFY | Add the seven cross-check / execution / failure tests + inline fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib
import importlib.metadata as importlib_metadata
from pathlib import Path
# from the same module (added by TASK-3584):
from .test_getting_started_claims import extract_claims, DocClaim, GUIDE, REPO_ROOT  # or module-local refs
from parrot.clients.factory import LLMFactory  # verified: packages/ai-parrot/src/parrot/clients/factory.py
from parrot.bots.agent import BasicAgent        # verified: examples/basic_agent.py usage
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def list_providers() -> dict: ...   # backs test_named_providers_are_registered

# entry-point group holding all provider keys (verified: 37 keys resolve today):
importlib_metadata.entry_points(group="parrot.clients")   # names include claude-code, codex-code, google
```

### Key facts
- `requires-python` lives at `packages/ai-parrot/pyproject.toml` → `[project]` `requires-python`.
- extras → `[project.optional-dependencies]`; scripts → `[project.scripts]` (same file).
- provider claims resolve against `entry_points(group="parrot.clients")` names.
- dep claim form: `<dist>:<requirement>` e.g. `ai-parrot-client-anthropic:claude-agent-sdk>=0.1.68`
  (that satellite's `pyproject.toml:18`); `ai-parrot-client-openai:openai-codex>=0.1.0`
  (that satellite's `pyproject.toml:23`).

### Does NOT Exist
- ~~`parrot.clients.factory.SUPPORTED_CLIENTS` as an eager dict~~ — it is a lazy
  registry; read it via `LLMFactory.list_providers()` or `entry_points`, never
  by importing a provider.
- ~~a `conftest.py` for this suite~~ — fixtures are inline in the test module.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/tests/docs/test_getting_started_claims.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Offline: no network, no API key. The hello-world test registers a **stub**
  provider so `LLMFactory` resolves without a real backend.
- Read `pyproject.toml` with stdlib `tomllib` (3.11+) — no new dependency.
- Provider test asserts against declared extras when the satellite is absent and
  against entry points when present (spec §7 risk).

### References in Codebase
- `packages/ai-parrot/tests/test_llm_factory.py` — factory test patterns
- `packages/ai-parrot/tests/unit/clients/test_factory_discovery.py` — entry-point discovery + monkeypatch reset

---

## Implementation Blueprint

### Steps (in order)
1. Add a `_pyproject()` helper returning the parsed core `pyproject.toml` — *why*:
   three tests read it; parse once.
2. Add one test per claim kind, iterating `extract_claims(GUIDE)` filtered by kind
   — *why*: each asserts against the matching live source.
3. Add `test_hello_world_snippet_executes` with an inline stub provider — *why*:
   proves the headline example runs offline (AC7).
4. Add `test_failure_message_names_file_and_line` — *why*: proves the harness
   bites (AC12).

### `packages/ai-parrot/tests/docs/test_getting_started_claims.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_extract_claims_ignores_plain_comments' packages/ai-parrot/tests/docs/test_getting_started_claims.py)
# AFTER — append below `def test_extract_claims_ignores_plain_comments` (verified: TASK-3584 creates this symbol)
import tomllib
import importlib.metadata as importlib_metadata

CORE_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"


def _pyproject() -> dict:
    """Parsed core pyproject.toml (single source of truth for claim checks)."""
    return tomllib.loads(CORE_PYPROJECT.read_text(encoding="utf-8"))


def _claims(kind: str) -> list[DocClaim]:
    return [c for c in extract_claims(GUIDE) if c.kind == kind]


def test_python_range_matches_pyproject() -> None:
    """Every python-range claim equals requires-python."""
    want = _pyproject()["project"]["requires-python"]
    for c in _claims("python-range"):
        assert c.value == want, f"{c.source}:{c.line} claims '{c.value}', pyproject says '{want}'"


def test_named_extras_exist() -> None:
    """Every extra claim is a real optional-dependency key."""
    extras = set(_pyproject()["project"]["optional-dependencies"])
    for c in _claims("extra"):
        assert c.value in extras, f"{c.source}:{c.line} unknown extra '{c.value}'"


def test_named_scripts_exist() -> None:
    """Every script claim is a real console-script key."""
    scripts = set(_pyproject()["project"]["scripts"])
    for c in _claims("script"):
        assert c.value in scripts, f"{c.source}:{c.line} unknown script '{c.value}'"


def test_named_providers_are_registered() -> None:
    """Every provider claim resolves in the parrot.clients entry points."""
    names = {ep.name for ep in importlib_metadata.entry_points(group="parrot.clients")}
    for c in _claims("provider"):
        assert c.value in names, f"{c.source}:{c.line} unknown provider '{c.value}'"


def test_named_dep_floors_match() -> None:
    """Every `dep=<dist>:<req>` claim matches that satellite's declared floor."""
    # FILL IN: split value on ':' into (dist, requirement); read that satellite's
    #          pyproject.toml under packages/<dist>/ and assert `requirement` is a
    #          declared dependency string — bounded by AC18.
    raise NotImplementedError


def test_hello_world_snippet_executes(monkeypatch) -> None:
    """The guide's hello-world runs against a stub provider — offline."""
    # FILL IN: register a fake parrot.clients provider (monkeypatch entry-point
    #          discovery, per test_factory_discovery.py), then run BasicAgent
    #          configure()+invoke() with it; assert a non-empty answer. No network,
    #          no key — bounded by AC7.
    raise NotImplementedError


def test_failure_message_names_file_and_line(tmp_path) -> None:
    """A deliberately stale claim fails naming file, line and offending value."""
    # FILL IN: write a tmp guide with `<!-- verify: extra=does-not-exist -->`,
    #          point the extra check at it, assert AssertionError whose message
    #          contains the path, the line number and 'does-not-exist' — AC12.
    raise NotImplementedError
```
**Why this shape**: all reads go through stdlib `tomllib` and `importlib.metadata`
so the suite needs no new dependency and runs offline. The `dep`, hello-world and
failure tests are `FILL IN` because each needs a judgement call (satellite path
resolution, the stub-provider mechanism, the tmp-doc wiring) bounded by the cited
AC. Do not rename `extract_claims`/`DocClaim`/`GUIDE`/`REPO_ROOT` — they are
fixed by TASK-3584.

### FILL IN checklist
- [ ] `test_named_dep_floors_match` — dist/req split + satellite pyproject read; bounded by AC18
- [ ] `test_hello_world_snippet_executes` — stub-provider registration + BasicAgent run; bounded by AC7
- [ ] `test_failure_message_names_file_and_line` — tmp stale-claim doc + message assertion; bounded by AC12
- [ ] confirm `entry_points(group="parrot.clients")` is the correct group name in the installed tree

---

## Acceptance Criteria
- [ ] python-range / extra / script / provider / dep claims each asserted against live metadata (spec AC2, AC18)
- [ ] Hello-world executes offline against a stub provider (spec AC7, AC11)
- [ ] A stale claim fails naming file, line, offending value (spec AC12)
- [ ] `ruff check` and `black --check` pass (spec AC16)
- [ ] All harness tests pass: full module green

## Validation Commands
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_python_range_matches_pyproject -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_named_extras_exist -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_named_scripts_exist -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_named_providers_are_registered -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_named_dep_floors_match -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_hello_world_snippet_executes -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_failure_message_names_file_and_line -q`

---

## Test Specification
```python
def test_python_range_matches_pyproject(): ...
def test_named_extras_exist(): ...
def test_named_scripts_exist(): ...
def test_named_providers_are_registered(): ...
def test_named_dep_floors_match(): ...
def test_hello_world_snippet_executes(monkeypatch): ...
def test_failure_message_names_file_and_line(tmp_path): ...
```

---

## Agent Instructions
1. Read the spec (§2, §3 M2, §6) and TASK-3584's delivered module.
2. Verify: `LLMFactory.list_providers()` exists, the `parrot.clients` group name,
   and both satellite pyproject dep lines.
3. Index status → in-progress.
4. Implement from the blueprint; complete every `# FILL IN`.
5. Run the Validation Commands.
6. Move to `sdd/tasks/completed/`, index → done, fill the note.

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-21
**Notes**: Added `_pyproject()`, `_claims()`, `_declared_provider_keys()`,
`test_python_range_matches_pyproject`, `test_named_extras_exist`,
`test_named_scripts_exist`, `test_named_providers_are_registered`,
`test_named_dep_floors_match`, `test_hello_world_snippet_executes`,
`test_failure_message_names_file_and_line` to
`packages/ai-parrot/tests/docs/test_getting_started_claims.py`. All 10
tests in the module pass. `test_named_providers_are_registered` asserts
against the live `parrot.clients` entry-point registry when a satellite is
installed, falling back to the provider keys declared in each
`ai-parrot-client-*` satellite's own `pyproject.toml` in this repo tree
when none is installed (covers a bare-install CI environment per spec §7
risk). `test_hello_world_snippet_executes` registers a real,
dotted-path-resolvable mocked `EntryPoint` (same pattern as
`tests/unit/clients/test_factory_discovery.py`) under the `google`
provider key, pointing at a module-level offline `AbstractClient` stub, so
`BasicAgent`'s default LLM resolution runs fully offline.
**IMPORTANT — environment gotcha discovered while building this test**:
running `PYTHONPATH=packages/ai-parrot/src pytest ...` (literally as
worded in `.claude/rules/worktree-management.md` §4) *replaces* an
already-set `PYTHONPATH` in this shell that lists every workspace member's
`src/` (including every `ai-parrot-client-*` satellite) — under that
literal form, `entry_points(group="parrot.clients")` silently returns
empty and `parrot.clients.google` fails to import. The fix is to prepend,
not replace: `PYTHONPATH="$(pwd)/packages/ai-parrot/src:$PYTHONPATH"`.
Worth a doc fix for whoever hits this next; not filed as a ledger issue
since it is a documentation clarification, not a code defect.
**Deviations from spec**: none in this task's own scope. Two pre-existing,
out-of-scope bugs were confirmed by direct execution while building this
test (both already logged in TASK-3584's Completion Note and both to be
raised at code review / filed to the ledger):
  1. `BasicAgent.__init__` (`parrot/bots/agent.py`) unconditionally imports
     `GoogleGenAIClient` regardless of `llm=`, so it needs `parrot.clients
     .google` to be importable (or faked, as this test does) even when a
     different provider is requested.
  2. `examples/basic_agent.py`'s literal `answer, response = await
     agent.invoke(question)` raises `ValueError: too many values to
     unpack` against the current `BaseBot.invoke()` (returns one
     `AIMessage`).
`ruff check` could not be run — not installed in the shared `.venv` in
this environment (dev extra not synced); `black --check` is clean.
