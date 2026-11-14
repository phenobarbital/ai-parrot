# TASK-5643: `parrot sdd procedure` — build, list, show, check, and the config section

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5635, TASK-5636, TASK-5640, TASK-5641
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (first half) and §2 "New Public Interfaces". This task creates the CLI helper
with the four verbs that do not need the resolver, mounts the noun in `parrot sdd`, and adds the
`procedure` section to `SddConfig` (the model forbids extra keys, so the section must exist in the
model before any repository writes it). TASK-5644 adds `next` and `brief`.

---

## Scope

- Create `parrot/sdd/scripts/procedure.py` with `main`, `build`, and the verbs `build`, `list`,
  `show`, `check`.
- Mount the noun `procedure` (those four verbs) in `VERBS` in `parrot/sdd/cli.py`.
- Add `ProcedureSettings` and `SddConfig.procedure` in `parrot/sdd/config.py`.
- Create `tests/sdd/test_procedure_cli.py`.

**NOT in scope**: `next`, `brief`, `render_brief` (TASK-5644); the packaged manifest (TASK-5647);
the install step (TASK-5648); the wheel-smoke scenario (TASK-5651).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure.py` | CREATE | CLI helper, four verbs |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Mount the `procedure` noun |
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | `ProcedureSettings`, `SddConfig.procedure` |
| `packages/ai-parrot/tests/sdd/test_procedure_cli.py` | CREATE | CLI and config tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Names from TASK-5635 / 5636 / 5640 / 5641 are
> dependency-provided — re-check them after they land.

### Verified Imports
```python
from parrot.sdd.config import SddConfig, SddConfigError, load_sdd_config        # sdd/config.py:25, :21, :278
from parrot.knowledge.wiki.project import find_shared_root                      # wiki/project.py:1563
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProcedureSpec     # TASK-5633
from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs   # TASK-5635
from parrot.knowledge.wiki.procedure.validate import GraphFinding, validate_graph     # TASK-5636
from parrot.knowledge.wiki.procedure.index import is_stale, read_index                # TASK-5639
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane                      # TASK-5640
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS                           # TASK-5641
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {     # :247  noun -> verb -> (module, argv prefix, help)
    ...
    "brief": {v: ("brief_meta", (v,), f"brief_meta {v}") for v in ("plan", "write-index")},   # :304 — the comprehension form to copy
    ...
    "hooks": {                                                         # :327
def _mount(noun, verb, module, prefix, help_) -> None: ...             # :349 — calls parrot.sdd.scripts.<module>.main([*prefix, *args]);
                                                                       #        an int return or SystemExit code becomes the exit code

# packages/ai-parrot/src/parrot/sdd/config.py
class SddConfig(BaseModel):                                            # :25
    model_config = ConfigDict(extra="forbid")                          # :28
    techwiki: TechwikiConfig | None = None                             # :43
def load_sdd_config(root: Path | None = None) -> SddConfig: ...        # :278

# Packaged SDD commands: <package>/parrot/sdd/_assets/claude/commands/sdd-*.md   (from this module:
#   Path(__file__).resolve().parent.parent / "_assets" / "claude" / "commands")

# Dependency-provided (re-check):
def manifest_specs(root: Path) -> tuple[list[ProcedureSpec], list[Path]]          # raises ValueError naming the file
def load_manifest(path: Path, *, root: Path) -> ProcedureManifest                 # .uncovered_ok: list[str]
def validate_graph(specs, *, known_probes, known_commands=()) -> list[GraphFinding]   # .code .severity .subjects .message
class ProcedurePlane:
    def __init__(self, plane_dir: Path) -> None
    async def build(self, specs, sources, *, root: Path, probe_costs) -> dict[str, int]
    async def specs(self) -> list[ProcedureSpec]
def read_index(plane_dir: Path) -> dict[str, Any] | None
def is_stale(document, *, root: Path) -> bool
```

### Does NOT Exist
- ~~`parrot.sdd.scripts.procedure`~~ — this task creates it.
- ~~`SddConfig.procedure`~~ — not a field today; a config file carrying the key fails validation
  until this task lands.
- ~~A `procedure` noun in `VERBS`~~ — this task adds it.
- ~~`click` in the helper~~ — helpers are plain `main(argv) -> int` functions using `argparse`.
- ~~`print`~~ — forbidden by the conventions; write with `sys.stdout.write` / `sys.stderr.write`
  like the other `parrot.sdd.scripts` helpers.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#VERBS",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#_mount",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#SddConfig",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#load_sdd_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Root**: every verb works on the primary checkout, `find_shared_root(Path.cwd())` (`build` also
  accepts `--root`). No repository: one line on stderr, exit 2.
- **`build(root)`** (async): `manifest_specs(root)` → `validate_graph(specs,
  known_probes=PROBE_COSTS)` → when any finding has severity `error`, raise `ValueError` whose
  message lists `code: message` per error → else `ProcedurePlane(root / PLANE_DIR).build(specs,
  sources, root=root, probe_costs=PROBE_COSTS)`. The verb prints `procedure plane: N pages, M
  edges, K sources` and exits 0; a `ValueError` is printed on stderr and exits 1.
- **`check`**: `manifest_specs(root)` (a `ValueError` is one error line, exit 1); `known_commands`
  = stems of the packaged `sdd-*.md` commands minus the union of `uncovered_ok` over
  `load_manifest(path, root=root)` for every source; print one line per finding
  (`<severity> <code> <subjects>: <message>`) or the JSON list with `--json`; exit 1 when any
  finding is an error, else 0. No manifest at all: print `no procedure manifest`, exit 0.
- **Fresh specs for `list` / `show`** (`_load_specs(root) -> tuple[list[ProcedureSpec], bool]`):
  when `is_stale(read_index(plane_dir), root=root)`, try `build(root)`; if that fails (read-only
  directory, invalid manifest), write one line `procedure plane is stale: <reason>` on stderr and
  continue with what the store holds. The boolean is the final stale flag. TASK-5644 reuses it.
- **`list`**: one line per node `<id>  <mode>  <scope_kind>  <title>`, sorted by id; `--mode M`
  filters; `--json` prints the list of `spec.model_dump(mode="json")`.
- **`show <id>`**: the node's fields as readable text (or its JSON with `--json`); unknown id:
  one line on stderr, exit 1.
- `argparse` exits with code 2 on a usage error through `SystemExit`; `_mount` already converts it.
- A corrupt `sdd/config.json` (`SddConfigError`) must not break these verbs: fall back to
  `ProcedureSettings()` and write one warning line on stderr.

---

## Implementation Blueprint

### Steps (in order)
1. Add `ProcedureSettings` and the field to `config.py` — *why*: `extra="forbid"` rejects the key
   otherwise.
2. Write `procedure.py` — *why*: one helper module per noun, `main(argv) -> int`.
3. Mount the noun — *why*: `test_sdd_cli_mounts_every_helper` fails for an unmounted `main()`.
4. Write the tests.

### `packages/ai-parrot/src/parrot/sdd/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class SddConfig(BaseModel):' packages/ai-parrot/src/parrot/sdd/config.py)
# BEFORE — insert above `class SddConfig(BaseModel):` (verified: packages/ai-parrot/src/parrot/sdd/config.py:25)
class ProcedureSettings(BaseModel):
    """Procedure-graph settings (``sdd/config.json`` key ``procedure`` — FEAT-891)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    #: False: the guards never deny a mandatory violation, they advise instead.
    enforce: bool = True
    brief_max_lines: int = 8
    remote_probe_timeout_seconds: int = 5


# occurrences: 1 (verified: grep -c '    techwiki: TechwikiConfig | None = None' packages/ai-parrot/src/parrot/sdd/config.py)
# AFTER — insert below `    techwiki: TechwikiConfig | None = None` (verified: packages/ai-parrot/src/parrot/sdd/config.py:43)
    #: FEAT-891 — procedure-graph settings; ``None`` means defaults.
    procedure: ProcedureSettings | None = None
```
**Why**: same optional-section pattern as `techwiki`. `procedure_advice` reads the raw JSON key,
so the field names here are a contract with it (`enabled`, `enforce`).

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "hooks": {' packages/ai-parrot/src/parrot/sdd/cli.py)
# BEFORE — insert above `    "hooks": {` (verified: packages/ai-parrot/src/parrot/sdd/cli.py:327), inside the VERBS dict
    "procedure": {
        v: ("procedure", (v,), f"Procedure graph: {v}") for v in ("build", "list", "show", "check")
    },
```
**Why**: the verb is passed to the helper as its first argv token (prefix `(v,)`), the same form
the `brief` noun uses. TASK-5644 extends the tuple with `next` and `brief`.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure.py` (CREATE)
```python
"""``parrot sdd procedure`` — build, inspect and check the procedure graph (FEAT-891)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from parrot.knowledge.wiki.procedure.index import is_stale, read_index
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProcedureSpec
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane
from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs
from parrot.knowledge.wiki.procedure.validate import validate_graph
from parrot.knowledge.wiki.project import find_shared_root
from parrot.sdd.config import ProcedureSettings, SddConfigError, load_sdd_config
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "_assets" / "claude" / "commands"


def _settings(root: Path) -> ProcedureSettings:
    """The repository's procedure settings; defaults (plus one stderr line) on an invalid config."""
    # FILL IN


async def build(root: Path) -> dict[str, int]:
    """manifest_specs(primary checkout) -> validate (errors abort with ValueError) -> ProcedurePlane.build."""
    # FILL IN: per Implementation Notes "build(root)".


def _load_specs(root: Path) -> tuple[list[ProcedureSpec], bool]:
    """(specs read from the plane, stale flag); rebuilds first when the plane is stale and writable."""
    # FILL IN: per Implementation Notes "Fresh specs".


def _known_commands(root: Path, sources: Sequence[Path]) -> list[str]:
    """Packaged sdd-* command names minus every manifest's uncovered_ok."""
    # FILL IN


def _cmd_build(args: argparse.Namespace) -> int: ...   # FILL IN
def _cmd_list(args: argparse.Namespace) -> int: ...    # FILL IN
def _cmd_show(args: argparse.Namespace) -> int: ...    # FILL IN
def _cmd_check(args: argparse.Namespace) -> int: ...   # FILL IN


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parrot sdd procedure", description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    p_build = sub.add_parser("build", help="Fold the manifests into the plane and publish the index.")
    p_build.add_argument("--root", type=Path, default=None)
    p_build.set_defaults(func=_cmd_build)
    p_list = sub.add_parser("list", help="List procedure nodes.")
    p_list.add_argument("--mode", choices=("advisory", "mandatory", "constraint"))
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)
    p_show = sub.add_parser("show", help="Show one node.")
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=_cmd_show)
    p_check = sub.add_parser("check", help="Validate the graph; exit 1 on any error finding.")
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch build | list | show | check. Exit 0; 1 for 'check' with an error finding, a failed
    'build' or 'show' of an unknown id; 2 on usage errors."""
    args = _parser().parse_args(argv)
    return int(args.func(args))
```
**Why this shape**: `main`, `build` and the verb names are fixed by spec §3 M7. Each `_cmd_*` gets
a real body (the one-line `...` forms are blueprint gaps). `_load_specs` and `_settings` are the
two helpers TASK-5644 builds on, so keep their names and return types.

### `packages/ai-parrot/tests/sdd/test_procedure_cli.py` (CREATE)
```python
"""Tests for `parrot sdd procedure` (FEAT-891)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.sdd.cli import VERBS, mounted_modules
from parrot.sdd.config import ProcedureSettings, SddConfig
from parrot.sdd.scripts import procedure

MANIFEST = """\
schema_version: 1
graph: sdd
procedures:
  - {id: spec, title: Write the spec, kind: command, command: "/sdd-spec <slug>", done_when: [{probe: spec.exists}], next: [task]}
  - {id: task, title: Decompose, kind: command, command: "/sdd-task <spec>", requires_procedures: [spec], done_when: [{probe: index.exists}]}
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository (a `.git` directory is enough) with one valid manifest; cwd is its root."""
    # FILL IN: (tmp_path / "repo" / ".git").mkdir(parents=True); write MANIFEST to a file named demo.yaml in the
    # repo's procedure-manifest directory (MANIFEST_DIR from the producers module); monkeypatch.chdir(root); return root.


def test_cli_verbs(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """build, list, show and check exit codes; the noun is mounted in VERBS."""
    assert "procedure" in mounted_modules()
    assert {"build", "list", "show", "check"} <= set(VERBS["procedure"])
    # FILL IN: main(["build"]) == 0 and procedures.json exists; main(["list", "--json"]) lists two ids;
    # main(["show", "sdd:task"]) == 0; main(["show", "sdd:nope"]) == 1; main(["check"]) == 0.


def test_check_fails_on_graph_errors(repo: Path) -> None:
    """A broken edge, a requires cycle or an unknown probe makes `check` and `build` exit 1."""
    # FILL IN: overwrite the manifest three times (one error each) and assert both exit codes.


def test_list_rebuilds_a_stale_plane(repo: Path) -> None:
    """After a manifest edit, `list` rebuilds and shows the new node."""
    # FILL IN


def test_sdd_config_procedure_section() -> None:
    """`procedure` is accepted by SddConfig; absent keeps defaults; unknown keys are rejected."""
    assert SddConfig().procedure is None
    assert SddConfig.model_validate({"procedure": {"enforce": False}}).procedure == ProcedureSettings(enforce=False)
    with pytest.raises(ValueError):
        SddConfig.model_validate({"procedure": {"nope": 1}})
```

### FILL IN checklist
- [ ] `procedure.py` — `_settings`, `build`, `_load_specs`, `_known_commands`, the four `_cmd_*` bodies
- [ ] `test_procedure_cli.py` — the fixture and three test bodies
- [ ] `tmp_path` lives under the system temp directory: confirm `find_shared_root` resolves the fixture repo (it skips only the temp root itself and its ancestors)

---

## Acceptance Criteria

- [ ] `parrot sdd procedure build|list|show|check` are mounted and return the exit codes above.
- [ ] `check` exits 0 on a valid manifest and 1 on a broken edge, a `requires` cycle or an unknown probe.
- [ ] `build` aborts (exit 1, no new index) when the graph has an error finding.
- [ ] `SddConfig` accepts the optional `procedure` section and rejects unknown keys in it.
- [ ] `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q` still passes (every helper with a `main()` is mounted).
- [ ] The helper never uses `print`.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5635, TASK-5636, TASK-5640 and TASK-5641 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN` and replace every `...` placeholder.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5643 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5643
- Feature: procedural-graph-plane
- Implementation SHA: b1bcf4a84ac89ccb8b0ddbdde24cba885a1051c4
- Closed at (UTC): 2026-11-13T22:53:01+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 555.8s · Tokens: n/a |
