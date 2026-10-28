# TASK-4863: Ledger outbox recovery/migration docs and end-to-end acceptance suite

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4860, TASK-4862
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and §4 "Integration Tests". Operators need a documented procedure for the four recovery
paths (hook migration, legacy contaminated feature diffs, crash-retry, unavailable source machine), and the
feature needs an end-to-end suite that drives the real CLI against private bare repositories — two linked
worktrees and two independent clones — to prove the acceptance criteria together rather than per module.
The FEAT-694 cheatsheet paragraph still describes the pre-commit export and done-time rotation; it is
corrected here.

---

## Scope

- Create `docs/sdd/ledger-outbox.md`: model (journal → sealed batch → integrator → `origin/dev`), the three CLI
  commands and exit codes, outbox layout, and these procedures:
  1. **Migrate installed hooks** → `parrot claude install` (upgrades the `parrot-ledger` block) → seal legacy
     local events (`outbox prepare`) → deliver (`outbox integrate`) → verify remote content.
  2. **Legacy feature diff** (`outbox status` exit 4 / `contaminated_paths`): back up the branch's ledger
     files, import missing events into the local journal (`ledger import-log --repo-root <worktree>`), deliver,
     then a reviewed, scoped cleanup restoring ONLY `sdd/ledger/events.jsonl` and `sdd/ledger/issues.jsonl` to
     their merge-base contents (`git restore --source "$(git merge-base origin/dev HEAD)" -- <those two paths>`)
     and committing it. Never restore the whole `sdd/ledger/` directory (ID allocator and archives are outside
     scope). Never rewrite already-published history automatically.
  3. **Retry after crash** → `outbox integrate --batch-id <id>`; remote verification makes it idempotent.
  4. **Source machine unavailable** → pending events exist only in that machine's journal/outbox; recover from
     its backup of `<ledger-dir>/events.jsonl` and `<ledger-dir>/outbox/`.
  Also: log rotation is explicit maintenance (`wikitoolkit ledger rotate-log`), no longer run by `/sdd-done`;
  direct pushes to `dev` blocked by server policy leave delivery pending (no fallback to `main`).
- Edit the FEAT-694 paragraph of `docs/wiki/cheatsheet.md` so it no longer claims the hooks export or that
  rotation runs in `/sdd-done` step 9.1, and link the new doc.
- Create `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py` covering spec §4
  Integration rows not already proven by TASK-4859's unit-level Git tests, driving the **CLI** via
  `CliRunner` with `--ledger-dir` pointed at private ledgers.

**NOT in scope**: changing any source module (if a scenario fails, report it in the Completion Note and file a
ledger issue — do not fix other tasks' code here); running anything against the project's real remote.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/sdd/ledger-outbox.md` | CREATE | Operating model + recovery/migration matrix |
| `docs/wiki/cheatsheet.md` | MODIFY | Correct the FEAT-694 shared-log paragraph |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py` | CREATE | End-to-end CLI acceptance |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from click.testing import CliRunner                      # used by tests/knowledge/wiki/test_cli_ledger_shared_log.py:9
from parrot.knowledge.wiki.cli import ledger             # cli.py:3223 (group)
from parrot.knowledge.wiki.ledger.events import LedgerEvent   # events.py:103
from parrot.knowledge.wiki.ledger.log import LedgerLog        # log.py:10
from parrot.knowledge.wiki.ledger.service import LedgerService  # service.py:149
# created by earlier FEAT-758 tasks:
from parrot.knowledge.wiki.ledger.outbox import LedgerOutbox       # TASK-4857
from parrot.knowledge.wiki.claude_code.installer import _install_ledger_hooks  # installer.py:973 (upgraded by TASK-4861)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
async def open_issue(self, title: str, body: str, kind: IssueKind = "bug", severity: str = "minor",
                     discovered_from: str = "", about: list[str] | None = None, actor: str = "agent:sdd") -> str:  # :243
@classmethod
def from_dir(cls, ledger_dir: Path, *, sqlite_policy=None) -> "LedgerService":  # :197
```
CLI surface (TASK-4860): `ledger outbox prepare|status|integrate --repo-root PATH --ledger-dir PATH [--json]`,
exit 0/2/3/4. Monkeypatch `parrot.knowledge.wiki.remote_cli.remote_or_none` → `(None, None, None)` exactly as
`tests/knowledge/wiki/test_cli_ledger_shared_log.py:18` does.

Cheatsheet anchor (occurrences: 1, verified `docs/wiki/cheatsheet.md:258`):
`(`.gitattributes`). The four `parrot-ledger` git hooks (pre-commit, post-merge, post-checkout,`

### Does NOT Exist
- ~~`docs/sdd/ledger-outbox.md`~~ — created here.
- ~~a parrot-e2e target for this feature~~ — spec §4: pytest Git integration suite, no E2E policy metadata.
- ~~`wikitoolkit ledger outbox discard`~~ — no discard/force-ack operation (spec §2 step 6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/sdd/ledger-outbox.md", "action": "CREATE"},
    {"path": "docs/wiki/cheatsheet.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.open_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_ledger_hooks"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the acceptance suite first and run it — *why*: the doc must describe behavior that was observed.
2. Write `docs/sdd/ledger-outbox.md` — *why*: AC "recovery documentation is complete".
3. Correct the cheatsheet paragraph — *why*: it currently documents the superseded FEAT-694 transport.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py` (CREATE)
```python
"""FEAT-758 M6 — end-to-end acceptance: linked worktrees, independent clones, hotfix, migration."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.service import LedgerService

@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))


@pytest.fixture
def origin_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    # FILL IN: bare origin with `dev` + `main` branches and an initial commit containing sdd/ledger/ (empty
    #   events.jsonl + issues.jsonl); clone with user.name/email configured. Never use the project remote.
    raise NotImplementedError


def _cli(*args: str) -> "object":
    return CliRunner().invoke(ledger, list(args))


def test_two_linked_worktrees_findings_never_enter_feature_diffs(origin_and_clone, tmp_path) -> None:
    # FILL IN: two `git worktree add` feature branches; open an issue from each via
    #   LedgerService.from_dir(<shared ledger>); commit code in both; assert
    #   `git diff --name-only origin/dev...<branch>` has no sdd/ledger paths; prepare+integrate once ->
    #   both events on origin/dev exactly once.


def test_new_event_after_seal_waits_for_next_pass(origin_and_clone, tmp_path) -> None:
    # FILL IN: prepare; append event; integrate -> receipt covers only captured ids, status shows 1 unsealed;
    #   second prepare+integrate delivers it.


def test_feature_worktree_removed_externally_batch_still_deliverable(origin_and_clone, tmp_path) -> None:
    # FILL IN: prepare from a linked worktree, `git worktree remove` it, integrate with --repo-root <primary>.


def test_hotfix_on_main_delivers_only_to_dev(origin_and_clone, tmp_path) -> None:
    # FILL IN: branch from origin/main; prepare+integrate; origin/main sha unchanged, origin/dev has the event.


def test_foreign_remote_event_survives_snapshot_regeneration(origin_and_clone, tmp_path) -> None:
    # FILL IN: push an event to origin/dev from a second clone this ledger never saw; deliver a local batch;
    #   issues.jsonl on origin/dev still contains the foreign issue.


def test_mixed_archive_and_current_log_no_rotation(origin_and_clone, tmp_path) -> None:
    # FILL IN: origin/dev has sdd/ledger/archive/events-2026_09.jsonl + current log with one duplicated line;
    #   delivery succeeds and archive bytes are unchanged.


def test_stale_hook_cannot_stage_events(origin_and_clone, tmp_path) -> None:
    # FILL IN: install an OLD pre-commit hook text calling `<wikitoolkit> ledger export-log --stage --quiet`
    #   (stub bin -> python -m parrot.knowledge.wiki.cli is NOT required: invoke _cli("export-log","--stage")
    #   directly) -> exit 4, nothing staged; then _install_ledger_hooks upgrades it to the no-op block.
```
**Why**: the seven tests map to spec §4 Integration rows "two linked worktrees", "new event after seal",
"feature worktree deleted externally", "hotfix based on main", "foreign event never seen locally",
"mixed archives/current log" and AC "old --stage commands cannot reintroduce tracked events"; two-clone races,
lost receipts, hook mutation and retry exhaustion are already proven in TASK-4859. Bound every Git subprocess with
`timeout=` instead of adding a pytest plugin (spec AC: no new dependency).

### `docs/sdd/ledger-outbox.md` (CREATE)
```markdown
# Ledger outbox (FEAT-758)

## Model
<!-- FILL IN: journal (<ledger-dir>/events.jsonl, resolved by LedgerService.from_root) -> sealed batch
     (<ledger-dir>/outbox/pending/<uuid>/) -> integrator (temporary checkout of origin/dev) -> receipt
     (<ledger-dir>/outbox/receipts/<uuid>.json, written only after remote verification). Feature PRs carry
     code and task artifacts only. -->

## Commands and exit codes
<!-- FILL IN: prepare / status / integrate, flags, 0/2/3/4 table -->

## Recovery and migration
### Migrate installed hooks
### Legacy feature diff
### Retry after a crash
### Source machine unavailable
<!-- FILL IN: the four procedures from this task's Scope, with exact commands -->

## Limits
<!-- FILL IN: no distributed claims; conflicts need review; no auto rotation; dev push policy; remote-only
     MCP ledgers are unsupported; back up <ledger-dir>/ — no PR is its backup anymore -->
```

### `docs/wiki/cheatsheet.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'The four `parrot-ledger` git hooks (pre-commit, post-merge, post-checkout,' docs/wiki/cheatsheet.md)
     REPLACE lines 258-263 (from "(`.gitattributes`). The four" through "install the hooks.") with: -->
(`.gitattributes`). The `parrot-ledger` post-merge, post-checkout and post-rewrite hooks import it into the
local ledger; the pre-commit block is a no-op since FEAT-758 — events reach `origin/dev` only through
`/sdd-done`'s outbox delivery (`wikitoolkit ledger outbox prepare|status|integrate`, see
`docs/sdd/ledger-outbox.md`). `wikitoolkit ledger rotate-log --older-than-days N` is explicit maintenance;
`/sdd-done` no longer rotates. Existing checkouts: re-run `parrot claude install` once to upgrade the hooks.
```

### FILL IN checklist
- [ ] Fixture + 7 acceptance tests — bounded by spec §4 Integration Tests
- [ ] Doc sections — bounded by spec §3 M6 interface skeleton (four procedures)
- [ ] Cheatsheet paragraph

---

## Acceptance Criteria

- [ ] Every spec §4 Integration row is covered here or in TASK-4859's tests (list the mapping in the Completion Note)
- [ ] Docs describe migration, legacy cleanup (two paths only), crash retry and machine loss
- [ ] Full FEAT-758 validation contract passes (see below)
- [ ] No source module changed by this task

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_acceptance.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py -q`

---

## Test Specification

See the blueprint above. Save the run log under `artifacts/logs/`.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4860 and TASK-4862 must be `done` (transitively all earlier tasks).
2. Read spec §3 Module 6 and §4.
3. Implement tests first; if a scenario fails because of another task's code, stop, record it in the
   Completion Note and `wikitoolkit ledger open` it — do not patch source here.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; commit only the three files.
5. Close with `scripts/sdd/close_task.sh TASK-4863 ledger-outbox-integration verified`.

---

## Completion Note

*(Agent fills this in when done)*
