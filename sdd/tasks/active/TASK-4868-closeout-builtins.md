# TASK-4868: Builtin hook actions: jira.transition, telegram.send, push.send, webhook.post

**Feature**: FEAT-764 — `/sdd-done` closeout hooks
**Spec**: `sdd/specs/sdd-done-closeout-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4867
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. Absorbs today's `/sdd-done` Step 10 Jira logic
(`.claude/commands/sdd-done.md:765-866`) into `jira.transition` (spec G6, AC8), and adds
`telegram.send`, `push.send` (ntfy, gotify) and `webhook.post`. AC9: secrets only from env;
missing secret → `skipped`, never `fail`.

---

## Scope

- Create `scripts/sdd/closeout_builtins.py` exporting `BUILTINS: dict[str, BuiltinFn]` and
  `run_builtin(hook, ctx, artifact_dir) -> HookResult`.
- `jira.transition`: find the key in the spec (`**Jira**: [KEY]` regex, same as sdd-done.md:772,
  then frontmatter `jira:`); none → `skipped` "No Jira key in spec". Env `JIRA_INSTANCE`,
  `JIRA_USERNAME`, `JIRA_API_TOKEN` (try `navconfig` import lazily; fall back to `os.environ`).
  GET `/rest/api/3/issue/<KEY>/transitions`, pick the one whose `to.name`/`name` equals
  `with.status` (default `"Done"`, case-insensitive), POST it, then POST a comment with
  `pr_url`/`merge_sha`. No matching transition → `fail` listing available names.
- `telegram.send`: `https://api.telegram.org/bot<token>/sendMessage`, token from
  `with.token_env` (default `SDD_TELEGRAM_BOT_TOKEN`), chat from `with.chat_id_env`
  (default `SDD_TELEGRAM_CHAT_ID`), text = `with.template` formatted with the context.
- `push.send`: provider registry `{"ntfy": _push_ntfy, "gotify": _push_gotify}`.
  ntfy → POST `${url}/${topic}` (url from `with.url_env` default `SDD_NTFY_URL`, topic from
  `with.topic_env` default `SDD_NTFY_TOPIC`, optional `Authorization: Bearer $SDD_NTFY_TOKEN`),
  headers `Title`, `Priority`. gotify → POST `${url}/message` (url `with.url_env` default
  `SDD_GOTIFY_URL`), header `X-Gotify-Key: $SDD_GOTIFY_TOKEN`, JSON `{title, message, priority}`.
- `webhook.post`: POST `HookContext.model_dump()` as JSON to `os.environ[with.url_env]`;
  optional `with.headers_env` names an env var holding a JSON object of headers.
- HTTP via `aiohttp` inside `asyncio.run(...)`, timeout = `hook.timeout_s`; non-2xx → `fail`.
- Template formatting: `str.format_map` over context dict with a defaulting mapping (missing key → "").

**NOT in scope**: dispatcher, CLI, config parsing (TASK-4867/4869), removing Step 10 from the twins (TASK-4870).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/closeout_builtins.py` | CREATE | BUILTINS registry + four actions over aiohttp |
| `tests/sdd_scripts/test_closeout_builtins.py` | CREATE | Unit tests (HTTP mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                            # core dependency (packages/ai-parrot/pyproject.toml)
from scripts.sdd.closeout_hooks_config import HookContext, HookKind, HookResult, HookSpec, PUSH_PROVIDERS   # created by TASK-4867
```

### Existing Signatures to Use
```python
# .claude/commands/sdd-done.md:772 — Jira key regex to reuse
#   grep -oP '(?<=\*\*Jira\*\*: \[)[A-Z]+-\d+' sdd/specs/<feature>.spec.md
# .claude/commands/sdd-done.md:786 — creds come from navconfig/env JIRA_* (JIRA_INSTANCE, JIRA_API_TOKEN)
```

### Does NOT Exist
- ~~`parrot.integrations.telegram` for scripts~~ — do not import parrot integrations (wrong layer, spec §6).
- ~~`requests`~~ / ~~`httpx`~~ — forbidden (ruff TID251); use aiohttp.
- ~~an FCM/APNs provider~~ — v1 ships only `ntfy` and `gotify` (spec §8 Q2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/closeout_builtins.py",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_closeout_builtins.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Tests mock HTTP by monkeypatching a module-level `_post_json`/`_request` coroutine helper
  (define one helper `async def _request(method, url, *, headers=None, json=None, data=None, timeout) -> tuple[int, Any]`)
  — *because* it keeps aiohttp out of the tests and gives one seam for all four actions.
- Never log tokens; summaries must not contain secret values.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton below — *why*: the dispatcher calls `run_builtin` only.
2. Implement `_request` with aiohttp — *why*: single HTTP seam for tests.
3. Implement the four actions and the two push providers.
4. Write tests mocking `_request`.

### `scripts/sdd/closeout_builtins.py` (CREATE)
```python
"""Builtin closeout-hook actions for /sdd-done (FEAT-764)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from scripts.sdd.closeout_hooks_config import HookContext, HookKind, HookResult, HookSpec, PUSH_PROVIDERS

BuiltinFn = Callable[[HookSpec, HookContext, Path], HookResult]
_JIRA_KEY_RE = re.compile(r"\*\*Jira\*\*: \[([A-Z]+-\d+)")


class _Defaulting(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _render(template: str, ctx: HookContext) -> str:
    """Format ``template`` with context fields; unknown placeholders render empty."""
    return template.format_map(_Defaulting(ctx.model_dump()))


async def _request(method: str, url: str, *, headers: dict[str, str] | None = None,
                   json_body: Any = None, data: str | None = None, timeout: int = 60) -> tuple[int, Any]:
    """Single HTTP seam (patched in tests). Returns (status, parsed body or text)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.request(method, url, headers=headers, json=json_body, data=data) as resp:
            # FILL IN: parse JSON when content-type is json, else text
            raise NotImplementedError


def _result(hook: HookSpec, status: str, summary: str, started: float) -> HookResult:
    return HookResult(name=hook.name, kind=HookKind.BUILTIN, status=status, blocking=hook.blocking,
                      duration_s=round(time.monotonic() - started, 3), summary=summary)


def jira_transition(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Transition the spec-linked Jira ticket; skipped when the spec has none."""
    # FILL IN: key lookup (regex, then frontmatter `jira:`), creds, transitions GET/POST, comment — bounded by AC8/AC9
    raise NotImplementedError


def telegram_send(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Send a Telegram message via the Bot API."""
    # FILL IN — bounded by AC9
    raise NotImplementedError


def _push_ntfy(hook: HookSpec, ctx: HookContext, title: str, message: str, priority: str) -> tuple[str, str]:
    # FILL IN: returns (status, summary)
    raise NotImplementedError


def _push_gotify(hook: HookSpec, ctx: HookContext, title: str, message: str, priority: str) -> tuple[str, str]:
    # FILL IN: returns (status, summary)
    raise NotImplementedError


_PUSH: dict[str, Callable[..., tuple[str, str]]] = {"ntfy": _push_ntfy, "gotify": _push_gotify}
assert set(_PUSH) == set(PUSH_PROVIDERS)


def push_send(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Send a push notification through the configured provider (default ntfy)."""
    # FILL IN: dispatch on hook.with_.get("provider", "ntfy"); title/template/priority defaults
    raise NotImplementedError


def webhook_post(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """POST the JSON context to a URL taken from an env var."""
    # FILL IN — bounded by AC9
    raise NotImplementedError


BUILTINS: dict[str, BuiltinFn] = {
    "jira.transition": jira_transition,
    "telegram.send": telegram_send,
    "push.send": push_send,
    "webhook.post": webhook_post,
}


def run_builtin(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
    """Run ``hook.builtin``; any unexpected exception becomes a ``fail`` result, never a crash."""
    # FILL IN: lookup + try/except Exception -> fail with type(exc).__name__ (no secrets)
    raise NotImplementedError
```
**Why**: the dispatcher depends only on `run_builtin` + `BUILTINS`; providers sit in a dict so a
later FCM provider is one entry plus one `PUSH_PROVIDERS` member.

### FILL IN checklist
- [ ] `_request` body parsing
- [ ] `jira_transition` — AC8 skip path, transition match, comment
- [ ] `telegram_send`, `webhook_post`, `push_send`, `_push_ntfy`, `_push_gotify` — missing env → skipped (AC9)
- [ ] `run_builtin` exception guard

---

## Acceptance Criteria

- [ ] Spec without Jira key → `skipped` with "No Jira key in spec" (AC8).
- [ ] Missing secret env for any action → `skipped` (AC9).
- [ ] ntfy and gotify send the documented URL/headers/body.
- [ ] No `requests`/`httpx`; `ruff check scripts/sdd/closeout_builtins.py` clean (AC11).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_closeout_builtins.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_closeout_builtins.py — patch scripts.sdd.closeout_builtins._request
def test_jira_no_key_skipped(tmp_path): ...
def test_jira_transition_matches_status_and_comments(tmp_path, monkeypatch): ...
def test_jira_no_matching_transition_fails(tmp_path, monkeypatch): ...
def test_telegram_missing_token_skipped(monkeypatch): ...
def test_telegram_payload(monkeypatch): ...
def test_push_ntfy_request_shape(monkeypatch): ...
def test_push_gotify_request_shape(monkeypatch): ...
def test_webhook_posts_context(monkeypatch): ...
def test_non_2xx_is_fail(monkeypatch): ...
def test_run_builtin_exception_becomes_fail(monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-done-closeout-hooks --feature-id FEAT-764`), never on `dev`.
2. Read the spec `sdd/specs/sdd-done-closeout-hooks.spec.md` (§2 Overview, Data Models, exit-code table).
3. Every `Depends-on` task must be `done` in `sdd/tasks/index/sdd-done-closeout-hooks.json`.
4. Verify the Codebase Contract before writing code; fix stale entries first.
5. Mark `in-progress` in the index, implement from the Blueprint, complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH=.` from the worktree root; `ruff check` the new files.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh <TASK-ID> sdd-done-closeout-hooks verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
