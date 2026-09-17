# TASK-3362: `remote_cli.py` + `@remote_aware` + proxied read/authoring/symbol/ledger commands (M6a)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3351, TASK-3359
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (proxy part), AC7–AC9, design research S10. When the
repository resolves a `remote`, the tool-backed CLI commands must call the
matching MCP tool through `RemoteWikiClient` and print the tool's **text**
result (the same text an agent receives), and they must do so **before** any
local store is opened or `is_built()` is checked (S10). Commands without a tool
are refused with a usage error. This task adds the helper module and the
`@remote_aware` decorator, then wires the 14 proxied commands and the
refusals. `build/upsert/ingest` pushes and `sync` are TASK-3363 (same files,
sequenced after this one).

---

## Scope

- `remote_cli.py`: `remote_or_none(path_)`, `remote_client(remote, *, by=None)`, `call_remote_text(remote, tool, arguments, *, by=None) -> str`, `call_remote(remote, tool, arguments, *, by=None) -> dict`, `refuse_remote(command, hint="")`, `remote_aware(*, proxied: bool, tool: str | None = None)` decorator (resolves remote once, stores in `click.get_current_context().obj`, rejects `--store/--backend` when remote, refuses non-proxied commands).
- Wire the remote branch at the top of: `query`, `page`, `related`, `status`, `remember`, `note`, `symbols lookup|outline|blast`, `ledger open|ready|claim|close|context` (mapping in spec M6).
- Apply `@remote_aware(proxied=False)` to: `ns list|add|remove`, `communities`, `export`, `link`, `memories`, `audit`, `ground`, `ingest-jira`, `sync obsidian`, `ledger acknowledge|blockers|export|sync|rebuild|ingest-sdd|compact|audit`.
- `status` in remote mode prints `Mode      : remote (<url>)` then the `wiki_status` text.
- Tests with a fake remote (reuse the fake-server pattern from `test_remote_client.py`).

**NOT in scope**: `build/upsert/ingest/sync push|pull` (TASK-3363), stdio pass-through (TASK-3364), `serve` (TASK-3361).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py` | CREATE | helpers + decorator |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | remote branches + refusals |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_remote.py` | CREATE | CLI tests with a fake remote |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click, functools
from click.testing import CliRunner                                              # tests
from parrot.knowledge.wiki.project import WikiRemoteConfig, WikiEffectiveConfig, resolve_remote, load_effective_config   # TASK-3351 / project.py
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError      # TASK-3359
from parrot.knowledge.wiki.cli import wiki, _run, _resolve_project_effective, _authoring_identity, _find_repo_root   # cli.py:1328, :494, :375, :3027, :333 — import INSIDE remote_cli functions (cli imports remote_cli; avoid a cycle at module import)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
path_option = click.option("--path", "path_", default=None, ...)   # :121 ; ns_option :125 ; def _store_options(func) :588 (adds --store/--backend → params store_opt/backend_opt)
def _find_repo_root(path: str | None) -> Path :333 · def _resolve_project(path) :350 · def _resolve_project_effective(path) -> tuple[Path, WikiEffectiveConfig] :375-389
def _require_built(root, config) :391 · def _resolve_read_store(path_, store_opt, backend_opt, ns_opt) :517 · def _run(coro) :494
def _authoring_identity(by: str | None) -> str :3027-3049
query(question, path_, top_k, budget, category, store_opt, backend_opt, ns_opt, as_table, show_body, as_json) :1824 — body starts `store = _resolve_read_store(...)` ; prints packed.text
page :1895 · related :1943 · status(path_, ns_opt, as_json) :2017 (prints "Env       : …") · def _structural_tool(name, path_) :2165 (uses _resolve_project + _require_built) · _echo_structural_result(result, as_json) :2185
symbols_lookup(path_, query, kind, language, path_prefix, limit, as_json) :2208 · symbols_outline :2230 · symbols_blast :2266
ledger_open(kind, severity, discovered_from, about, title, body) :2650 (LedgerService.from_root(), actor="agent:cli") · ledger_ready :2679 · ledger_claim(issue_id, actor) :2696 · ledger_acknowledge :2715 · ledger_close(issue_id, reason, actor) :2730 · ledger_context(file_paths, max_tokens) :2747 · blockers :2759 · export :2775 · sync :2787 · rebuild :2802 · ingest-sdd :2828 · compact :2848 · audit :2860
communities :2893 · export :2994 · remember(...) :3320 (options --title --link --rel --by --json …) · note :3460 · link :3531 · memories :3588 · audit :3618 · ground :3671 · sync obsidian :3869 · ingest-jira :4744 · ns_list :2405 · ns_add :2502 · ns_remove :2615
# MCP tool argument names (tools.py / structural/tools.py) — the proxy must send these exact keys:
wiki_query(question, budget_tokens, namespace, include_symbols) :211 · wiki_page(page_id, namespace) :249 · wiki_related(page_id, namespace) :286 · wiki_status() :477
wiki_remember(...) :318 (read the Input model WikiRememberInput :158-165 for keys: fact, category, title, link_page_id, rel …) · wiki_note(...) :413 (WikiNoteInput :168-170)
wiki_symbol_lookup(query, kind, language, path_prefix, limit) · wiki_code_outline(target, include_source, …) · wiki_blast_radius(symbol, …)  — read structural/tools.py:110-200 Input models
ledger_open(title, body, kind, severity, discovered_from, about) :637 · ledger_ready(kind) · ledger_claim(issue_id) · ledger_close(issue_id, reason) · ledger_context(file_paths, max_tokens)
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.remote_cli`~~, ~~`@remote_aware`~~, ~~`refuse_remote`~~ — created here.
- ~~a `--remote` flag per command~~ — mode comes from config/env only (brainstorm decision).
- ~~silent fallback to the local plane~~ — any `RemoteWikiError` → `click.ClickException` exit 2 (AC8).
- ~~byte-identical local rendering in remote mode~~ — remote mode prints the tool text; `--table`/`--json` on `query` in remote mode: `--json` prints the raw MCP `result` dict; `--table` is refused (design research S11 / AC7).
- ~~`ctx.obj` pre-populated by the `wiki` group~~ — `wiki()` (cli.py:1337) does not set `obj`; the decorator must `ctx.ensure_object(dict)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py", "action": "CREATE" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_cli_remote.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_project_effective",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_authoring_identity",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#query",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_structural_tool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_open",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiQueryTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The decorator must run **before** the command body and must not open any store; it reads `path_` from the command kwargs when present.
- Exit code 2 for every `RemoteWikiError` (`ClickException.exit_code = 2` via a subclass `RemoteCliError(click.ClickException)`).
- Actor for writes: `remote.actor or _authoring_identity(by)` (`--by` exists on `remember`; ledger commands have `--actor` — pass it as `by`).
- Keep local mode byte-identical: the decorator with no remote is a pass-through (AC14).

---

## Implementation Blueprint

### Steps (in order)
1. Create `remote_cli.py` — *why*: all remote plumbing in one place; `cli.py` only gains a decorator line and an early branch per command.
2. Decorate + branch the 14 proxied commands — *why*: AC7.
3. Decorate the refused commands — *why*: AC9.
4. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py` (CREATE)
```python
"""Remote-mode plumbing for the wikitoolkit CLI (FEAT-569): resolve once, proxy tool calls, refuse the rest."""
from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import click

from parrot.knowledge.wiki.project import WikiEffectiveConfig, WikiRemoteConfig, resolve_remote
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError


class RemoteCliError(click.ClickException):
    """A remote failure surfaced to the shell with exit code 2 (fail-closed, AC8)."""
    exit_code = 2


def remote_or_none(path_: str | None) -> tuple[Path, WikiEffectiveConfig, WikiRemoteConfig | None]:
    """Resolve repo root + effective config + remote WITHOUT opening any store."""
    from parrot.knowledge.wiki.cli import _resolve_project_effective  # lazy: cli imports this module
    root, effective = _resolve_project_effective(path_)
    return root, effective, resolve_remote(effective.config)


def remote_client(remote: WikiRemoteConfig, *, by: str | None = None) -> RemoteWikiClient:
    from parrot.knowledge.wiki.cli import _authoring_identity
    try:
        return RemoteWikiClient(remote, actor=remote.actor or _authoring_identity(by))
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


async def _call(remote: WikiRemoteConfig, tool: str, arguments: dict[str, Any], *, by: str | None, text: bool) -> Any:
    client = remote_client(remote, by=by)
    try:
        async with client:
            return await (client.call_tool_text(tool, arguments) if text else client.call_tool(tool, arguments))
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


def call_remote_text(remote: WikiRemoteConfig, tool: str, arguments: dict[str, Any], *, by: str | None = None) -> str:
    from parrot.knowledge.wiki.cli import _run
    return _run(_call(remote, tool, arguments, by=by, text=True))


def call_remote(remote: WikiRemoteConfig, tool: str, arguments: dict[str, Any], *, by: str | None = None) -> dict[str, Any]:
    from parrot.knowledge.wiki.cli import _run
    return _run(_call(remote, tool, arguments, by=by, text=False))


def refuse_remote(command: str, hint: str = "") -> NoReturn:
    extra = f" — {hint}" if hint else ""
    raise click.UsageError(f"`wikitoolkit {command}` is not available in remote mode{extra}")


def remote_aware(*, proxied: bool, hint: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Resolve the remote BEFORE the command body; reject --store/--backend; refuse non-proxied commands.

    Stores the remote in ``ctx.obj["remote"]`` (``None`` in local mode → command runs unchanged).
    """
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = click.get_current_context()
            ctx.ensure_object(dict)
            _root, _eff, remote = remote_or_none(kwargs.get("path_"))
            ctx.obj["remote"] = remote
            if remote is None:
                return func(*args, **kwargs)
            if kwargs.get("store_opt") or kwargs.get("backend_opt"):
                raise click.UsageError("--store/--backend cannot be combined with remote mode (remote is configured)")
            if not proxied:
                refuse_remote(ctx.command_path.replace("wiki ", "", 1), hint)
            return func(*args, **kwargs)
        return wrapper
    return deco
```
**Why this shape**: S10 — one resolution point that precedes `_resolve_read_store`/`_require_built`; the decorator is a no-op in local mode (AC14). Lazy `cli` imports break the import cycle.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — pattern; apply to every listed command)
```python
# occurrences: 1 (verified: grep -c '^def query(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# 1) Add `from parrot.knowledge.wiki import remote_cli` to the import block (cli.py:43-60 region, after the federation import).
# 2) Decorate: insert `@remote_cli.remote_aware(proxied=True)` as the LAST decorator (directly above `def query(`), so it wraps the callable click invokes.
# 3) Branch: insert as the FIRST statements of the body (before `store = _resolve_read_store(...)`, cli.py:~1845):
    remote = click.get_current_context().obj.get("remote")
    if remote is not None:
        if as_table:
            remote_cli.refuse_remote("query --table", "remote mode prints the tool text; use --json for raw results")
        args = {"question": question, "budget_tokens": budget, "namespace": ns_opt, "include_symbols": False}
        if as_json:
            click.echo(json.dumps(remote_cli.call_remote(remote, "wiki_query", args), indent=2, default=str))
        else:
            click.echo(remote_cli.call_remote_text(remote, "wiki_query", args))
        return
# Same shape for: page→wiki_page{page_id,namespace} · related→wiki_related{page_id,namespace} · status→wiki_status{} (prefix line "Mode      : remote (<url>)")
#   remember→wiki_remember{…WikiRememberInput keys, by=by} · note→wiki_note{…} · symbols lookup/outline/blast→wiki_symbol_lookup/wiki_code_outline/wiki_blast_radius
#   ledger open/ready/claim/close/context → ledger_* (pass the command's --actor as by=)
# 4) Refusals: `@remote_cli.remote_aware(proxied=False)` as last decorator on ns_list/ns_add/ns_remove, communities, export, link, memories, audit, ground,
#    ingest_jira, sync_obsidian_cmd, ledger_acknowledge/blockers/export/sync/rebuild/ingest_sdd/compact/audit.
# FILL IN: per-command argument dicts — read each MCP Input model for exact keys (tools.py:127-188, :599-623; structural/tools.py:~60-105) — bounded by AC7/AC9
```
**Why**: every proxied command follows one 6-line shape so review is mechanical; ordering the decorator last guarantees it runs before the body. Local mode: `remote is None` → unchanged code path.

### FILL IN checklist
- [ ] Argument dicts for the 14 proxied commands — bounded by the Input models named above.
- [ ] `status` remote output: `Mode      : remote (<url>)` + tool text (JSON with `--json`).
- [ ] Refusal decorator on the full list in Scope (AC9).
- [ ] Ledger `--actor` → `by=` so `X-Wiki-Actor` carries it.

---

## Acceptance Criteria

- [ ] With `remote` in `wiki.json`, no local `wiki.db`, and a fake remote: `wikitoolkit query "x"` prints the tool text and exits 0; `page`, `related`, `status`, `symbols lookup`, `ledger ready` likewise (fake returns canned text).
- [ ] `wikitoolkit query --store x "q"` → UsageError (exit 2) naming remote mode; `wikitoolkit ns list` / `link` / `memories` / `ledger blockers FEAT-1` → UsageError "not available in remote mode".
- [ ] Fake remote down → exit 2, stderr contains `[remote:unreachable]`; no `wiki.db` created (AC8).
- [ ] `wikitoolkit remember --by human:bob "fact"` sends `X-Wiki-Actor: human:bob` (fake records headers).
- [ ] Without `remote`, `test_cli.py` passes unchanged (AC14).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_remote.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_cli_remote.py
import json, pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config
# reuse the Fake aiohttp server + `server` fixture from test_remote_client.py (import them or copy the ~15 lines)


@pytest.fixture
def repo(tmp_path, server, monkeypatch):
    fake, url = server
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url=url)))
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n"); monkeypatch.chdir(tmp_path)
    return tmp_path, fake


def test_query_proxies_and_never_opens_store(repo):
    root, fake = repo
    r = CliRunner().invoke(wiki, ["query", "how does ingest work"])
    assert r.exit_code == 0 and "hello" in r.output
    assert not (root / ".parrot" / "wiki" / "wiki.db").exists()
    assert json.loads(fake.last_body)["params"]["name"] == "wiki_query"   # FILL IN: have Fake keep last_body


def test_refusals(repo):
    assert CliRunner().invoke(wiki, ["query", "--store", "x", "q"]).exit_code == 2
    r = CliRunner().invoke(wiki, ["ns", "list"]); assert r.exit_code == 2 and "remote mode" in r.output


def test_fail_closed(repo, monkeypatch):
    root, _ = repo
    monkeypatch.setenv("WIKITOOLKIT_REMOTE_URL", "http://127.0.0.1:9/mcp/w")
    r = CliRunner().invoke(wiki, ["query", "q"])
    assert r.exit_code == 2 and "[remote:unreachable]" in r.output
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3351, TASK-3359 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read every Input model before writing argument dicts
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
