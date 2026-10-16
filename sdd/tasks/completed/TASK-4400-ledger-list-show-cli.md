# TASK-4400: CLI `wikitoolkit ledger list` / `ledger show`

**Feature**: FEAT-689 — wikitoolkit ledger list / show
**Spec**: `sdd/specs/wiki-ledger-show.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4398
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. This task adds the two read subcommands to the `ledger` click group, between
`ledger ready` and `ledger claim`. The local branch calls the TASK-4398 service reads. The remote
branch proxies the MCP tool names `ledger_list`/`ledger_show` as plain strings, so this task has
**no code dependency on TASK-4399** and can run alongside it.

---

## Scope

- Add `@ledger.command("list")` → `ledger_list(...)` with `--status` (repeatable, may be `all`), `--kind`, `--severity`, `--about` and `--json`.
- Add `@ledger.command("show")` → `ledger_show(issue_id, as_json, no_history)`.
- Both use `@remote_cli.remote_aware(proxied=True, tool=...)`. The remote branch calls `call_remote` with `--json` and `call_remote_text` otherwise (the `page` pattern).
- Report `WikiStoreBusy` as `Ledger index is busy (<op>); …` (the `ledger_ready` pattern); an unknown id → `click.ClickException` (exit 1).
- Add the M3 CliRunner tests to `tests/knowledge/wiki/test_cli_ledger.py`.

**NOT in scope**: service methods (TASK-4398); ops/MCP/remote allowlist (TASK-4399); changing
`ledger ready`, `plan-fix` or `context` output; the navconfig stdout banner.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `ledger list` and `ledger show` subcommands |
| `tests/knowledge/wiki/test_cli_ledger.py` | MODIFY | M3 CliRunner tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in cli.py — do not re-import
import json                                                        # used by `page` (cli.py:2225)
from typing import cast                                            # used by ledger_ready (cli.py:3288)
from parrot.knowledge.wiki import remote_cli                       # verified: cli.py:104
from parrot.knowledge.wiki.store import WikiStoreBusy              # verified: cli.py:114 (inside the store import block)
from parrot.knowledge.wiki.ledger.service import LedgerService     # verified: cli.py:127
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity  # verified: cli.py:129 — extend with IssueStatus
from parrot.knowledge.wiki.ledger.events import IssueStatus        # verified: ledger/events.py:24
```
`typing.get_args` is stdlib; import it locally in the command or extend the module's `typing` import.

### Existing Signatures to Use
```python
# cli.py
def _run(coro: Any) -> Any:                                        # line 579 — asyncio.run wrapper
@ledger.command("ready") … def ledger_ready(kind: str | None) -> None:  # lines 3277-3295 — remote branch + WikiStoreBusy pattern
@ledger.command("claim")                                           # line 3298 — insertion anchor
# `page` command --json + remote: cli.py:2219-2228
#   remote = click.get_current_context().obj.get("remote")
#   if remote is not None: json.dumps(remote_cli.call_remote(remote, tool, args), indent=2, default=str) | remote_cli.call_remote_text(remote, tool, args)

# remote_cli.py
def call_remote_text(remote, tool: str, arguments: dict[str, Any], *, by: str | None = None) -> str   # line 65
def call_remote(remote, tool: str, arguments: dict[str, Any], *, by: str | None = None) -> Any       # line 78

# TASK-4398 (must be merged first) — ledger/service.py
async def list_issues(self, statuses=("open","claimed"), *, kind=None, severity=None, about_prefix=None) -> list[dict]
async def get_issue(self, issue_id: str) -> dict[str, Any] | None              # _issue_dict keys + "body"
async def issue_history(self, issue_id: str) -> list[dict[str, Any]]          # {"event_id","kind","actor","ts","payload"}
def normalize_issue_id(raw: str) -> str

# tests/knowledge/wiki/test_cli_ledger.py
#   fixtures: runner (line 26), mock_ledger_service (line 32, MagicMock(spec=LedgerService))
#   pattern: with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service): runner.invoke(ledger, [...])
```

### Does NOT Exist
- ~~`wikitoolkit ledger list`~~ / ~~`ledger show`~~ — this task creates them
- ~~`ledger_list`/`ledger_show` MCP ops as importable symbols for the CLI~~ — the CLI never imports them; the remote branch uses the tool-name strings
- ~~`remote_cli.call_remote_json`~~ — only `call_remote` and `call_remote_text` exist
- ~~`issue["body"]` from `list_issues`~~ — list rows have no body; only `get_issue` has it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_cli_ledger.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_ready",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py#call_remote",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py#call_remote_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Emit nothing before the JSON on stdout under `--json` (spec §7, navconfig-banner gotcha). Use a single `click.echo(json.dumps(..., indent=2, default=str))`.
- `--status` resolution: `all` anywhere in the tuple → `get_args(IssueStatus)`; an empty tuple → `("open", "claimed")`; otherwise the given statuses. Remote: `{"statuses": [s for s in statuses if s != "all"] or None, "all_statuses": "all" in statuses, "kind": ..., "severity": ..., "about_prefix": ...}`.
- Remote `show` arguments: `{"issue_id": issue_id, "include_history": not no_history}`.
- `--no-history`: the text output omits the `History:` section, and the JSON omits the `"history"` key (spec §4 `test_cli_ledger_show_text_and_json`).
- The text formats are fixed by spec §3 M3 (see the blueprint). Do not change `ledger ready` output.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the cli.py events import with `IssueStatus`. *Why:* status expansion and the casts use it.
2. Insert both commands above `@ledger.command("claim")`. *Why:* spec §3 M3 fixes the placement next to `ready`.
3. Append the tests, then run the validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cxF 'from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity' cli.py)
# REPLACE line cli.py:129 WITH:
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus
```

### `cli.py` (MODIFY) — commands
```python
# occurrences: 1 (verified: grep -c '@ledger.command("claim")' cli.py)
# BEFORE — insert above `@ledger.command("claim")` (verified: cli.py:3298), keeping two blank lines between commands
@ledger.command("list")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(["open", "claimed", "closed", "superseded", "all"]),
    help="Repeatable; default open+claimed.",
)
@click.option("--kind", type=click.Choice(["bug", "tech_debt", "feature_gap", "vulnerability"]), default=None)
@click.option("--severity", type=click.Choice(["critical", "major", "minor", "low"]), default=None)
@click.option("--about", "about_prefix", default=None, help="Keep issues whose about starts with this prefix.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@remote_cli.remote_aware(proxied=True, tool="ledger_list")
def ledger_list(
    statuses: tuple[str, ...], kind: str | None, severity: str | None, about_prefix: str | None, as_json: bool
) -> None:
    """List ledger issues by status, kind, severity or about prefix."""
    want_all = "all" in statuses
    explicit = [s for s in statuses if s != "all"]
    remote = click.get_current_context().obj.get("remote")
    if remote is not None:
        arguments = {
            "statuses": explicit or None,
            "all_statuses": want_all,
            "kind": kind,
            "severity": severity,
            "about_prefix": about_prefix,
        }
        if as_json:
            click.echo(json.dumps(remote_cli.call_remote(remote, "ledger_list", arguments), indent=2, default=str))
        else:
            click.echo(remote_cli.call_remote_text(remote, "ledger_list", arguments))
        return
    service = LedgerService.from_root()
    try:
        resolved = get_args(IssueStatus) if want_all else (tuple(explicit) or ("open", "claimed"))
        issues = _run(
            service.list_issues(
                resolved,
                kind=cast(IssueKind, kind) if kind else None,
                severity=cast(IssueSeverity, severity) if severity else None,
                about_prefix=about_prefix,
            )
        )
    except WikiStoreBusy as exc:
        click.echo(f"Ledger index is busy ({exc.operation}); no issues available (index_pending)")
        return
    if as_json:
        click.echo(json.dumps({"issues": issues}, indent=2, default=str))
        return
    # FILL IN: one line per issue `{issue_id} [{severity}] {status} {title} ({kind})` + ` — claimed by {claimed_by}` when status == "claimed";
    #          "No matching issues." when empty — bounded by spec §3 M3 text format


@ledger.command("show")
@click.argument("issue_id")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.option("--no-history", is_flag=True, help="Omit the event history.")
@remote_cli.remote_aware(proxied=True, tool="ledger_show")
def ledger_show(issue_id: str, as_json: bool, no_history: bool) -> None:
    """Show one ledger issue in full: state, body and event history."""
    remote = click.get_current_context().obj.get("remote")
    if remote is not None:
        arguments = {"issue_id": issue_id, "include_history": not no_history}
        if as_json:
            click.echo(json.dumps(remote_cli.call_remote(remote, "ledger_show", arguments), indent=2, default=str))
        else:
            click.echo(remote_cli.call_remote_text(remote, "ledger_show", arguments))
        return
    service = LedgerService.from_root()
    try:
        issue = _run(service.get_issue(issue_id))
        if issue is None:
            raise click.ClickException(f"Issue {normalize_issue_id(issue_id)} not found")
        history = [] if no_history else _run(service.issue_history(issue_id))
    except WikiStoreBusy as exc:
        click.echo(f"Ledger index is busy ({exc.operation}); issue unavailable (index_pending)")
        return
    if as_json:
        payload: dict[str, Any] = {"issue": issue}
        if not no_history:
            payload["history"] = history
        click.echo(json.dumps(payload, indent=2, default=str))
        return
    # FILL IN: header lines `<field>: <value>` in order id(issue_id), title, status, kind, severity, acknowledged,
    #          discovered_from, about (comma-joined), claimed_by, closed_by, closed_reason, resolved_by — skip None/empty
    #          (keep acknowledged only when True); blank line; body verbatim; unless no_history: "History:" then per event
    #          `{ts} {actor} {kind}` + the first present of payload reason/claimed_by/unclaimed_by/resolved_by — bounded by spec §3 M3
```
**Why**: the remote and `--json` branches copy `page` (cli.py:2219-2228) so remote output stays
identical in shape. `WikiStoreBusy` handling copies `ledger_ready`. `normalize_issue_id` comes from
`parrot.knowledge.wiki.ledger.service`: add it to the existing `from parrot.knowledge.wiki.ledger.service
import LedgerService` line (cli.py:127). `get_args` comes from `typing`: extend the module's existing
`from typing import TYPE_CHECKING, Any, Optional, cast` line (cli.py:41) by adding `get_args`. `Any` is already imported (it's used by `_run`).

### `tests/knowledge/wiki/test_cli_ledger.py` (MODIFY — append)
```python
def _issue(**over: Any) -> dict[str, Any]:
    """A public issue dict as LedgerService.get_issue returns it."""
    row = {
        "issue_id": "issue:abc123",
        "title": "Broken thing",
        "status": "open",
        "kind": "bug",
        "severity": "major",
        "acknowledged": False,
        "discovered_from": "spec:FEAT-689",
        "about": ["sym:a.py#f"],
        "claimed_by": None,
        "closed_by": None,
        "closed_reason": None,
        "resolved_by": None,
        "body": "Full body text",
    }
    row.update(over)
    return row


def test_cli_ledger_list_default_and_status_all(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Default passes open+claimed; --status all passes every status."""
    # FILL IN: service.list_issues = AsyncMock(return_value=[...]); invoke ["list"] then ["list", "--status", "all"];
    #          assert the first positional arg of each await is ("open","claimed") / ("open","claimed","closed","superseded")


def test_cli_ledger_list_json(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """--json stdout parses with json.loads and has an "issues" key."""
    # FILL IN


def test_cli_ledger_show_text_and_json(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Text shows body and History lines; --json has issue+history; --no-history omits them."""
    # FILL IN: get_issue → _issue(); issue_history → [{"event_id": "e1", "kind": "issue.opened", "actor": "agent:x", "ts": "2026-10-16T00:00:00+00:00", "payload": {}}]


def test_cli_ledger_show_unknown_exit_1(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Unknown id exits 1 and names the normalized id."""
    # FILL IN: get_issue → None; invoke ["show", "abc123"]; exit_code == 1 and "issue:abc123" in output
```

### FILL IN checklist
- [ ] `ledger_list` text rendering, bounded by spec §3 M3
- [ ] `ledger_show` header, body and history rendering, bounded by spec §3 M3
- [ ] the four test bodies (set `get_issue`/`issue_history`/`list_issues` as `AsyncMock`s on the `mock_ledger_service` fixture)

---

## Acceptance Criteria

- [ ] `wikitoolkit ledger --help` lists `list` and `show`
- [ ] `ledger list` defaults to open+claimed; `--status all` adds closed/superseded; `--kind`/`--severity`/`--about` filter
- [ ] `ledger show <id>` prints body and a chronological history; it accepts the id with or without `issue:`; an unknown id exits 1
- [ ] `--json` output of both commands parses with `json.loads`
- [ ] with `--remote` configured, both commands proxy `ledger_list`/`ledger_show`
- [ ] existing `ledger ready`/`context`/`plan-fix` tests are unchanged and green; `ruff check` is clean on cli.py

## Validation Commands
- `pytest tests/knowledge/wiki/test_cli_ledger.py -q`

---

## Test Specification

See the append block. Spec §4 rows covered: `test_cli_ledger_list_default_and_status_all`, `test_cli_ledger_list_json`,
`test_cli_ledger_show_text_and_json`, `test_cli_ledger_show_unknown_exit_1`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wiki-ledger-show --feature-id FEAT-689`).
2. TASK-4398 must be `done`. TASK-4399 is not required.
3. Verify the Codebase Contract and mark the task `in-progress` in `sdd/tasks/index/wiki-ledger-show.json`.
4. Implement from the blueprint and complete every `FILL IN`.
5. Run the validation with `PYTHONPATH=packages/ai-parrot/src`, then commit only the two listed files.
6. Close with `scripts/sdd/close_task.sh TASK-4400 wiki-ledger-show verified` and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-luna, codex, 1 attempt, 66s)
**Date**: 2026-10-16
**Notes**: Delivered per task contract; merged cleanly, no unexpected files. Verified with the task's validation commands run with PYTHONPATH covering ai-parrot and ai-parrot-tools sources (test_ledger_tools, test_mcp_server_ledger, test_cli_ledger: 59 passed; golden/manifest/remote/service-read suites: 43 passed). The engine merge-tier sweep is red only from pre-existing environment failures (missing Cython parrot.utils.types in worktree, unrelated mcp-server/installer tests failing on the base checkout too); it is not a green run. No review defects; no feedback recorded.
