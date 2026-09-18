# TASK-3451: `CREW_AI_KEY` config entry + Google-LLM classifier helper

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 step 1 + §3 Module 1 (first half). Everything else in FEAT-575 depends on
two primitives that do not exist yet: the `CREW_AI_KEY` config entry, and a way to
tell whether an agent's raw LLM declaration resolves to a Google provider.

This task lands the config key, the new `credentials.py` module shell, and the two
read-only functions `get_crew_google_api_key()` / `is_google_llm()`. The injector
`apply_google_api_key()` is TASK-3452 — it needs `is_google_llm` to already exist.

---

## Scope

- Add `CREW_AI_KEY = config.get("CREW_AI_KEY")` to core `parrot/conf.py`, in the
  `## Google Services:` block next to `GOOGLE_API_KEY`.
- Create `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` with
  `GOOGLE_PROVIDER_KEYS`, `_CREDENTIAL_KWARGS`, the module-level warn-once flag
  `_warned_unset`, `get_crew_google_api_key()` and `is_google_llm()`.
- Write unit tests for both functions.

**NOT in scope**:
- `apply_google_api_key()` — TASK-3452 adds it to the same module.
- Any change to `crew.py`, `manager.py`, `handler.py` — TASK-3453..3456.
- Any change to `parrot/bots/abstract.py` or to any Google client. Spec §2 step 3:
  the key reaches the client through the EXISTING `LLMConfig.extra` path; no client
  or `AbstractBot` code changes anywhere in this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `CREW_AI_KEY` next to `GOOGLE_API_KEY` |
| `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` | CREATE | Module shell + `get_crew_google_api_key` + `is_google_llm` |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# inside packages/ai-parrot/src/parrot/conf.py — already present at the top of the file
from navconfig import config                       # verified: conf.py uses config.get(...) at conf.py:379

# inside packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py
# credentials.py sits at parrot/bots/flows/crew/ — the SAME package as crew.py,
# so these relative depths are copied verbatim from crew.py:53-59.
from navconfig.logging import logging               # verified: crew.py:53
from ....clients.factory import SUPPORTED_CLIENTS   # verified: crew.py:59
from ...abstract import _resolve_supported_client   # verified: crew.py:57 (same relative depth), abstract.py:178
from .... import conf                               # module object — see "Key Constraints" below
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/conf.py
## Google Services:                                  # line 378 — UNIQUE anchor
GOOGLE_API_KEY = config.get("GOOGLE_API_KEY")        # line 379 (DUPLICATED at line 424 — never anchor on it)

# packages/ai-parrot/src/parrot/bots/abstract.py
def _resolve_supported_client(entry):                # line 178
    """Resolve a SUPPORTED_CLIENTS entry into a client class.
    Returns entry() when entry is a callable that is not a type; else entry."""
    if entry is not None and callable(entry) and not isinstance(entry, type):
        return entry()                               # line 196
    return entry                                     # line 197

class AbstractBot(...):
    _default_llm: str = "google"                     # line 220

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: Dict[str, Any] = _LazyClientRegistry()   # line 100
# A dict subclass, LAZILY populated from the installed satellites'
# "parrot.clients" entry points on first read. Reading a key triggers
# discovery; a missing key is a normal KeyError / .get() -> None.

# packages/ai-parrot-client-google/pyproject.toml  [project.entry-points."parrot.clients"]
google       = "parrot.clients.google:GoogleGenAIClient"        # line 36
gemini-live  = "parrot.clients.google:GeminiLiveClient"         # line 37
google-compat = "parrot.clients.google:GeminiOpenAICompatClient" # line 38
```

### Does NOT Exist

- ~~`parrot.conf.CREW_AI_KEY`~~ — this task creates it. `CREW_AI_KEY` appears
  nowhere in the repo today.
- ~~`packages/ai-parrot-server/src/parrot/conf.py`~~ — the server has NO own
  `conf.py`. `manager.py:93`'s `from ..conf import ...` resolves to core
  `parrot/conf.py`. There is exactly one `conf.py` to edit.
- ~~`packages/ai-parrot/src/parrot/clients/google/`~~ (as source) — the Google
  clients live in the `ai-parrot-client-google` satellite. Core holds only a stale
  `__pycache__`. NEVER `from parrot.clients.google import ...` at module scope here.
- ~~`GeminiLiveClient.client_name == "gemini-live"`~~ — its class attr is
  `"google_live"`. Match via `SUPPORTED_CLIENTS` **keys**, never via `client_name`.
- ~~`parrot.clients.factory.get_google_clients()`~~ / any Google-specific helper on
  the factory — does not exist.
- ~~`AbstractBot.set_api_key()`~~ — no public credential setter exists, and this
  feature does not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#_resolve_supported_client",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#SUPPORTED_CLIENTS"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Read `CREW_AI_KEY` through the module object, at call time.**
  `from ....conf import CREW_AI_KEY` binds the value at import time, and the test
  fixture monkeypatches `parrot.conf.CREW_AI_KEY` — a bound name would not see it.
  Import the module (`from .... import conf`) and read `conf.CREW_AI_KEY` inside
  the function body. This is the single most likely way to get this task wrong.
- **Never log the key value** (AC7). The warning text mentions only the variable
  name.
- Warn exactly once per process (AC6) via a module-level `_warned_unset` flag.
  The test fixture resets it with `monkeypatch.setattr(..., "_warned_unset", False)`,
  so it MUST be a plain module-level `bool` named exactly `_warned_unset`.
- **Lazy provider lookup.** Resolve Google classes inside `is_google_llm` via
  `SUPPORTED_CLIENTS`; never import `parrot.clients.google` at module scope
  (FEAT-523 rule, see `crew.py:2125-2131`).
- A client **instance** is never Google here — a live instance already carries its
  own credentials, so there is nothing to inject (spec §2 step 2, AC2).
- Google-style docstrings + strict type hints; `logging.getLogger(__name__)`,
  never `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:53-59` — the exact relative
  import depths for this package.
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:227-233` — how `crew.py`
  already resolves a provider string through `SUPPORTED_CLIENTS`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `CREW_AI_KEY` to `conf.py` under the `## Google Services:` header — *why*: it is the only `conf.py` in the workspace, and the block already groups Google credentials.
2. Create `credentials.py` with the constants and the two functions — *why*: TASK-3452/3453/3455/3456 all import from this module, so its name and symbol names are fixed.
3. Write the tests, completing each `FILL IN` body — *why*: AC6/AC7 (warn-once, no key in logs) are only provable by test.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^## Google Services:' packages/ai-parrot/src/parrot/conf.py)
# AFTER — insert below `GOOGLE_API_KEY = config.get("GOOGLE_API_KEY")`, which is the
# line directly under the unique `## Google Services:` header (verified: conf.py:378-379).
# Do NOT anchor on the GOOGLE_API_KEY line itself: it occurs twice (conf.py:379 and :424).
# Default Google credential for crews built by the AgentCrew HTTP handlers
# (FEAT-575). Unset -> crew Google clients fall back to GOOGLE_API_KEY.
CREW_AI_KEY = config.get("CREW_AI_KEY")
```
**Why**: one line, in the block that already owns `GOOGLE_API_KEY`, so operators find
it where they look. `config.get` with no fallback yields `None` when unset, which is
exactly the sentinel `get_crew_google_api_key()` keys off.

### `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` (CREATE)
```python
"""Default Google credential for handler-built AgentCrews (``CREW_AI_KEY``).

FEAT-575. Crews created and executed through the AgentCrew HTTP handlers bill
their Google traffic to the process-wide ``GOOGLE_API_KEY``, which makes
crew-builder usage impossible to meter or rotate separately. This module
resolves an opt-in ``CREW_AI_KEY`` and classifies an agent's raw LLM
declaration so the crew build paths can inject it.

Nothing here mutates a ``CrewDefinition``, and the key value is never logged.
"""
from __future__ import annotations

from typing import Any, Optional

from navconfig.logging import logging  # verified: crew.py:53

from .... import conf

logger = logging.getLogger(__name__)

#: The three ``parrot.clients`` entry points of ``ai-parrot-client-google``.
#: verified: packages/ai-parrot-client-google/pyproject.toml:36-38
GOOGLE_PROVIDER_KEYS: frozenset[str] = frozenset({"google", "gemini-live", "google-compat"})

#: ``llm_kwargs`` keys that mean "this agent brought its own credential".
_CREDENTIAL_KWARGS: tuple[str, ...] = ("api_key", "credentials_file", "credentials")

#: Module-level warn-once latch (AC6). Reset by tests via monkeypatch.
_warned_unset: bool = False


def get_crew_google_api_key() -> Optional[str]:
    """Return the configured crew Google API key, or ``None``.

    Reads ``parrot.conf.CREW_AI_KEY`` through the module object (never a
    from-import) so a monkeypatched value is honoured. Logs a single warning
    per process when the key is unset; the key value is never logged.

    Returns:
        The configured ``CREW_AI_KEY``, or ``None`` when it is unset/empty.
    """
    global _warned_unset  # noqa: PLW0603 — deliberate process-wide warn-once latch
    key = getattr(conf, "CREW_AI_KEY", None)
    if key:
        return key
    if not _warned_unset:
        _warned_unset = True
        logger.warning("CREW_AI_KEY is not set; crew Google agents fall back to GOOGLE_API_KEY")
    return None


def _google_client_classes() -> tuple[type, ...]:
    """Resolve ``GOOGLE_PROVIDER_KEYS`` to client classes, tolerating absence.

    Returns:
        Every class the Google entry points resolve to. Empty when the
        ``ai-parrot-client-google`` satellite is not installed.
    """
    # FILL IN: import SUPPORTED_CLIENTS and _resolve_supported_client HERE (function
    # scope, not module scope), look each key up with .get(), pass it through
    # _resolve_supported_client, keep the results that are classes, and swallow any
    # Exception per key into a skip — bounded by "satellite missing / lookup error
    # -> False" (spec §3 M1) and the FEAT-523 no-provider-import-at-module-scope rule.
    raise NotImplementedError


def is_google_llm(llm: Any, default_provider: Optional[str] = "google") -> bool:
    """Report whether an agent's raw LLM declaration resolves to a Google provider.

    Args:
        llm: The agent's ``_llm_raw`` value — a ``provider[:model]`` string, an
            ``AbstractClient`` subclass, an ``AbstractClient`` instance, or ``None``.
        default_provider: The provider used when ``llm`` is ``None`` (the bot's
            ``_default_llm``, which is ``"google"``).

    Returns:
        ``True`` only for a Google provider string, a Google client **class**, or
        ``None`` with a Google ``default_provider``. A client *instance* and any
        other callable are always ``False`` — a live instance carries its own
        credentials.
    """
    if llm is None:
        return bool(default_provider) and default_provider.lower() in GOOGLE_PROVIDER_KEYS
    if isinstance(llm, str):
        # FILL IN: take the provider part of "provider[:model]", lower-case and
        # strip it, and test membership in GOOGLE_PROVIDER_KEYS — bounded by AC1
        # ("google", "google:gemini-3.5-flash", "GOOGLE", "gemini-live",
        # "google-compat:x" -> True) and by the fact that a bare "" is False.
        raise NotImplementedError
    if isinstance(llm, type):
        # FILL IN: return True when llm is a subclass of any class from
        # _google_client_classes() — bounded by AC1 (class-level declaration) and
        # by "satellite missing -> False".
        raise NotImplementedError
    return False
```
**Why this shape**: `GOOGLE_PROVIDER_KEYS`, `_CREDENTIAL_KWARGS`, `_warned_unset`,
`get_crew_google_api_key` and `is_google_llm` are the spec's fixed §2 New Public
Interfaces — TASK-3452/3453/3455/3456 import these exact names, and the test fixture
monkeypatches `_warned_unset` by name. The `from .... import conf` + call-time
`getattr` is load-bearing for the monkeypatch fixture. `_google_client_classes` is a
private helper so the lazy import lives in exactly one place. Do not change any
signature, module path, or symbol name.

### `packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py` (CREATE)
```python
"""Unit tests for the crew Google-credential helpers (FEAT-575, TASK-3451)."""
import logging

import pytest

from parrot.bots.flows.crew.credentials import (
    GOOGLE_PROVIDER_KEYS,
    get_crew_google_api_key,
    is_google_llm,
)


@pytest.fixture
def crew_key(monkeypatch):
    """Set CREW_AI_KEY and reset the warn-once latch for one test."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"


@pytest.fixture
def no_crew_key(monkeypatch):
    """Unset CREW_AI_KEY and reset the warn-once latch for one test."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", None, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)


def test_google_provider_keys_are_the_three_entry_points():
    assert GOOGLE_PROVIDER_KEYS == frozenset({"google", "gemini-live", "google-compat"})


@pytest.mark.parametrize(
    "value,expected",
    [
        ("google", True),
        ("google:gemini-3.5-flash", True),
        ("GOOGLE", True),
        ("gemini-live", True),
        ("google-compat:x", True),
        ("openai:gpt-5", False),
        ("anthropic", False),
    ],
)
def test_is_google_llm_strings(value, expected):
    assert is_google_llm(value) is expected


def test_is_google_llm_none_uses_default_provider():
    # FILL IN: None + "google" -> True; None + "openai" -> False — bounded by AC1
    raise NotImplementedError


def test_is_google_llm_instance_is_false():
    # FILL IN: build a trivial object standing in for a live client instance and
    # assert False — bounded by AC2 ("an AbstractClient instance is unchanged").
    raise NotImplementedError


def test_is_google_llm_class():
    # FILL IN: pytest.importorskip the google satellite, assert the resolved
    # GoogleGenAIClient class -> True and a non-Google client class -> False —
    # bounded by AC1 and by "satellite missing -> skip, never fail".
    raise NotImplementedError


def test_get_key_returns_configured_value(crew_key):
    assert get_crew_google_api_key() == crew_key


def test_get_key_warns_once_when_unset(no_crew_key, caplog):
    # FILL IN: with caplog at WARNING, call get_crew_google_api_key() TWICE; assert
    # both return None, exactly ONE warning record mentions CREW_AI_KEY, and no
    # record text contains a key value — bounded by AC6 and AC7.
    raise NotImplementedError
```
**Why**: the two fixtures are the spec §4 fixture contract and are reused verbatim by
TASK-3452. `test_get_key_warns_once_when_unset` is the only proof of AC6 + AC7.

### FILL IN checklist
- [ ] `credentials.py::_google_client_classes` — lazy `SUPPORTED_CLIENTS` lookup with per-key error tolerance; bounded by "satellite missing → False" + FEAT-523
- [ ] `credentials.py::is_google_llm` (str branch) — parse `provider[:model]`, case-insensitive; bounded by AC1
- [ ] `credentials.py::is_google_llm` (class branch) — `issubclass` against resolved Google classes; bounded by AC1
- [ ] `test_is_google_llm_none_uses_default_provider` — bounded by AC1
- [ ] `test_is_google_llm_instance_is_false` — bounded by AC2
- [ ] `test_is_google_llm_class` — `importorskip` the satellite; bounded by AC1
- [ ] `test_get_key_warns_once_when_unset` — two calls, one record, no key value; bounded by AC6/AC7

---

## Acceptance Criteria

- [ ] `parrot.conf.CREW_AI_KEY` exists and reads the `CREW_AI_KEY` env/navconfig entry.
- [ ] `get_crew_google_api_key()` returns the configured value, or `None` plus exactly one process-wide warning when unset (AC6).
- [ ] The warning never contains a key value (AC7).
- [ ] `is_google_llm` classifies strings, `None`+`default_provider`, and client classes per AC1; instances and other callables are `False` (AC2).
- [ ] `credentials.py` imports no provider module at module scope (`grep -n "clients.google" packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` finds nothing outside a function body).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py packages/ai-parrot/src/parrot/conf.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py -q`

---

## Test Specification

See the blueprint's test block — it IS the scaffold. Every `FILL IN` test body must
be completed and passing.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `conf.py:378-379`, `abstract.py:178`,
   and `crew.py:53-59` still read as quoted before writing code
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3451-crew-key-config-and-llm-classifier.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
