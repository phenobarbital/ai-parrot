---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, sdd-tooling]
tags: [wikitoolkit, ledger, cli, mcp]
---

# Feature Specification: wikitoolkit ledger list / show

**Feature ID**: FEAT-689
**Date**: 2026-10-16
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor

Source: `sdd/proposals/wiki-ledger-show.proposal.md` (research state `sdd/state/wiki-ledger-show/`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit ledger` has 15 subcommands but no way to **read an issue by id** and no way to
**list issues in any status other than `open`**. `ledger ready` prints only
`id [severity] title (kind)` for unclaimed open issues, so claimed and closed issues can't be seen
from the CLI, and an issue's `body` can't be seen anywhere: `_issue_dict()` drops it. The pieces
already exist in the service layer: `LedgerService.list_issues()` is used only by the standup
collector, and `_issue_state()` is private. Agents (`/sdd-fix`, reviewers) therefore read
`events.jsonl` or `ledger.db` by hand to find out what an issue actually says.

### Goals
- `wikitoolkit ledger list` lists issues by status (any status, or `all`), kind, severity and
  `about` prefix, in text or `--json`.
- `wikitoolkit ledger show <issue_id>` prints the full current state (including `body`) plus the
  issue's chronological event history from `events.jsonl`, in text or `--json`.
- The same two reads are available as the MCP tools `ledger_list` and `ledger_show`, and through
  `--remote` (both are in `READ_ONLY_TOOLS`).
- Reads tolerate a busy writer lock, the same way `ready` does (`_sync_best_effort`).

### Non-Goals (explicitly out of scope)
- Changing the output of `ledger ready`, `plan-fix` or `context`. `ready` stays a separate command
  and does not become an alias.
- Any change to the ledger write path or the event schema.
- Moving `/sdd-fix` or `/sdd-next` over to the new commands (a follow-up).
- Fixing the pre-existing navconfig banner that `plan-fix --json` prints to stdout.
- An offset index for history lookups. History is a linear scan of `events.jsonl` (about 458 KB
  today).

---

## 2. Architectural Design

### Overview

The change is purely additive and reads only. Two public read methods join `LedgerService`:
`get_issue()` (the single-issue state including `body`) and `issue_history()` (events whose
`subject` equals the issue id, read off-loop with `asyncio.to_thread` over
`LedgerLog.iter_events()`). `list_issues()` gains an optional `severity` filter. A module-level
`normalize_issue_id()` accepts `a9514c9232ad` or `issue:a9514c9232ad`.

Two framework-free operations, `op_ledger_list` and `op_ledger_show`, wrap the service. The MCP
transport, both tool adapter layers and the remote read-only allowlist register them by name,
following the `ledger_context` pattern line for line. The CLI adds `ledger list` and `ledger show`
next to `ledger ready`, with the standard `@remote_cli.remote_aware(proxied=True, tool=...)` branch
and `--json` output via `json.dumps(..., indent=2, default=str)` (the same pattern as the `page`
command).

### Component Diagram
```
CLI  ledger list / ledger show ──┐ (local)            ┌── remote_cli.call_remote(_text) ── remote server
                                 │                    │        (needs READ_ONLY_TOOLS entry)
                                 ▼                    │
MCP  ledger_list / ledger_show ─→ op_ledger_list / op_ledger_show  (ledger/operations.py)
                                 │
                                 ▼
                LedgerService.list_issues(severity=…) · get_issue() · issue_history()
                                 │                         │
                       ledger.db pages (store._read)   LedgerLog.iter_events (events.jsonl)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LedgerService.list_issues` | extends | new keyword-only `severity` filter; default behaviour unchanged |
| `LedgerService._issue_state` | reuses | `get_issue` builds on it; the private method stays |
| `LedgerLog.iter_events` | uses | per-issue history filter on `event.subject` |
| `transport._SPECS` + dispatch | extends | two new `mount="ledger"` entries |
| `remote.READ_ONLY_TOOLS` | extends | allows `--remote` proxying |
| `parrot_tools.wiki.tools.create_wiki_tools` | extends | two new tool classes appended after `LedgerContextTool` |

### Data Models
```python
class LedgerListInput(BaseModel):
    statuses: list[IssueStatus] | None = None   # None => ["open", "claimed"]
    all_statuses: bool = False                  # True => every status
    kind: IssueKind | None = None
    severity: IssueSeverity | None = None
    about_prefix: str | None = None

class LedgerShowInput(BaseModel):
    issue_id: str                               # bare hex or "issue:<hex>"
    include_history: bool = True
```

`ledger_list` result: `{"issues": [<_issue_dict rows>]}`. These rows do not include `body`.
`ledger_show` result: `{"issue": <_issue_dict row + "body">, "history": [<event dicts>]}`.
History event dict: `{"event_id", "kind", "actor", "ts", "payload"}`, in log order.
An unknown id returns `OperationResult(is_error=True, text="Issue issue:<hex> not found")`.

### New Public Interfaces
See the §3 Interface Skeletons. CLI usage:
```
wikitoolkit ledger list [--status open|claimed|closed|superseded|all]... [--kind K] [--severity S] [--about PREFIX] [--json]
wikitoolkit ledger show ISSUE_ID [--json] [--no-history]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Service read API | yes | signatures below; `issue_history` via `asyncio.to_thread`; sort unchanged | — |
| M2: Ops + MCP + remote wiring | yes | mirror the `ledger_context` entries in every listed file; names fixed below | — |
| M3: CLI `list` / `show` | yes | mirror `ledger_ready` (busy handling) and `page` (`--json` + remote) | — |

### Module 1: Service read API
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
- **Responsibility**: public single-issue state, per-issue history, a severity filter on
  `list_issues`, and id normalization.
- **Depends on**: existing `_issue_state`, `_issue_dict`, `LedgerLog.iter_events`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py  (modifies)
  def normalize_issue_id(raw: str) -> str:
      """Return ``raw`` prefixed with ``issue:`` unless it already is; strips whitespace."""

  class LedgerService:  # verified: service.py:127
      async def list_issues(  # verified: service.py:278 — add keyword-only `severity`
          self,
          statuses: Sequence[str] = ("open", "claimed"),
          *,
          kind: IssueKind | None = None,
          severity: IssueSeverity | None = None,
          about_prefix: str | None = None,
      ) -> list[dict[str, Any]]:
          """…existing contract…; ``severity`` keeps only rows of that severity."""

      async def get_issue(self, issue_id: str) -> dict[str, Any] | None:
          """Public issue dict (``_issue_dict`` shape) plus ``body``; ``None`` when unknown.

          Normalizes the id, runs ``_sync_best_effort()`` first, then reads via ``_issue_state``.  # verified: service.py:198,336
          """

      async def issue_history(self, issue_id: str) -> list[dict[str, Any]]:
          """Events whose ``subject`` equals the normalized id, in log order.

          Each item: ``{"event_id", "kind", "actor", "ts", "payload"}``. Scans
          ``self.log.iter_events()`` inside ``asyncio.to_thread``.  # verified: log.py:83, service.py:141
          Returns ``[]`` for an unknown id.
          """
  ```

### Module 2: Ops + MCP + remote wiring
- **Paths**: `ledger/operations.py`, `transport.py`, `remote.py`, core `wiki/tools.py`,
  `parrot_tools/wiki/tools.py`, `parrot_tools/wiki/ledger.py`, `parrot_tools/__init__.py`
- **Responsibility**: expose `ledger_list` and `ledger_show` as MCP tools and as remote
  read-only tools.
- **Depends on**: Module 1 (`get_issue`, `issue_history`, `list_issues(severity=)`)
- **Interface Skeleton**:
  ```python
  # ledger/operations.py  (modifies; after LedgerContextInput, verified: operations.py:64)
  class LedgerListInput(BaseModel):
      """Schema mirrors `wikitoolkit ledger list` options one for one."""
      statuses: list[IssueStatus] | None = Field(default=None, description="Statuses to include (default open+claimed)")
      all_statuses: bool = Field(default=False, description="Include every status; overrides statuses")
      kind: IssueKind | None = Field(default=None, description="Filter by issue kind")
      severity: IssueSeverity | None = Field(default=None, description="Filter by severity")
      about_prefix: str | None = Field(default=None, description="Keep issues with an about entry starting with this prefix")

  class LedgerShowInput(BaseModel):
      issue_id: str = Field(..., description="Issue id, with or without the issue: prefix")
      include_history: bool = Field(default=True, description="Include the issue's event history")

  async def op_ledger_list(service: LedgerService, params: LedgerListInput, **context: Any) -> OperationResult:
      """ledger_list — list issues by status/kind/severity/about prefix → data={"issues": [...]}."""

  async def op_ledger_show(service: LedgerService, params: LedgerShowInput, **context: Any) -> OperationResult:
      """ledger_show — one issue with body (+ history) → data={"issue":…, "history":[…]}; is_error when unknown."""

  # parrot_tools/wiki/tools.py  (modifies; after LedgerContextTool, verified: tools.py:395)
  class LedgerListTool(AbstractTool):
      """List SDD ledger issues by status, kind, severity or about prefix."""
      name = "ledger_list"
  class LedgerShowTool(AbstractTool):
      """Show one SDD ledger issue in full, including body and event history."""
      name = "ledger_show"
  ```
  `IssueStatus` is imported from `parrot.knowledge.wiki.ledger.events` (verified: events.py:24).

### Module 3: CLI `ledger list` / `ledger show`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: the two subcommands, inserted between `ledger_ready` and
  `@ledger.command("claim")`.
- **Depends on**: Module 1. It also uses the tool names `ledger_list`/`ledger_show` as strings for
  the remote branch, but has no code dependency on Module 2.
- **Interface Skeleton**:
  ```python
  # cli.py  (modifies; insert before @ledger.command("claim"), verified: cli.py:3298)
  @ledger.command("list")
  @click.option("--status", "statuses", multiple=True,
                type=click.Choice(["open", "claimed", "closed", "superseded", "all"]), help="Repeatable; default open+claimed.")
  @click.option("--kind", type=click.Choice(["bug", "tech_debt", "feature_gap", "vulnerability"]), default=None)
  @click.option("--severity", type=click.Choice(["critical", "major", "minor", "low"]), default=None)
  @click.option("--about", "about_prefix", default=None, help="Keep issues whose about starts with this prefix.")
  @click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
  @remote_cli.remote_aware(proxied=True, tool="ledger_list")
  def ledger_list(statuses: tuple[str, ...], kind: str | None, severity: str | None,
                  about_prefix: str | None, as_json: bool) -> None:
      """List ledger issues by status, kind, severity or about prefix."""

  @ledger.command("show")
  @click.argument("issue_id")
  @click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
  @click.option("--no-history", is_flag=True, help="Omit the event history.")
  @remote_cli.remote_aware(proxied=True, tool="ledger_show")
  def ledger_show(issue_id: str, as_json: bool, no_history: bool) -> None:
      """Show one ledger issue in full: state, body and event history."""
  ```
  Text formats:
  - `list` prints one line per issue:
    `{issue_id} [{severity}] {status} {title} ({kind})`, with ` — claimed by {claimed_by}` appended
    when the issue is claimed. With no rows it prints `No matching issues.`
  - `show` prints a header block in this order: id, title, status, kind, severity, acknowledged,
    discovered_from, about, claimed_by, closed_by, closed_reason, resolved_by. Fields whose value
    is `None` or empty are omitted. Then a blank line, then `body` verbatim, then
    `History:` with one line per event: `{ts} {actor} {kind}`, followed by the payload's
    `reason`, `claimed_by`, `unclaimed_by` or `resolved_by` when present.
  - An unknown id raises `click.ClickException("Issue <id> not found")`, which exits with code 1.
  - `WikiStoreBusy` is reported as `Ledger index is busy (<op>); …` instead of a traceback.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_normalize_issue_id` | M1 | bare hex gets the prefix; prefixed id and surrounding whitespace are handled |
| `test_get_issue_includes_body` | M1 | open an issue, then `get_issue` returns `body` and all `_issue_dict` keys |
| `test_get_issue_unknown_returns_none` | M1 | unknown id → `None` |
| `test_issue_history_order_and_filter` | M1 | open→claim→close: 3 events in order; other issues' events excluded |
| `test_list_issues_severity_filter` | M1 | `severity="major"` keeps only major |
| `test_op_ledger_list_all_statuses` | M2 | `all_statuses=True` includes closed |
| `test_op_ledger_show_unknown_is_error` | M2 | `is_error=True`, the text names the id |
| `test_ledger_list_show_tool_names` | M2 | `LedgerListTool.name == "ledger_list"`, `LedgerShowTool.name == "ledger_show"` |
| `test_read_only_tools_include_list_show` | M2 | both names in `READ_ONLY_TOOLS` |
| `test_cli_ledger_list_default_and_status_all` | M3 | CliRunner: default hides closed; `--status all` shows it |
| `test_cli_ledger_list_json` | M3 | `--json` stdout parses with `json.loads` |
| `test_cli_ledger_show_text_and_json` | M3 | body + History lines; `--json` has `issue` and `history` keys; `--no-history` omits them |
| `test_cli_ledger_show_unknown_exit_1` | M3 | exit code 1 |

### Integration Tests
| Test | Description |
|---|---|
| `test_mcp_server_ledger` (update) | the ledger-mounted tool count goes from 12 to 14 (`tests/knowledge/wiki/test_mcp_server_ledger.py:52`); `ledger_list`/`ledger_show` are present |

### Test Data / Fixtures
Reuse the existing tmp-dir ledger fixtures in `tests/knowledge/wiki/test_cli_ledger.py`
(`LedgerService.from_dir(tmp_path)` style). Tests go in that file (M3), in
`tests/knowledge/wiki/test_ledger_tools.py` (M2) and in a new
`tests/knowledge/wiki/test_ledger_service_reads.py` (M1).

---

## 5. Acceptance Criteria

- [ ] `wikitoolkit ledger --help` lists `list` and `show`.
- [ ] `ledger list` with no flags shows `open` and `claimed` issues, severity-sorted;
      `--status all` adds `closed` and `superseded`; `--kind`, `--severity` and `--about` filter.
- [ ] `ledger show <id>` prints `body` and a chronological history; it accepts the id with or
      without `issue:`; an unknown id exits 1.
- [ ] `--json` output of both commands is valid JSON (`json.loads(stdout)` succeeds in CliRunner).
- [ ] MCP tools `ledger_list` and `ledger_show` are listed when a ledger is mounted and return the
      data shapes in §2.
- [ ] `ledger_list` and `ledger_show` are in `remote.READ_ONLY_TOOLS`, and the CLI proxies them
      when `--remote` is configured.
- [ ] `ledger ready`, `plan-fix` and `context` output is byte-identical to before (existing tests
      unchanged and green).
- [ ] All §4 tests pass; `ruff check` is clean on every touched file.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus, SEVERITY_ORDER  # verified: ledger/events.py:22-26
from parrot.knowledge.wiki.ledger.log import LedgerLog            # verified: ledger/service.py:29
from parrot.knowledge.wiki.ledger.service import LedgerService    # verified: cli.py:127
from parrot.knowledge.wiki.operations import OperationResult      # verified: ledger/operations.py:19
from parrot.knowledge.wiki.store import WikiStoreBusy             # verified: ledger/service.py:36
from parrot.knowledge.wiki import remote_cli                      # verified: cli.py:104
from parrot.tools.abstract import AbstractTool, ToolResult        # verified: parrot_tools/wiki/tools.py:20
```

### Existing Class Signatures
```python
# ledger/events.py
IssueStatus = Literal["open", "claimed", "closed", "superseded"]           # line 24
def compute_issue_id(kind: str, title: str, discovered_from: str) -> str:   # line 96 → f"issue:{sha1[:12]}" (line 100)
class LedgerEvent(BaseModel):                                               # line 103
    event_id: str; kind: LedgerEventKind; subject: str; actor: str; ts: str; payload: dict[str, Any]  # lines 106-111

# ledger/log.py
class LedgerLog:
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:  # line 83

# ledger/service.py
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:   # line 109 — no "body" key
class LedgerService:                                                        # line 127
    log: LedgerLog                                                          # set line 141
    async def _sync_best_effort(self) -> None:                              # line 198
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:        # line 205
    async def list_issues(self, statuses: Sequence[str] = ("open", "claimed"), *,
                          kind: IssueKind | None = None, about_prefix: str | None = None) -> list[dict[str, Any]]:  # line 278
    async def _issue_state(self, issue_id: str) -> dict[str, Any] | None:   # line 336 — decoded state incl. "body"

# ledger/operations.py
class LedgerContextInput(BaseModel):                                        # line 64
def _failed(exc: Exception) -> OperationResult:                             # line 69
async def op_ledger_context(service, params, **context) -> OperationResult: # line 123

# cli.py
def _run(coro: Any) -> Any:                                                 # line 579
def ledger_ready(kind: str | None) -> None:                                 # line 3280 (busy handling pattern)
# `page` command --json + remote pattern: lines 2203-2235 (remote_cli.call_remote / call_remote_text)

# parrot_tools/wiki/tools.py
class LedgerContextTool(AbstractTool):                                      # line 395 (adapter pattern)
def create_wiki_tools(...)  # ledger block appends LedgerContextTool(ledger_service) at line 581
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LedgerService.get_issue` | `_issue_state`, `_issue_dict` | method call | `service.py:336`, `:109` |
| `LedgerService.issue_history` | `LedgerLog.iter_events` | `asyncio.to_thread` | `log.py:83` |
| `op_ledger_list` | `LedgerService.list_issues` | method call | `service.py:278` |
| `ledger_list`/`ledger_show` MCP | `transport._SPECS` + `elif name ==` dispatch | registration | `transport.py:147`, `:401` |
| CLI remote branch | `remote_cli.call_remote` / `call_remote_text` | function call | `remote_cli.py:65,78` |

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit ledger list`~~ / ~~`ledger show`~~ — no such commands (verified: `wikitoolkit ledger --help`)
- ~~`LedgerService.get_issue`~~, ~~`LedgerService.issue_history`~~, ~~`normalize_issue_id`~~ — created by this feature
- ~~`op_ledger_list`~~, ~~`op_ledger_show`~~, ~~`LedgerListTool`~~, ~~`LedgerShowTool`~~ — created by this feature
- ~~`_issue_dict(...)["body"]`~~ — `_issue_dict` has no `body` key; do NOT add one (it would bloat `ready`/`list` output)
- ~~`LedgerLog.events_for(subject)`~~ — no subject-indexed reader exists; filter `iter_events()`
- ~~`LedgerIndex.get_issue`~~ — the index has only private `_read_issue(conn, id)`; go through the service

### Edit Sites (Blueprint Anchors)
Verified against: `0b36a5713`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:` (add `normalize_issue_id` above) | `service.py:109` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `    async def list_issues(` | `service.py:278` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `    async def claim(self, issue_id: str, actor: str) -> bool:` (insert get_issue/issue_history above) | `service.py:310` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py` | MODIFY | `class LedgerContextInput(BaseModel):` | `operations.py:64` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py` | MODIFY | `async def op_ledger_context(` | `operations.py:123` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    LedgerContextInput,` | `transport.py:25` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    op_ledger_context,` | `transport.py:30` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    "ledger_context": _Spec(` | `transport.py:147` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    elif name == "ledger_context":` | `transport.py:401` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote.py` | MODIFY | `        "ledger_context",` | `remote.py:27` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `    op_ledger_context,` | `tools.py:14` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `    "LedgerContextTool": "parrot_tools.wiki.ledger",` | `tools.py:79` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | MODIFY | `    op_ledger_context,` | `tools.py:29` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | MODIFY | `class LedgerContextTool(AbstractTool):` | `tools.py:395` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | MODIFY | `                LedgerContextTool(ledger_service),` | `tools.py:581` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/ledger.py` | MODIFY | `    LedgerContextTool,` | `ledger.py:6` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | `    "ledger_context": "parrot_tools.wiki.tools.LedgerContextTool",` | `__init__.py:155` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `@ledger.command("claim")` (insert list/show above) | `cli.py:3298` | 1 |
| `tests/knowledge/wiki/test_mcp_server_ledger.py` | MODIFY | `assert len(tools) == 12` | `test_mcp_server_ledger.py:52` | 1 |
| `tests/knowledge/wiki/test_ledger_service_reads.py` | CREATE | — | — | — |
| `tests/knowledge/wiki/test_ledger_tools.py` | MODIFY | (append tests) | — | — |
| `tests/knowledge/wiki/test_cli_ledger.py` | MODIFY | (append tests) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- CLI: follow `ledger_ready` (cli.py:3277) for `WikiStoreBusy`, and `page` (cli.py:2203) for
  `--json`. In the remote branch, use `remote_cli.call_remote` for `--json` and `call_remote_text`
  otherwise.
- The ops stay framework-free (operations.py module docstring), with input schemas mirroring the
  CLI one for one. Catch exceptions with `_failed(exc)`.
- The `IssueKind`/`IssueStatus` Literals are already validated by the schema, so don't call them
  as constructors (the existing comment at operations.py:93-94 explains why).
- Tool adapters use `Model.model_construct(...)` in `_execute`, as `LedgerContextTool` does.
- `--status all` (CLI) and `all_statuses=True` (MCP) mean every value of `IssueStatus`.
  `--status` given together with `all` resolves to all.

### Known Risks / Gotchas
- **Shared venv runs main-checkout code.** Inside the worktree, run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
- **navconfig banner on stdout.** This is a pre-existing problem for `plan-fix --json` under a real
  shell. CliRunner tests aren't affected. Don't add any `print`/echo before the JSON.
- **History scan cost** is O(log size). That's acceptable at about 458 KB; an index is a follow-up.
- **Duplicate-open events.** A colliding `issue.opened` only adds an edge (index.py:164-168), but it
  still appears in the log, so history will show it. This is intended: history mirrors the log.
- **Tool-count assertions.** `test_mcp_server_ledger.py:52` hard-codes 12; update it to 14.

### External Dependencies
None.

---

## 8. Open Questions

- [x] Which surfaces get the new reads? — *Resolved in proposal*: CLI + MCP + remote proxy (`READ_ONLY_TOOLS`).
- [x] What does `show` include? — *Resolved in proposal*: current state including body + event history from `events.jsonl`.
- [x] Should `ready` become an alias of `list`? — *Resolved in proposal (default)*: no, it stays separate and unchanged.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (exploration doc status is `review`, not `accepted`)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-689-wiki-ledger-show`. The `sdd-coder` engine
  gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1 (the ops call `get_issue`, `issue_history` and
  `list_issues(severity=)`); M3 → M1 (the CLI's local branch calls the same methods). M2 and M3
  share no edge and can run concurrently once M1 is merged.
- **Shared files**: none. M2 and M3 touch disjoint files; M1 alone touches `service.py`.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-16 | Jesus Lara / Claude | Initial draft from wiki-ledger-show proposal |
