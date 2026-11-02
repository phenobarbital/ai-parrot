# TASK-4993: CodexUsageCodec and codex dispatcher usage emission

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4984, TASK-4986, TASK-4989
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, G6, AC-8, design review S7. The codex seat is 60% of attempts and
0.0006% of recorded tokens, because `dispatchers/codex.py` streams `codex exec --json`
and never reads usage (there is no `input_tokens` anywhere in the file). This task adds a
dedicated codec (**not** in `_shared.py`, which twelve siblings import, and **no** import of
`ai-parrot-client-openai`) and emits one `AfterClientCallEvent` per dispatch, mirroring
`claude.py::_emit_usage_event`.

> **Open item S3 remainder (spec §8)**: confirm the stdout event's token field names from
> one captured `codex exec --json` run (codex-cli 0.164.0) before freezing the fixtures.
> If you cannot capture a run, write the fixtures from the codex-cli source/docs and say so
> in the Completion Note.

---

## Scope

- Create `dispatchers/codex_usage.py` with `CodexUsageCodec`: `observe(event)` folds one stream event; `result()` returns one aggregated `CompletionUsage` or `None`. The last terminal observation wins; repeated identical terminal events are not double-counted; nested `usage` objects are supported. It maps `cached_input_tokens`→`cache_read_tokens` and `reasoning_output_tokens`.
- The codec also captures `auth_mode` / `plan_type` when present, and exposes `pricing_policy() -> Optional[str]` (`"subscription"` for a ChatGPT-plan login, `"billed"` for an API key).
- In `CodexCodeDispatcher`: add `set_event_registry_resolver` / `event_registry_resolver` (same shape as `claude.py:183-208`). Feed each parsed event to a per-dispatch codec inside `_stream_stdout_events`. After the process ends (success **and** failure paths), emit one `AfterClientCallEvent` (`client_name="codex"`, counters, `source_cost_usd` if reported, `pricing_policy`), inside `usage_attribution(run_id, seat=node_id)`.
- Captured fixtures under `packages/ai-parrot/tests/fixtures/codex_usage/`: terminal, nested, missing and repeated.
- Tests.

**NOT in scope**: the adversarial-review command path (`_build_adversarial_review_command`); any change to `_shared.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex_usage.py` | CREATE | Codec |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | Resolver + codec feed + emit |
| `packages/ai-parrot/tests/fixtures/codex_usage/terminal.jsonl` | CREATE | Fixture |
| `packages/ai-parrot/tests/fixtures/codex_usage/nested.jsonl` | CREATE | Fixture |
| `packages/ai-parrot/tests/fixtures/codex_usage/missing.jsonl` | CREATE | Fixture |
| `packages/ai-parrot/tests/fixtures/codex_usage/repeated.jsonl` | CREATE | Fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_usage_codec.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage                                  # basic.py:48 (counters from TASK-4984)
from parrot.core.events.lifecycle import TraceContext                            # claude.py:46
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent      # claude.py:47
from parrot.observability.context import usage_attribution                       # claude.py:67
```

### Existing Signatures to Use
```python
# dispatchers/codex.py — imports asyncio, codecs, json, logging, os, tempfile, time; NO observability/events imports today
class CodexCodeDispatcher:   # verify name: grep -n '^class ' codex.py
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds, codex_bin="codex") -> None   # :238
    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None) -> T  # :255
    async def _stream_stdout_events(self, stdout, *, stream_key, run_id, node_id) -> str   # :636
            if isinstance(event, dict):
                last_error = _codex_error_message(event) or last_error
            await self._publish_codex_event(stream_key, event, run_id, node_id)   # :668 (1 occurrence) — anchor
# dispatchers/claude.py:183-208 — set_event_registry_resolver / event_registry_resolver property (copy the shape)
# dispatchers/claude.py:977-1029 — _emit_usage_event (copy the emit + forward_to_global + fail-open shape)
```

### Does NOT Exist
- ~~`dispatchers/codex.py` usage extraction~~ — nothing today; this task adds it
- ~~`CodexCodeDispatcher.set_event_registry_resolver`~~ — this task adds it
- ~~usage parsing in `dispatchers/_shared.py`~~ — forbidden (S7)
- ~~any import from `parrot.clients.openai` / ai-parrot-client-openai~~ — forbidden (S7)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex_usage.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/fixtures/codex_usage/terminal.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/fixtures/codex_usage/nested.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/fixtures/codex_usage/missing.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/fixtures/codex_usage/repeated.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_codex_usage_codec.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher.dispatch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._stream_stdout_events",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._emit_usage_event",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#CompletionUsage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_stream_stdout_events` returns a `str` today, and its callers depend on that. Pass the codec in as a new keyword argument (`codec: Optional[CodexUsageCodec] = None`) instead of changing the return type.
- Codex attempts are routinely abandoned (`issue:c4d0e7a028ca`). **Emit on the failure paths too**: their cost is real (spec §7).
- `usage_reported` honesty: when the codec saw no usage, emit with `input_tokens=None, output_tokens=None`. Never fabricate zeros.

---

## Implementation Blueprint

### Steps (in order)
1. Capture or author the fixtures, because the codec is written against them.
2. Write the codec + unit tests.
3. Add the resolver API to the dispatcher.
4. Thread a per-dispatch codec through `_stream_stdout_events`.
5. Add `_emit_usage_event` and call it from a `finally`-style point covering success and failure (FILL IN placement).
6. Dispatcher-level test with a fake process stdout.

### `codex_usage.py` (CREATE)
```python
"""CodexUsageCodec — decode `codex exec --json` usage events (FEAT-783 M4).

Deliberately NOT in _shared.py: twelve sibling dispatchers import that module, and
dev_loop must not import ai-parrot-client-openai merely to parse CLI output (S7).
"""
from __future__ import annotations

from typing import Any, Optional

from parrot.models.basic import CompletionUsage


class CodexUsageCodec:
    """Fold a codex JSONL event stream into exactly one terminal usage observation."""

    def __init__(self) -> None:
        self._usage: Optional[dict[str, Any]] = None
        self._auth_mode: Optional[str] = None
        self._plan_type: Optional[str] = None
        self._source_cost_usd: Optional[float] = None

    def observe(self, event: dict[str, Any]) -> None:
        """Fold one stream event; last terminal observation wins."""
        # FILL IN: locate a usage dict at event["usage"] or nested (e.g. event["msg"]["usage"] /
        # event["info"]["total_token_usage"] — match the fixtures); record auth_mode/plan_type when present;
        # turn cost (e.g. cost_microusd / 1e6) -> _source_cost_usd — bounded by fixture cases
        raise NotImplementedError

    def result(self) -> Optional[CompletionUsage]:
        """The single aggregated usage for the turn, or None if never reported."""
        if self._usage is None:
            return None
        return CompletionUsage.model_validate(self._usage)

    @property
    def source_cost_usd(self) -> Optional[float]:
        """Provider-reported cost, reconciliation only (AC-5)."""
        return self._source_cost_usd

    def pricing_policy(self) -> Optional[str]:
        """'subscription' for a ChatGPT-plan login, 'billed' for an API key, None if unknown (U4)."""
        # FILL IN: derive from _auth_mode/_plan_type — bounded by U4
        raise NotImplementedError
```

### `codex.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            await self._publish_codex_event(stream_key, event, run_id, node_id)' codex.py), :668
# BEFORE — insert above it:
            if codec is not None and isinstance(event, dict):
                try:
                    codec.observe(event)
                except Exception:  # noqa: BLE001 — telemetry must never break dispatch
                    self.logger.debug("codex usage codec failed on an event", exc_info=True)
```
```python
# FILL IN: add `codec: "Optional[CodexUsageCodec]" = None` to _stream_stdout_events' keyword args;
# create `codec = CodexUsageCodec()` in dispatch() and pass it at the _stream_stdout_events call site
# (grep -n '_stream_stdout_events(' codex.py); add `self._event_registry_resolver = None` in __init__;
# add set_event_registry_resolver/event_registry_resolver copied from claude.py:183-208;
# add `async def _emit_usage_event(self, codec, *, run_id, node_id, profile, duration_ms)` copied from
# claude.py:977-1029 with client_name="codex", source_name="codex", counters from codec.result(),
# source_cost_usd=codec.source_cost_usd, pricing_policy=codec.pricing_policy(); call it once on every
# exit path that ran the process (success, non-zero exit, timeout) — bounded by AC-8 and "cost is real"
```

### `test_codex_usage_codec.py` (CREATE)
```python
"""FEAT-783 TASK-4993 — codex usage codec (AC-8)."""
import json
from pathlib import Path

from parrot.flows.dev_loop.dispatchers.codex_usage import CodexUsageCodec

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "codex_usage"


def _feed(name: str) -> CodexUsageCodec:
    codec = CodexUsageCodec()
    for line in (FIXTURES / name).read_text().splitlines():
        if line.strip():
            codec.observe(json.loads(line))
    return codec


def test_terminal_usage_is_reported() -> None:
    # FILL IN: non-zero input/output; cache_read and reasoning mapped (AC-8)
    ...


def test_nested_usage_is_found() -> None:
    # FILL IN
    ...


def test_missing_usage_returns_none() -> None:
    assert _feed("missing.jsonl").result() is None


def test_repeated_terminal_not_double_counted() -> None:
    # FILL IN
    ...


async def test_dispatcher_emits_one_event_on_failure_path() -> None:
    # FILL IN: fake process/stdout yielding terminal.jsonl, non-zero exit -> exactly one AfterClientCallEvent
    # captured via a resolver returning a fake registry
    ...
```

### FILL IN checklist
- [ ] Fixture field names (S3 remainder)
- [ ] `observe` / `pricing_policy`
- [ ] Dispatcher wiring + emit on every exit path
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] AC-8: the codex seat reports non-zero provider tokens for a fixture-replayed attempt, and for one real attempt (evidence in the Completion Note).
- [ ] One event per dispatch; no double count on repeated terminal events; the failure path also emits.
- [ ] `_shared.py` is untouched; no openai-client import.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_usage_codec.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Seven files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note

- Task: TASK-4993
- Feature: unified-usage
- Implementation SHA: 4bbbd6d0666db6d0adbe4c43d11c5a43ad0c514a
- Closed at (UTC): 2026-10-31T01:01:47+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 113.1s · Tokens: n/a |
