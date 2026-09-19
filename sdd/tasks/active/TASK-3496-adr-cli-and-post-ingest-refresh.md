# TASK-3496: `wikitoolkit adr` CLI group and post-ingest refresh

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3489, TASK-3493, TASK-3494, TASK-3495
**Assigned-to**: unassigned

---

## Context

Module 6's operator half, and the **only** surface through which a maintainer
accepts a candidate (Q3 / AC11). It also wires the post-ingest ADR refresh into
`build` and `upsert`, so an ordinary `wikitoolkit build` keeps decisions fresh
without ever invoking a model (AC5).

`cli.py` is a shared, 187 KB file that spec §7 says has one owner; this task is
that owner for FEAT-578. It also picks up the CLI-side managed-page guards that
TASK-3495 deliberately left out because they live here.

---

## Scope

- Add `decisions/cli.py` holding the `adr` command group: `sync`, `lookup`,
  `why`, `generate`, `review`, `export`.
- Register the group on the existing `wiki` click group in `cli.py`.
- Wire `refresh_decisions` into `build` and `upsert`, **after** ordinary
  ingestion and deletion handling, avoiding recursion during read repair.
- Apply the managed-page guard to the CLI `note` (`cli.py:3470`) and `remember`
  (`cli.py:3330`) commands.
- Implement the exit-code contract and JSON error envelope.
- Test the command surface, exit codes and CLI/MCP parity of error codes.

**NOT in scope**: service internals, tool registration (TASK-3494), guards on
the tool/toolkit surfaces (TASK-3495).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py` | CREATE | The `adr` click group and its six commands |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Register `adr`; post-ingest refresh; note/remember guards |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli.py` | CREATE | Command surface, exit codes, JSON envelope |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import click
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions          # TASK-3489
from parrot.knowledge.wiki.decisions.models import DecisionError, CandidateEdit, ReviewRequest  # TASK-3479
from parrot.knowledge.wiki.decisions.render import render_dossier_text        # TASK-3488
from parrot.knowledge.wiki.decisions.review import render_export              # TASK-3492
from parrot.knowledge.wiki.decisions.service import DecisionService           # TASK-3490/3493
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@click.group(name="wiki")                                        # line 1328
def wiki(ctx: click.Context, verbose: bool) -> None: ...         # line 1337
@wiki.group(name="symbols")                                      # line 2195  <- GROUP PATTERN TO COPY
def symbols() -> None: ...                                       # line 2196
@wiki.group(name="ledger")                                       # line 2638
def _run(coro: Any) -> Any:                                      # line 496 — asyncio.run for sync click commands
def _resolve_project(path_) -> tuple[Path, WikiProjectConfig]    # used by every command, e.g. line ~1683
async def _ingest_files(store, sources, root, scan, force=False,
                        force_rel_paths=None) -> dict[str, Any]: ...   # line 683
def build(...)                                                   # line 1401 (click command)
def upsert(paths, path_, changed, quiet) -> None: ...            # line 1670 (click command)
def remember(...)                                                # line 3330
def note(...)                                                    # line 3470
#   decorators reused across commands: @path_option, @ns_option, @_store_options
#   `from parrot.clients.factory import LLMFactory` already present at line 3271

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py  (TASK-3490/3493)
async def sync(self, paths: list[str] | None = None) -> SyncResult: ...
async def for_symbol(self, symbol, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier: ...
async def why(self, question, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier: ...
async def generate(self, target: str) -> GenerationResult: ...
async def review(self, request: ReviewRequest) -> DecisionRecord: ...
```

### Does NOT Exist

- ~~an `asyncio.run` per command other than `_run`~~ — `cli.py:496` is the one
  helper; use it (`_run(coro)`), matching `symbols_lookup` at `cli.py:2219`.
- ~~a `--force` flag on `adr generate`~~ — spec §2: not part of v1.
- ~~an interactive review prompt~~ — revision content comes from
  `--edit-file PATH` holding `CandidateEdit` JSON (spec §2 Module 6).
- ~~`--ns all` on a write command~~ — spec §2 Module 6: write commands reject
  `all` and a missing local evidence root.
- ~~an automatic ADR commit on accept~~ — Q3: "Markdown export and committing an
  ADR file are optional." `adr export` prints to **stdout**; it never writes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#upsert",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_ingest_files",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService"
  ]
}
```

---

## Implementation Notes

### Command surface (spec §2 Module 6, verbatim)

```
wikitoolkit adr sync [PATH...]
wikitoolkit adr lookup SYMBOL
wikitoolkit adr why QUESTION
wikitoolkit adr generate TARGET
wikitoolkit adr review ID --action ACTION --expected-revision N --actor ACTOR --reason TEXT
wikitoolkit adr export ID
```

Read commands accept `--include-history`, `--limit`, `--budget`, `--json` and
one `--ns`. `review --action revise` takes `--edit-file PATH`; `--action link`
takes `--documented-id ID`.

### Exit codes (spec §2 "Errors and transport")

| Code | When |
|---|---|
| 0 | successful or **empty** dossier, completed sync, **ambiguous** dossier |
| 1 | failed operation, or a sync/generation that produced error diagnostics |
| 2 | invalid arguments |

An ambiguous dossier is a valid read result — exit 0. JSON mode emits the typed
result, or `{"error": {"code": ..., "message": ...}}`.

### Post-ingest refresh

Spec §2 Module 6: wire it "after deletions, avoiding recursive refresh during
structural read repair. A missing ADR config/file is a no-op, never a model
call."

---

## Implementation Blueprint

### Steps (in order)

1. Write `decisions/cli.py` as a standalone click group — *why*: keeping the six
   commands out of the 187 KB `cli.py` limits this task's blast radius on a file
   spec §7 says has one owner.
2. Register it with two lines in `cli.py` — *why*: `@wiki.group` needs the parent
   group object, so registration must happen in `cli.py`.
3. Wire the post-ingest refresh — *why*: it must run after deletion handling, so
   it goes at the end of the build/upsert bodies.
4. Add the note/remember guards last — *why*: they are independent of everything
   above and easiest to verify in isolation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py` (CREATE)

```python
"""``wikitoolkit adr`` — the maintainer surface for the decision plane (FEAT-578).

This module is the ONLY place a candidate can be accepted. Review is
deliberately absent from every agent-facing surface (spec §2, AC11).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from parrot.knowledge.wiki.decisions.models import (
    ADR_INVALID_ARGUMENT,
    CandidateEdit,
    DecisionError,
    ReviewRequest,
)
from parrot.knowledge.wiki.decisions.render import render_dossier_text
from parrot.knowledge.wiki.decisions.review import render_export
from parrot.knowledge.wiki.decisions.service import DecisionService

#: Exit codes (spec §2 "Errors and transport").
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID_ARGUMENT = 2


def _emit_error(exc: DecisionError, as_json: bool) -> int:
    """Print a typed failure and return its exit code.

    Errors go to stderr so stdout stays protocol-safe for ``--json``
    consumers (spec §4 ``test_cli_mcp_parity``: "stdout remains
    protocol-safe").
    """
    payload = {"error": {"code": exc.code, "message": exc.message}}
    if exc.decision_id:
        payload["error"]["decision_id"] = exc.decision_id
    click.echo(json.dumps(payload) if as_json else f"{exc.code}: {exc.message}", err=True)
    return EXIT_INVALID_ARGUMENT if exc.code == ADR_INVALID_ARGUMENT else EXIT_FAILED


def _build_service(path_: str | None, namespace: str | None, *, writable: bool) -> DecisionService:
    """Resolve the project and build a namespace-scoped service.

    Raises:
        DecisionError: ``ADR_INVALID_ARGUMENT`` when ``writable`` is set and
            the namespace is ``all`` or there is no local evidence root
            (spec §2 Module 6).
    """
    # FILL IN: reuse cli.py's _resolve_project(path_) for (root, config), build
    # the store the way the symbols commands do, scope it by `namespace`, and
    # construct DecisionService(store, root, config.decisions,
    # structural=StructuralService(...)). Refuse namespace == "all" for ANY
    # command and, when writable, refuse a missing local root. Bounded by
    # spec §2 Module 6's namespace paragraph.
    raise NotImplementedError


@click.group(name="adr")
def adr() -> None:
    """Architectural decisions: ingest ADRs, look them up, and review candidates."""


def _read_options(func):
    """Shared options for the two read commands (spec §2 Module 6)."""
    func = click.option("--include-history", is_flag=True, help="Include rejected/deprecated/superseded records.")(func)
    func = click.option("--limit", default=10, type=int, show_default=True, help="Maximum hits (1-50).")(func)
    func = click.option("--budget", default=3000, type=int, show_default=True, help="Token budget (min 256).")(func)
    func = click.option("--json", "as_json", is_flag=True, help="Emit the typed result as JSON.")(func)
    func = click.option("--ns", "namespace", default=None, help="Namespace to read ('all' is not supported).")(func)
    return func


@adr.command("sync")
@click.argument("paths", nargs=-1)
@click.option("--path", "path_", default=None, help="Project root.")
@click.option("--json", "as_json", is_flag=True, help="Emit the SyncResult as JSON.")
def adr_sync(paths: tuple[str, ...], path_: str | None, as_json: bool) -> None:
    """Refresh ADR records from source. Never invokes a model."""
    # FILL IN: build a writable service; _run(service.sync(list(paths) or None));
    # print the counts (or JSON); exit EXIT_FAILED when the result carries error
    # diagnostics, else EXIT_OK. Bounded by the exit-code table and AC5.
    raise NotImplementedError


@adr.command("lookup")
@click.argument("symbol")
@click.option("--path", "path_", default=None, help="Project root.")
@_read_options
def adr_lookup(symbol, path_, include_history, limit, budget, as_json, namespace) -> None:
    """Find the decisions that apply to SYMBOL, with citations."""
    # FILL IN: build a read service; _run(service.for_symbol(...)); render with
    # render_dossier_text or JSON; exit 0 for ok/empty/AMBIGUOUS (an ambiguous
    # dossier is a valid read result — spec §2). Bounded by the exit-code table.
    raise NotImplementedError


@adr.command("why")
@click.argument("question")
@click.option("--path", "path_", default=None, help="Project root.")
@_read_options
def adr_why(question, path_, include_history, limit, budget, as_json, namespace) -> None:
    """Answer a 'why' question with cited decision excerpts."""
    # FILL IN: same shape as adr_lookup, calling service.why(question, ...)
    raise NotImplementedError


@adr.command("generate")
@click.argument("target")
@click.option("--path", "path_", default=None, help="Project root.")
@click.option("--json", "as_json", is_flag=True, help="Emit the GenerationResult as JSON.")
def adr_generate(target: str, path_: str | None, as_json: bool) -> None:
    """Generate labeled CANDIDATE rationale for TARGET (a sym: id or a file).

    Requires generation to be enabled and a model configured. Candidates are
    created unreviewed; accepting one is a separate, explicit `adr review`.
    """
    # FILL IN: writable service; _run(service.generate(target)); print created
    # and reused ids distinctly so a no-op rerun is obvious; exit EXIT_FAILED
    # when diagnostics contain an error. Bounded by AC6.
    raise NotImplementedError


@adr.command("review")
@click.argument("decision_id")
@click.option("--action", required=True, type=click.Choice(["accept", "reject", "revise", "link"]))
@click.option("--expected-revision", required=True, type=int, help="Revision you read; guards concurrent edits.")
@click.option("--actor", required=True, help="Who is reviewing, e.g. 'human:jlara'. Attribution is mandatory.")
@click.option("--reason", default="", help="Why.")
@click.option("--edit-file", "edit_file", default=None, type=click.Path(exists=True),
              help="CandidateEdit JSON; required for --action revise.")
@click.option("--documented-id", "documented_id", default=None,
              help="Documented ADR to associate; required for --action link.")
@click.option("--path", "path_", default=None, help="Project root.")
@click.option("--json", "as_json", is_flag=True, help="Emit the updated record as JSON.")
def adr_review(decision_id, action, expected_revision, actor, reason, edit_file, documented_id, path_, as_json) -> None:
    """Accept, reject, revise, or link a decision record.

    Accepting a candidate records the team's agreement. It does NOT turn the
    candidate into documented history: the record stays inferred with an
    unknown source status, and no ADR file is written (Q3, AC11).
    """
    # FILL IN: writable service; load and parse --edit-file into a CandidateEdit
    # for 'revise' (a malformed file is EXIT_INVALID_ARGUMENT); build a
    # ReviewRequest; _run(service.review(request)); on success print the new
    # revision AND a line stating the record is still inferred/unknown, so an
    # operator is never left thinking acceptance rewrote history. Bounded by
    # AC11 and the exit-code table.
    raise NotImplementedError


@adr.command("export")
@click.argument("decision_id")
@click.option("--path", "path_", default=None, help="Project root.")
def adr_export(decision_id: str, path_: str | None) -> None:
    """Print DECISION_ID as Markdown on stdout.

    Writing or committing this output is deliberately outside the feature —
    accepting a candidate in the wiki is sufficient (Q3).
    """
    # FILL IN: read service; load the record via the repository; click.echo
    # render_export(record); DecisionError -> _emit_error
    raise NotImplementedError
```

**Why this shape**: errors go to **stderr** because `--json` output is consumed
by the parity test in TASK-3497, which asserts stdout stays protocol-safe. The
`adr review` success message restating "still inferred / unknown" is a
deliberate operator-facing guard against the exact misreading AC11 exists to
prevent. `_read_options` as a decorator stack mirrors `_store_options` /
`ns_option` already in `cli.py`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — register the group)

```python
# occurrences: 1 (verified: grep -c '@wiki.group(name="symbols")' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# AFTER — insert directly above `@wiki.group(name="symbols")`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2195):

# FEAT-578: the ADR decision plane. Its commands live in decisions/cli.py to
# keep this module's size in check; only the registration is here.
from parrot.knowledge.wiki.decisions.cli import adr as _adr_group

wiki.add_command(_adr_group)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — post-ingest refresh)

```python
# occurrences: 1 (verified: grep -c 'async def _ingest_files(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# Add a helper next to _ingest_files (verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:683),
# then call it at the END of the `build` (line 1401) and `upsert` (line 1670)
# command bodies — AFTER ordinary ingestion and deletion handling:

async def _refresh_adr_plane(store, root: Path, config, paths: list[str] | None = None) -> None:
    """Refresh the ADR decision plane after ordinary ingestion (FEAT-578).

    A no-op when the feature is disabled or no ADR source exists. NEVER
    generates candidates and never invokes a model — an ordinary build stays
    fully offline (AC5).
    """
    if not config.decisions.enabled:
        return
    from parrot.knowledge.wiki.decisions.ingest import refresh_decisions

    try:
        result = await refresh_decisions(store, root, config.decisions, paths)
    except Exception as exc:  # noqa: BLE001 — a build must not fail on the ADR plane
        logger.warning("ADR refresh skipped: %s", exc)
        return
    # FILL IN: log the counts at info level and each diagnostic at warning
    # level, staying silent under the commands' existing --quiet flag.
    raise NotImplementedError
```

Call it as the **last** step of `build` and `upsert`.

**Why**: wrapping the whole refresh in a `try` is deliberate — a broken ADR file
must never fail an ordinary `wikitoolkit build`, which is what AC10 ("existing
code/document search ... tests pass") protects. The import is function-local so
that `cli.py`'s import time is unchanged when the feature is off, and so the
structural read-repair path (which can re-enter ingestion) cannot recurse into
a module-level ADR import (spec §2 Module 6: "avoiding recursive refresh during
structural read repair").

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — note/remember guards)

```python
# occurrences: 1 each (verified: grep -c '^def note(' and '^def remember(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# INSIDE `note` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3470)
# and `remember` (verified: :3330), immediately after the target page is loaded
# and before it is written:

    from parrot.knowledge.wiki.tools import _reject_managed_page

    managed = _reject_managed_page(page, page_id)
    if managed:
        click.echo(managed, err=True)
        raise SystemExit(2)
```

**Why**: TASK-3495 guarded the tool and toolkit surfaces; the CLI reaches the
same store, so leaving it open would leave the hole open. Exit 2 because writing
to a managed page is an invalid argument, not a failed operation.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli.py` (CREATE)

```python
"""adr CLI surface, exit codes and JSON envelope (FEAT-578 M6)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCommandSurface:
    def test_adr_group_is_registered(self, runner):
        result = runner.invoke(wiki, ["adr", "--help"])
        assert result.exit_code == 0
        for command in ("sync", "lookup", "why", "generate", "review", "export"):
            assert command in result.output

    def test_review_requires_attribution(self, runner):
        """Attribution is mandatory — no anonymous acceptance (spec §2)."""
        result = runner.invoke(wiki, ["adr", "review", "adr:candidate:a", "--action", "accept",
                                      "--expected-revision", "1"])
        assert result.exit_code == 2  # click: missing --actor

    def test_revise_requires_an_edit_file(self, runner, adr_repo):
        # FILL IN: assert `adr review ... --action revise` without --edit-file
        # exits 2
        raise NotImplementedError

    def test_link_requires_documented_id(self, runner, adr_repo):
        # FILL IN: assert `--action link` without --documented-id exits 2
        raise NotImplementedError


class TestExitCodes:
    def test_empty_dossier_exits_zero(self, runner, adr_repo):
        # FILL IN: `adr lookup sym:nope.py#gone --json` exits 0 with
        # status == "empty"
        raise NotImplementedError

    def test_ambiguous_dossier_exits_zero(self, runner, adr_repo):
        """spec §2: an ambiguous dossier is a valid read result."""
        # FILL IN: look up a duplicated bare name; assert exit 0 and
        # status == "ambiguous" with alternatives present
        raise NotImplementedError

    def test_invalid_argument_exits_two(self, runner, adr_repo):
        """--ns all is rejected in v1 (spec §2 Module 6)."""
        result = runner.invoke(wiki, ["adr", "why", "why", "--ns", "all", "--json", "--path", str(adr_repo)])
        assert result.exit_code == 2

    def test_sync_with_error_diagnostics_exits_one(self, runner, adr_repo):
        # FILL IN: make one ADR unreadable; assert `adr sync` exits 1 and still
        # reports the records it did persist
        raise NotImplementedError

    def test_generate_without_a_model_exits_one(self, runner, adr_repo, monkeypatch):
        # FILL IN: with generation disabled, assert exit 1 and an
        # ADR_MODEL_UNCONFIGURED error envelope
        raise NotImplementedError


class TestJsonEnvelope:
    def test_error_envelope_shape(self, runner, adr_repo):
        result = runner.invoke(wiki, ["adr", "why", "q", "--ns", "all", "--json", "--path", str(adr_repo)])
        payload = json.loads(result.stderr or result.output)
        assert set(payload) == {"error"}
        assert payload["error"]["code"] == "ADR_INVALID_ARGUMENT"

    def test_stdout_stays_protocol_safe(self, runner, adr_repo):
        """Errors go to stderr so --json stdout is always parseable."""
        # FILL IN: assert a successful `adr lookup --json` writes ONLY valid
        # JSON to stdout, with logs/warnings on stderr
        raise NotImplementedError


class TestPostIngestRefresh:
    def test_build_refreshes_the_adr_plane(self, runner, adr_repo):
        # FILL IN: run `wikitoolkit build` on adr_repo; assert adr: pages exist
        # afterwards without a separate `adr sync`
        raise NotImplementedError

    def test_build_makes_zero_llm_calls(self, runner, adr_repo, monkeypatch):
        """AC5: an ordinary build is fully offline."""
        # FILL IN: monkeypatch LLMFactory.create to raise; assert build succeeds
        raise NotImplementedError

    def test_a_broken_adr_never_fails_the_build(self, runner, adr_repo):
        """AC10: the ADR plane cannot break ordinary ingestion."""
        # FILL IN: write an undecodable ADR; assert `build` still exits 0
        raise NotImplementedError

    def test_upsert_refreshes_changed_paths(self, runner, adr_repo):
        # FILL IN: build, edit one ADR, `upsert docs/adr/<that>.md`; assert the
        # record was updated
        raise NotImplementedError


class TestCliManagedPageGuard:
    def test_cli_note_refuses_an_adr_page(self, runner, adr_repo):
        # FILL IN: build, then `wikitoolkit note adr:doc:<id> "text"`; assert
        # exit 2 and that the record still decodes
        raise NotImplementedError


class TestAcceptance:
    def test_maintainer_wiki_acceptance(self, runner, adr_repo):
        """AC11 through the operator surface — the Q3 acceptance path."""
        # FILL IN: generate a candidate with a fake client, then
        # `adr review <id> --action accept --expected-revision 1 --actor
        # human:m --reason ok`; assert exit 0, that the stored record is
        # review_status='accepted' with origin='inferred' and
        # source_status='unknown', that NO ADR file was written to adr_repo,
        # and that the output says the record is still inferred
        raise NotImplementedError

    def test_stale_revision_exits_one(self, runner, adr_repo):
        # FILL IN: assert a wrong --expected-revision exits 1 with
        # ADR_REVISION_CONFLICT
        raise NotImplementedError

    def test_export_writes_nothing_to_disk(self, runner, adr_repo):
        """Q3: export prints; committing is the operator's choice."""
        # FILL IN: snapshot the repo file list, run `adr export <id>`, assert
        # stdout has the Markdown and the file list is unchanged
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `decisions/cli.py::_build_service` — project/namespace resolution + write refusals; bounded by spec §2 Module 6
- [ ] `decisions/cli.py` — six command bodies; bounded by the exit-code table
- [ ] `cli.py::_refresh_adr_plane` — logging + quiet handling; bounded by AC5 / AC10
- [ ] `cli.py` — the `_refresh_adr_plane` call sites at the end of `build` and `upsert`
- [ ] `test_cli.py` — seventeen test bodies

---

## Acceptance Criteria

- [ ] All six `adr` commands exist with the options spec §2 Module 6 lists
- [ ] Exit 0 for successful, empty **and ambiguous** dossiers and completed sync; 1 for failures and error diagnostics; 2 for invalid arguments
- [ ] `--json` emits the typed result or `{"error": {"code", "message"}}`, with errors on **stderr** so stdout stays protocol-safe
- [ ] `--ns all` is rejected with `ADR_INVALID_ARGUMENT`; write commands also refuse a missing local root
- [ ] `adr review` requires `--actor`; `revise` requires `--edit-file`; `link` requires `--documented-id`
- [ ] Acceptance succeeds with no ADR file written, and the output states the record is still inferred/unknown (AC11, Q3)
- [ ] A stale `--expected-revision` exits 1 with `ADR_REVISION_CONFLICT`
- [ ] `adr export` prints to stdout and writes nothing to disk (Q3)
- [ ] `build` and `upsert` refresh the ADR plane **after** ingestion and deletion handling
- [ ] An ordinary `build` makes zero LLM calls (AC5) and cannot be failed by a broken ADR (AC10)
- [ ] CLI `note` / `remember` refuse a managed ADR page (exit 2)
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q` still passes (AC10)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_ingest_jira.py -q`

---

## Agent Instructions

1. **Read the spec** §2 Module 6, "Errors and transport", §8 Q3, and AC5/AC10/AC11.
2. **Read `cli.py:2195-2280`** (the `symbols` group) before writing — it is the pattern to copy.
3. **Verify the Codebase Contract** — confirm `cli.py:496`, `:683`, `:1401`, `:1670`, `:2195`, `:3330`, `:3470`.
4. **Implement** from the blueprint; complete every `# FILL IN:`. Touch only the four insertion points in `cli.py`.
5. **Verify** all three Validation Commands pass — the last two are the AC10 regression guard.
6. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
7. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
