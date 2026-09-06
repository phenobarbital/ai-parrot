# TASK-2892: Add the shared coding-agent LLM detection helper

**Feature**: FEAT-531 — Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it
**Spec**: `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is Module 1 of FEAT-531 (spec §3). It is the single foundation both other
implementation tasks (TASK-2893 bookstore, TASK-2894 wikitoolkit) import from, so it must
land first. It implements the "safe-execution detection" the feature request asked for:
a cheap, side-effect-free check for whether a Claude Code or Codex CLI session looks usable
on this machine, without ever spawning a subprocess, making a network call, or importing a
provider SDK.

---

## Scope

- Create `parrot/clients/detection.py` with a single public function
  `detect_coding_agent_llm() -> Optional[str]`.
- Logic, in order:
  1. Call `LLMFactory.list_providers()` (read-only entry-point discovery — no client is
     instantiated).
  2. If `"claude-code"` is a key in the result **and** `shutil.which("claude")` finds a
     binary, return `"claude-code:claude-haiku-4-5-20251001"`.
  3. Else if `"codex-code"` is a key in the result **and** `shutil.which("codex")` finds a
     binary, return `"codex-code:gpt-5.1-codex"`.
  4. Else return `None`.
- Write unit tests covering all four branches (see Test Specification).

**NOT in scope**:
- Any change to `bookstore/_llm.py` or `wiki/cli.py` — those are TASK-2893 and TASK-2894.
- Any change to `ClaudeAgentClient`, `OpenAICodexClient`, or `LLMFactory` itself.
- Reading or checking `PARROT_NO_AUTO_LLM` — that opt-out is checked by each *caller* using
  its own existing env-reading convention (spec §2 Overview), not inside this helper.
- Importing `claude_agent_sdk` or `openai_codex` anywhere in this module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/detection.py` | CREATE | `detect_coding_agent_llm()` |
| `packages/ai-parrot/tests/clients/test_detection.py` | CREATE | Unit tests for all branches |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.factory import LLMFactory  # verified: packages/ai-parrot/src/parrot/clients/factory.py:163
import shutil  # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def list_providers() -> Dict[str, str]:  # line 214-221
        """Return every discovered provider key mapped to the installed
        satellite distribution name that supplied it. Empty with zero
        ai-parrot-client-* satellites installed."""
```
Calling `LLMFactory.list_providers()` triggers `_discover()` internally (lazy, memoized after
first call) — this reads `importlib.metadata.entry_points(group="parrot.clients")`. It does
**not** import any provider module; it only reads entry-point metadata and lazily resolves the
loader (`EntryPoint.load`) which, for these specific two providers, imports
`parrot.clients.anthropic` / `parrot.clients.openai` (the client *package*, not the SDK) — this
is acceptable and unavoidable (it's how `list_providers()` already works for every other
provider in this codebase); it does NOT import `claude_agent_sdk` or `openai_codex` themselves.

### Does NOT Exist
- ~~`LLMFactory.is_provider_available()`~~ — no such method; use `list_providers()` and check
  membership (`"claude-code" in LLMFactory.list_providers()`).
- ~~`ClaudeAgentClient.cli_bin`~~ — does not exist as a class attribute (unlike
  `OpenAICodexClient.codex_bin`). Do not reference it.
- ~~A `parrot.clients.detection` module~~ — does not exist yet; this task creates it.

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/clients/detection.py
"""Safe, non-invasive detection of a usable coding-agent CLI LLM.

Never imports a provider SDK, never spawns a subprocess, never makes a
network call — only entry-point discovery (LLMFactory.list_providers())
and shutil.which() on the CLI binary.
"""
from __future__ import annotations

import shutil
from typing import Optional

from parrot.clients.factory import LLMFactory

_CLAUDE_CODE_SPEC = "claude-code:claude-haiku-4-5-20251001"
_CODEX_CODE_SPEC = "codex-code:gpt-5.1-codex"


def detect_coding_agent_llm() -> Optional[str]:
    providers = LLMFactory.list_providers()
    if "claude-code" in providers and shutil.which("claude"):
        return _CLAUDE_CODE_SPEC
    if "codex-code" in providers and shutil.which("codex"):
        return _CODEX_CODE_SPEC
    return None
```

### Key Constraints
- Function must be synchronous (no `async def`) — every call site that will use it
  (`resolve_adapter`, `_resolve_model_id`, `_extract_into_graph`) is itself synchronous at the
  point where the env var is checked.
- No logging inside this module — callers own the visible-warning responsibility (spec §2,
  §7 Patterns to Follow), since the exact wording differs per call site (`logger.warning` in
  bookstore vs. `click.echo` in wikitoolkit).
- Module-level constants for the two spec strings (as in the pattern above) so TASK-2893 and
  TASK-2894's tests can assert against them without duplicating the literal strings.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/factory.py:214-221` — `list_providers()`, the
  discovery mechanism this task reads from.
- `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py:288-289` —
  `_default_model` / `_lightweight_model` precedent for the Haiku 4.5 model id used here.
- `packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py:81` —
  `default_model = "gpt-5.1-codex"`, used verbatim for the Codex spec.

---

## Acceptance Criteria

- [ ] `detect_coding_agent_llm()` returns `None` when `LLMFactory.list_providers()` is `{}`.
- [ ] Returns `"claude-code:claude-haiku-4-5-20251001"` when `"claude-code"` is a discovered
      provider and `shutil.which("claude")` is truthy.
- [ ] Returns `"codex-code:gpt-5.1-codex"` when only `"codex-code"` is discovered and
      `shutil.which("codex")` is truthy.
- [ ] Returns the Claude Code spec (not Codex) when both providers are discovered and both
      binaries are found.
- [ ] Returns `None` when a provider key is discovered but its CLI binary is NOT found
      (package installed but no usable CLI session).
- [ ] The module does not import `claude_agent_sdk` or `openai_codex` anywhere (verify with
      `grep -n "claude_agent_sdk\|openai_codex" packages/ai-parrot/src/parrot/clients/detection.py`
      — expect no matches).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/clients/test_detection.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/detection.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_detection.py
import pytest

from parrot.clients import detection


@pytest.fixture
def no_providers(monkeypatch):
    monkeypatch.setattr("parrot.clients.factory.LLMFactory.list_providers", lambda: {})


@pytest.fixture
def claude_code_only(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {"claude-code": "ai-parrot-client-anthropic"},
    )


@pytest.fixture
def codex_code_only(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {"codex-code": "ai-parrot-client-openai"},
    )


@pytest.fixture
def both_providers(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {
            "claude-code": "ai-parrot-client-anthropic",
            "codex-code": "ai-parrot-client-openai",
        },
    )


def test_returns_none_when_no_providers(no_providers, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    assert detection.detect_coding_agent_llm() is None


def test_returns_claude_code_spec(claude_code_only, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/claude" if b == "claude" else None)
    assert detection.detect_coding_agent_llm() == "claude-code:claude-haiku-4-5-20251001"


def test_returns_codex_spec(codex_code_only, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/codex" if b == "codex" else None)
    assert detection.detect_coding_agent_llm() == "codex-code:gpt-5.1-codex"


def test_claude_wins_when_both_available(both_providers, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/" + _bin)
    assert detection.detect_coding_agent_llm() == "claude-code:claude-haiku-4-5-20251001"


def test_registered_but_binary_missing(both_providers, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    assert detection.detect_coding_agent_llm() is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md` for full context.
2. **Check dependencies** — none; this task can start immediately.
3. **Verify the Codebase Contract** — before writing ANY code, `grep`/`read`
   `packages/ai-parrot/src/parrot/clients/factory.py` to confirm `list_providers()` still has
   the exact signature and behavior described above.
4. **Update status** in the per-spec index (`sdd/tasks/index/wikitoolkit-cli-llm-fallback.json`)
   → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2892-detection-helper.md`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (session_017szabNhV61kLcqqqh7gZQF)
**Date**: 2026-09-06
**Notes**: Implemented `detect_coding_agent_llm()` in
`packages/ai-parrot/src/parrot/clients/detection.py` exactly per the
Implementation Notes pattern in this task, plus the full test scaffold from
the Test Specification in `packages/ai-parrot/tests/clients/test_detection.py`.
All 5 unit tests pass; `ruff check` is clean; grep confirms no
`claude_agent_sdk`/`openai_codex` imports anywhere in the module.

**Deviations from spec**: none
