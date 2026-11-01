# TASK-5095: `parrot sdd <noun> <verb>` — noun groups and passthrough verbs replace `parrot sdd run`

**Feature**: FEAT-633 — parrot-installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.8, amendment C26 — proposal rev 0.9)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4085, TASK-4086, TASK-4091, TASK-4509, TASK-5092 (all `done` except 5092 — the dev refresh must land first; the others own the files this task rewrites)
**Assigned-to**: unassigned

---

## Context

Amendment C26 (decided 2026-11-01 while PR #1823 is open) removes the generic `parrot sdd run <module>`
dispatcher that TASK-4091 shipped: `run` carries no meaning and `<module>` is a Python file name. The CLI
becomes one click group per SDD object with the helpers mounted as verbs; parsing stays with each helper's
argparse. This task is the kernel every other C26 task builds on: TASK-5096 adds `spec consequences`,
TASK-5097 moves the hook line, TASK-5098 rewrites the shipped markdown, TASK-5099 mounts `ledger`, TASK-5100
mounts `launch`, TASK-5101 documents. **No alias and no deprecation window** (C26 decision): `parrot sdd run`
becomes an unknown command.

---

## Scope

- Rewrite `packages/ai-parrot/src/parrot/sdd/cli.py`: delete `available_helpers()` and `run`; add the
  command ↔ module table `VERBS`, the passthrough factory `_mount()` and `mounted_modules()`; create the noun
  groups `worktree task ids spec brief docs tests closeout hooks` under `sdd` from the table.
- Give `worktree_status.main` and `worktree_environment.main` an `argv: Sequence[str] | None = None`
  parameter forwarded to their `parser.parse_args(argv)` so the passthrough can call `main([...])`.
- Replace the four `test_run_*` tests in `packages/ai-parrot/tests/sdd/test_sdd_cli.py` with
  `test_sdd_cli_mounts_every_helper` (mount-completeness + every leaf `--help` exits 0 + `run` unknown) and
  `test_verb_propagates_helper_exit_code`.
- Keep `_UNMOUNTED = frozenset({"insight"})` (C22: `/sdd-insight` is not shipped); TASK-5096 un-ships the module.

**NOT in scope**: the `spec consequences` verb and `insight` removal (TASK-5096); `SDD_HOOK_ARGV`, the
installer's `GUARD_HOOK_LINE` and the agent frontmatter (TASK-5097); any markdown rewrite (TASK-5098); the
`ledger` and `launch` nouns (TASK-5099, TASK-5100); docs (TASK-5101).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | nouns + passthrough verbs; delete `run` / `available_helpers` |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | MODIFY | `main(argv=None)` |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `main(argv=None)` |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | MODIFY | mount-completeness test replaces the `run` tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `feat-FEAT-633-parrot-installer` @ `54868dcb2d` (2026-11-01).

### Verified Imports
```python
import click                                                    # cli.py:12
from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration  # cli.py:14
from click.testing import CliRunner                             # tests/sdd/test_sdd_cli.py:8
from parrot.cli import cli                                      # tests/sdd/test_sdd_cli.py:10
from parrot.sdd.cli import sdd                                  # tests/sdd/test_sdd_cli.py:11
import parrot.sdd.scripts as pkg                                # cli.py:56 (lazy, inside a function)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/cli.py
_HELPER_PACKAGE = "parrot.sdd.scripts"                          # :16
def available_helpers() -> list[str]: ...                       # :53-58  — DELETE
@click.group(name="sdd")                                        # :61
def sdd() -> None: """Spec-Driven Development flow: install / uninstall / status / run."""   # :62-63
@sdd.command(context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})  # :132
def run(name: str, args: tuple[str, ...]) -> None: ...          # :135-148 — DELETE (runpy + sys.argv rewrite)
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py
def main() -> int:                                              # :613 — argparse built inside, `import argparse` at :620
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def main() -> None:                                             # :538
    parser.add_argument("--hook", action="store_true", required=True)   # :541
    parser.parse_args()                                         # :542
# packages/ai-parrot/src/parrot/launcher.py — the fast path calls hook_main() with sys.argv[1:] = ["--hook"] (:276-281); a
# defaulted `argv=None` keeps that call valid. SDD_HOOK_ARGV itself (:269) is TASK-5097's.
# Helper `main` signatures (all accept argv except the two above): list[str] | Sequence[str] | None, e.g.
#   reserve_ids.main(argv: list[str] | None = None) :616 · spec_tools.main(argv: list[str] | None = None) :188
#   sdd_meta.main(argv: Sequence[str] | None = None) :34 · brief_meta.main(argv: Sequence[str] | None = None) :264
#   test_report.main(argv: list[str] | None = None) :100 · review_checkpoint.main(argv: list[str] | None = None) :84
# Modules WITHOUT main() (libraries, never mounted): closeout_builtins.py, closeout_hooks_config.py.
# Modules without argparse (argv parsed by hand — verified grep -c argparse = 0): close_task.py, heal_orphans.py.
# parrot/cli/__init__.py:192 registers "sdd": "parrot.sdd.cli" in the LazyGroup table — unchanged.
```

### Does NOT Exist
- ~~`parrot.sdd.cli.VERBS` / `_mount` / `mounted_modules` / `_UNMOUNTED`~~ — created by this task.
- ~~`parrot.sdd.scripts.check_spec_consequences`~~ — TASK-5096 packages it; do not mount it here.
- ~~a `launch` or `ledger` noun~~ — TASK-5100 / TASK-5099.
- ~~`worktree_status.main(argv)` / `worktree_environment.main(argv)`~~ — both take no argument today; this task adds it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#sdd",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#run",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#available_helpers",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#main"
  ]
}
```

---

## Implementation Notes

- **Routing is click's, parsing stays argparse's** (C26 item 2). A verb is a click command with
  `add_help_option=False`, `ignore_unknown_options=True`, `allow_interspersed_args=False` and one
  `nargs=-1` `UNPROCESSED` argument, so `--help` and every option reach the helper's own parser untouched.
  Never re-declare a helper option in click.
- The verb prefix is injected for helpers with their own subparsers: `spec init-run …` →
  `spec_tools.main(["init-run", …])`. Helpers whose subparser *is* the verb's own argument (`task review
  prepare|validate`, `tests report render|decide-rerun`) get an empty prefix and keep their argparse subcommand.
- `main()` may return an int, `None`, or raise `SystemExit` (argparse `--help` exits 0). Normalise exactly as
  the old `run` did: int → that code; `None` → 0; anything else → 1.
- `--help` on a noun is click's verb list; the `help=` of each verb (one line, from the table) is what it shows.
- The table is **normative**: TASK-5098's rewrite and the C22 scanner read it from `parrot.sdd.cli.VERBS`, so
  its spelling is the spelling that ships. Do not rename a verb without amending C26.

---

## Implementation Blueprint

### Steps (in order)
1. Add `argv` to the two `main()`s — *why*: the passthrough calls `main(list)`; the hook fast path still calls `hook_main()` with no argument.
2. Replace `available_helpers` + `run` in `cli.py` with the table, the factory and the nouns — *why*: C26 item 1/2.
3. Rewrite the module docstring and the `sdd` group docstring (`install / uninstall / status / run` → `install / uninstall / status, <noun> <verb>`) — *why*: `parrot sdd --help` is the documentation.
4. Replace the four `test_run_*` tests — *why*: the mount-completeness gate is C26 item 3.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def main() -> None:' packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py)
# REPLACE `def main() -> None:` (verified: :538) with
def main(argv: Sequence[str] | None = None) -> None:
# and `parser.parse_args()` (verified: :542, 1 occurrence) with
    parser.parse_args(argv)
# FILL IN: add `from typing import Sequence` (or `collections.abc`) only if the module does not import it — the module is
# stdlib-only and must stay so (C16/C19); verify with grep before adding.
```
**Why**: the hook keeps working from the launcher fast path (`hook_main()` → `argv=None` → `sys.argv`), and the
`worktree guard --hook` verb can call `main(["--hook"])`.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def main() -> int:' packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py)
# REPLACE `def main() -> int:` (verified: :613) with
def main(argv: Sequence[str] | None = None) -> int:
# FILL IN: forward `argv` to the single `parser.parse_args(...)` call inside main (locate it with
# `grep -n 'parse_args' …/worktree_status.py`; if the count is not 1, quote 2–3 lines of context in the Completion Note).
```
**Why**: same contract as every other helper: `main(argv)`.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY — replace lines 53-58 and 132-148)
```python
import importlib  # replaces `import pkgutil` / `import runpy`; keep `import pkgutil` for mounted_modules()

#: C26 item 1 — normative command ↔ module map: noun → verb → (module, argv prefix, one-line help).
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {
    "worktree": {
        "ensure": ("ensure_worktree", (), "Create or reuse the feature/hotfix worktree (idempotent)."),
        "status": ("worktree_status", (), "Discover SDD worktrees and report task state and health."),
        "guard": ("worktree_environment", (), "Serve the PreToolUse shared-environment guard (--hook)."),
    },
    "task": {
        "close": ("close_task", (), "Close a task: move it to completed/ and stamp the per-spec index."),
        "finalize": ("finalize_task", (), "Finalize a task from its evidence file."),
        "heal": ("heal_orphans", (), "Re-attach orphaned task files to their per-spec index."),
        "graph": ("check_task_graph", (), "Validate a per-spec index task graph."),
        "state": ("check_task_state", (), "Read-only backstop for stalled task files."),
        "review": ("review_checkpoint", (), "Review checkpoint: prepare | validate."),
    },
    "ids": {
        "reserve": ("reserve_ids", (), "Reserve TASK/FEAT ids on the git-native ledger."),
        "check": ("check_id_collisions", (), "Scan for TASK/FEAT id collisions."),
        "ledger": ("id_ledger", (), "Inspect or bootstrap the TASK/FEAT id counter."),
    },
    "spec": {
        **{v: ("spec_tools", (v,), f"spec_tools {v}") for v in (
            "init-run", "render-brief", "stamp-run", "validate-suggestions", "check-path",
            "commit-intake", "existing-feature-id")},
        "prune-intake": ("prune_intake", (), "Prune stale /sdd-spec intake staging."),
    },
    "brief": {v: ("brief_meta", (v,), f"brief_meta {v}") for v in ("plan", "write-index")},
    "docs": {
        **{v: ("sdd_meta", (v,), f"Document flow metadata: {v}") for v in ("parse", "taxonomy", "resolve-flow")},
        "list": ("doc_taxonomy", (), "List SDD docs by projects/tags frontmatter."),
        "backfill": ("backfill_taxonomy", (), "Infer projects frontmatter for existing SDD docs."),
        "migrate-index": ("migrate_index", (), "One-shot monolith → per-spec index migration."),
    },
    "tests": {
        "select": ("select_tests", (), "Select the tests a task/feature must run."),
        "report": ("test_report", (), "Test report: render | decide-rerun."),
        "contract": ("cache_test_contract", (), "Cache a spec's Validation Contract into its index."),
        "e2e-closeout": ("check_e2e_closeout", (), "E2E evidence gate for the closeout surfaces."),
    },
    "closeout": {
        "run": ("run_closeout_hooks", (), "Dispatch /sdd-done closeout hooks."),
        "resolve-issues": ("close_resolved_issues", (), "Close the ledger issues a finished feature fixed."),
    },
    "hooks": {"install": ("install_hooks", (), "Install the SDD git hooks.")},
}
#: Packaged modules with a main() that are deliberately NOT mounted (C22: /sdd-insight does not ship).
_UNMOUNTED: frozenset[str] = frozenset({"insight"})
_PASSTHROUGH = {"ignore_unknown_options": True, "allow_interspersed_args": False}


def mounted_modules() -> set[str]:
    """Every `parrot.sdd.scripts` module reachable through a verb (the mount-completeness gate reads this)."""
    return {module for verbs in VERBS.values() for module, _, _ in verbs.values()}


def _mount(noun: click.Group, verb: str, module: str, prefix: tuple[str, ...], help_: str) -> None:
    """Mount `noun verb [args…]` → `parrot.sdd.scripts.<module>.main([*prefix, *args])` (C26 item 2)."""

    @noun.command(name=verb, help=help_, add_help_option=False, context_settings=_PASSTHROUGH)
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def _verb(args: tuple[str, ...]) -> None:
        main = importlib.import_module(f"{_HELPER_PACKAGE}.{module}").main
        try:
            code = main([*prefix, *args])
        except SystemExit as exc:  # the helper's own exit (argparse --help exits 0)
            code = exc.code
        raise click.exceptions.Exit(code if isinstance(code, int) else (0 if code is None else 1))


for _noun, _verbs in VERBS.items():
    _group = sdd.group(name=_noun, help=f"SDD {_noun} helpers.")(lambda: None)
    for _verb, (_module, _prefix, _help) in _verbs.items():
        _mount(_group, _verb, _module, _prefix, _help)
```
**Why this shape**: the table is data, so TASK-5098's rewrite and the mount test consume the same source of
truth; `add_help_option=False` is what lets `--help` reach argparse (C26: a verb's help is the helper's help);
`importlib` replaces `runpy` so no `sys.argv` is rewritten and the helper's exit code is forwarded unchanged.
Place the block after `status` (the `run` command's position) so the group is defined before the loop runs.

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (MODIFY — replace `test_run_*`, lines 83-105)
```python
import importlib, pkgutil

from parrot.sdd.cli import VERBS, _UNMOUNTED, mounted_modules


def test_sdd_cli_mounts_every_helper() -> None:
    """C26 item 3: mounted modules == packaged modules with main() minus _UNMOUNTED; every leaf --help exits 0."""
    import parrot.sdd.scripts as pkg

    with_main = {
        m.name for m in pkgutil.iter_modules(pkg.__path__)
        if not m.ispkg and hasattr(importlib.import_module(f"parrot.sdd.scripts.{m.name}"), "main")
    }
    assert mounted_modules() == with_main - _UNMOUNTED
    for noun, verbs in VERBS.items():
        for verb in verbs:
            result = CliRunner().invoke(cli, ["sdd", noun, verb, "--help"])
            assert result.exit_code == 0, (noun, verb, result.output)
    assert CliRunner().invoke(cli, ["sdd", "run", "reserve_ids", "--help"]).exit_code == 2  # no alias (C26)


def test_verb_propagates_helper_exit_code() -> None:
    result = CliRunner().invoke(cli, ["sdd", "ids", "reserve", "--kind", "bogus"])
    assert result.exit_code == 2  # argparse usage error, forwarded unchanged
```
**Why**: the first test is the gate C26 names; the second keeps the exit-code contract the deleted
`test_run_propagates_helper_exit_code` covered.

### FILL IN checklist
- [ ] `close_task.py` / `heal_orphans.py` — no argparse: if `main(["--help"])` does not exit 0, add a two-line `--help` branch that prints the module docstring and returns 0; bounded by AC-2.
- [ ] `test_sdd_cli.py::test_portable_flag` still asserts the OLD hook string — leave it; TASK-5097 changes it.
- [ ] `worktree_status.py` — locate the single `parse_args` call; bounded by AC-3.

---

## Acceptance Criteria
- [ ] AC-1 `parrot sdd --help` lists `install uninstall status` and the nouns `worktree task ids spec brief docs tests closeout hooks`; `parrot sdd run …` exits 2 (unknown command).
- [ ] AC-2 `test_sdd_cli_mounts_every_helper` passes: 26 mounted modules (27 with `main()` minus `insight`), every leaf `--help` exits 0.
- [ ] AC-3 `parrot sdd worktree status --json` and `parrot sdd worktree guard --hook` behave exactly as `parrot sdd run worktree_status --json` / `… worktree_environment --hook` did (same output, same exit codes; the launcher fast-path tests still pass unchanged).
- [ ] AC-4 `ruff check packages/ai-parrot/src/parrot/sdd/cli.py` clean; no `runpy`, no `sys.argv` assignment left in `cli.py`.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/launcher/test_launcher_sdd_hook.py -q`

---

## Test Specification
```python
# packages/ai-parrot/tests/sdd/test_sdd_cli.py — see the blueprint: test_sdd_cli_mounts_every_helper,
# test_verb_propagates_helper_exit_code. Keep every other existing test in the file untouched.
```

---

## Agent Instructions
- Work inside `.claude/worktrees/feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
- Touch only the four files listed. Do not edit any markdown, `_assets`, `launcher.py` or `installer.py` —
  other C26 tasks own them and `check_asset_sync --check` must stay green after this task.
- Commit: `feat(parrot-installer): TASK-5095 — parrot sdd noun groups replace run`.

---

## Completion Note
_(filled by the implementer)_
