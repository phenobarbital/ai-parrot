# TASK-2893: Wire the detection fallback into bookstore's LLM resolution

**Feature**: FEAT-531 — Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it
**Spec**: `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2892
**Assigned-to**: unassigned

---

## Context

This is Module 2 of FEAT-531 (spec §3). `bookstore/_llm.py::resolve_adapter` is the single
shared LLM-resolution seam for the `bookstore` CLI and its MCP server. Today, when
`PARROT_BOOKSTORE_LLM` is unset, it logs a warning and returns `(None, None, None)`
unconditionally — the bookstore then runs in degraded (BM25/deterministic carding) mode. This
task adds a fallback to the Module 1 detection helper before that degraded return, with a
visible warning and an opt-out.

---

## Scope

- In `resolve_adapter()`, when `spec` (from `llm_spec` or `os.environ.get(ENV_LLM)`) is falsy:
  - First check the opt-out: if `os.environ.get("PARROT_NO_AUTO_LLM")` is truthy, keep the
    existing behavior unchanged (log the existing warning, return `(None, None, None)`) —
    do NOT call the detection helper.
  - Otherwise, call `detect_coding_agent_llm()`. If it returns a spec string, use it exactly
    as if the user had supplied it via `PARROT_BOOKSTORE_LLM` (i.e. proceed into the existing
    `try:` block that builds the adapter from `spec`), and log a `logger.warning` naming the
    auto-selected spec and that `PARROT_BOOKSTORE_LLM` overrides it.
  - If detection also returns `None`, fall through to the existing degraded-mode
    warning/return, unchanged.
- Write unit tests for: detection-hit, opt-out set, explicit-config-wins (regression), and
  detection-miss (unchanged degraded path).

**NOT in scope**:
- Any change to `wiki/cli.py` — that is TASK-2894.
- Any change to `parrot/clients/detection.py` — that is TASK-2892 (depend on it, don't modify
  it).
- Changing `_NullAdapter`, `Bookstore.__init__`, or any other part of `library.py`.
- The `PARROT_BOOKSTORE_LLM_LIGHT` (`lightweight_model`) parameter — this task only changes
  the heavy-model fallback; `lightweight_model` continues to pass through unchanged (`None`
  when unset, exactly as today).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py` | MODIFY | Add detection fallback branch to `resolve_adapter()` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_llm.py` | CREATE | Unit tests for the new fallback behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.detection import detect_coding_agent_llm  # verified: TASK-2892 creates packages/ai-parrot/src/parrot/clients/detection.py
```
Import this **lazily**, inside `resolve_adapter()`, alongside the other lazy imports already
in that function (`from parrot.clients.factory import LLMFactory` etc., under the
`contextlib.redirect_stdout(sys.stderr)` block) — do not add it as a module-level import,
to preserve this file's existing "safe to import from the MCP server" stdout-purity
constraint (module docstring, lines 16-18).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py
ENV_LLM = "PARROT_BOOKSTORE_LLM"        # line 29
ENV_LLM_LIGHT = "PARROT_BOOKSTORE_LLM_LIGHT"  # line 30

def resolve_adapter(
    llm_spec: Optional[str] = None,
    lightweight_model: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str], Optional[Any]]:
    # line 35-75
    spec = llm_spec or os.environ.get(ENV_LLM)
    light = lightweight_model or os.environ.get(ENV_LLM_LIGHT)
    if not spec:                                    # line 54 — THIS branch gets the new fallback
        logger.warning(
            "No LLM configured (%s unset) — bookstore runs BM25/catalog only",
            ENV_LLM,
        )
        return None, None, None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.clients.factory import LLMFactory
            from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

            _, model_id = LLMFactory.parse_llm_string(spec)
            client = LLMFactory.create(spec)
            adapter = PageIndexLLMAdapter(client, model=model_id)
    except Exception as exc:
        logger.warning(...)
        return None, None, None
    return adapter, light, client
```

### Does NOT Exist
- ~~A `PARROT_NO_AUTO_LLM` check anywhere in this file today~~ — does not exist yet; this
  task introduces the first read of it (via plain `os.environ.get`, matching this file's
  existing convention — this file does NOT use navconfig/`_env_setting`, unlike `wiki/cli.py`).
- ~~Any existing default-provider fallback in this file~~ — confirmed absent (spec §6 "Does
  NOT Exist"). Do not frame this change as "restoring" anything.

---

## Implementation Notes

### Pattern to Follow
```python
def resolve_adapter(
    llm_spec: Optional[str] = None,
    lightweight_model: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str], Optional[Any]]:
    spec = llm_spec or os.environ.get(ENV_LLM)
    light = lightweight_model or os.environ.get(ENV_LLM_LIGHT)
    if not spec:
        if not os.environ.get("PARROT_NO_AUTO_LLM"):
            from parrot.clients.detection import detect_coding_agent_llm

            detected = detect_coding_agent_llm()
            if detected:
                logger.warning(
                    "No LLM configured (%s unset) — auto-selected %r because a coding-agent "
                    "CLI session was detected. Set %s to override, or PARROT_NO_AUTO_LLM=1 "
                    "to disable auto-detection.",
                    ENV_LLM,
                    detected,
                    ENV_LLM,
                )
                spec = detected
        if not spec:
            logger.warning(
                "No LLM configured (%s unset) — bookstore runs BM25/catalog only",
                ENV_LLM,
            )
            return None, None, None
    try:
        ...  # unchanged
```

### Key Constraints
- Do not change the function's public signature or return type.
- Keep the `contextlib.redirect_stdout(sys.stderr)` guard around the existing heavy imports
  (`LLMFactory`, `PageIndexLLMAdapter`) exactly as today; the new `detect_coding_agent_llm`
  import is cheap (no heavy provider SDK import — see TASK-2892) but keep it under the same
  lazy-import discipline as the rest of the function for consistency.
- Preserve the outer `except Exception as exc:` degrade-never-crash behavior — a failure while
  building the adapter from an *auto-detected* spec must degrade exactly like a failure
  building it from an *explicit* spec today (log + return `None, None, None`), not raise.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/detection.py` (TASK-2892) — the function this task
  calls.
- `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:38,62` — an existing caller of
  `resolve_adapter()`, useful for understanding how `llm_spec` is threaded from a CLI flag.

---

## Acceptance Criteria

- [ ] When `PARROT_BOOKSTORE_LLM` is unset, `PARROT_NO_AUTO_LLM` is unset, and
      `detect_coding_agent_llm()` returns a spec, `resolve_adapter()` builds and returns a
      real adapter (not `None, None, None`) from that spec.
- [ ] A `WARNING`-level log line is emitted naming the auto-selected spec and
      `PARROT_BOOKSTORE_LLM` as the override variable.
- [ ] When `PARROT_NO_AUTO_LLM` is set (any truthy value) and `PARROT_BOOKSTORE_LLM` is
      unset, `resolve_adapter()` returns `(None, None, None)` and `detect_coding_agent_llm`
      is never called (assert via `unittest.mock.patch` / monkeypatch spy).
- [ ] When `PARROT_BOOKSTORE_LLM` is set, `detect_coding_agent_llm` is never called
      (regression guard for explicit-config-always-wins).
- [ ] When detection returns `None` (neither CLI available), behavior is byte-for-byte
      identical to today: the existing degraded-mode warning is logged and
      `(None, None, None)` is returned.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/bookstore/test_llm.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
- [ ] `from parrot.knowledge.bookstore._llm import resolve_adapter` still imports cleanly with
      zero required env vars set (stdout purity / MCP-server-safe import, per the module's
      existing docstring constraint).

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/bookstore/test_llm.py
import logging
from unittest.mock import patch

import pytest

from parrot.knowledge.bookstore import _llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("PARROT_BOOKSTORE_LLM", raising=False)
    monkeypatch.delenv("PARROT_BOOKSTORE_LLM_LIGHT", raising=False)
    monkeypatch.delenv("PARROT_NO_AUTO_LLM", raising=False)


def test_uses_detection_when_unset(monkeypatch):
    with patch(
        "parrot.clients.detection.detect_coding_agent_llm",
        return_value="claude-code:claude-haiku-4-5-20251001",
    ):
        with patch("parrot.clients.factory.LLMFactory.create") as mock_create, \
             patch("parrot.clients.factory.LLMFactory.parse_llm_string", return_value=("claude-code", "claude-haiku-4-5-20251001")):
            adapter, light, client = _llm.resolve_adapter()
    assert adapter is not None


def test_respects_opt_out(monkeypatch, caplog):
    monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
    with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
        adapter, light, client = _llm.resolve_adapter()
    mock_detect.assert_not_called()
    assert (adapter, light, client) == (None, None, None)


def test_explicit_config_wins(monkeypatch):
    monkeypatch.setenv("PARROT_BOOKSTORE_LLM", "anthropic:claude-sonnet-5")
    with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
        with patch("parrot.clients.factory.LLMFactory.create"), \
             patch("parrot.clients.factory.LLMFactory.parse_llm_string", return_value=("anthropic", "claude-sonnet-5")):
            _llm.resolve_adapter()
    mock_detect.assert_not_called()


def test_degrades_when_detection_misses(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    with patch("parrot.clients.detection.detect_coding_agent_llm", return_value=None):
        adapter, light, client = _llm.resolve_adapter()
    assert (adapter, light, client) == (None, None, None)
    assert "bookstore runs BM25/catalog only" in caplog.text
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md` for full context.
2. **Check dependencies** — verify TASK-2892 is in `sdd/tasks/completed/` before starting.
3. **Verify the Codebase Contract** — `read` `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
   in full to confirm line numbers/behavior are still accurate before editing.
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2893-bookstore-fallback.md`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (session_017szabNhV61kLcqqqh7gZQF)
**Date**: 2026-09-06
**Notes**: Added the `PARROT_NO_AUTO_LLM`-gated `detect_coding_agent_llm()`
fallback branch to `resolve_adapter()` in `bookstore/_llm.py` exactly per the
Implementation Notes pattern, with the lazy import kept inside the function.
Added `packages/ai-parrot/tests/knowledge/bookstore/test_llm.py` with the
full test scaffold from the Test Specification. All 4 new tests plus the
5 pre-existing TASK-2892 tests pass (9/9); `ruff check` clean; verified the
module still imports with zero stdout output (MCP-server stdout-purity
constraint preserved).

**Deviations from spec**: none
