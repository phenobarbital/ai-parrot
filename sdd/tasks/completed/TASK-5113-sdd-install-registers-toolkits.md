# TASK-5113: `parrot sdd install` registers the `sdd-coder` and `bounded-source` toolkits

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12, amendment C34)
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5112, TASK-5110 (done)
**Assigned-to**: unassigned

---

## Context

In the first end-to-end SDD run in a foreign repo (sandbox project, FEAT-1 `stats-module`) the worker reported:
"The parrot-sdd-coder tools weren't available in this session. I implemented the tasks myself, one after
another." `sdd-worker` is built around the `parrot-sdd-coder` MCP server (20 `mcp__parrot-sdd-coder__*` tools in
its frontmatter, plus `mcp__parrot-bounded-source__source_inspect_batch`), but `parrot sdd install` never registers
either server — the user has to know to run `parrot toolkits install sdd-coder`. `sdd-coder` is already core;
TASK-5112 moves `bounded-source` into core so both can always be installed.

Decisions (Jesus Lara, 2026-11-03): install both from `parrot sdd install`; seed the **shipped** `sdd-coder` roster
unchanged and report which seats are usable. Spec rev 0.12 amendment C34 is the normative text.

---

## Scope

- Add a `toolkits` plan step to `plan_install()` (after `dangerous-guard`), present unless `sdd_coder=False`:
  `plan: toolkits sdd-coder, bounded-source`.
- In `install_sdd_integration()` run it through
  `parrot.mcp.toolkit_install.install_toolkits(root, ["sdd-coder", "bounded-source"], hosts)` (lazy import), mapping
  the install's `hosts` (`claude`/`codex`/`google`) to `HostKind`. Append the `ActionReport.actions` as action lines
  and each `ActionReport.warnings` / `failed_hosts` entry as a `warning:` line. A toolkit that is already installed
  is left alone (`install_toolkits` reports it as "already installed" — keep that as an informational line, not a
  `warning:`).
- Record in the receipt `receipt["toolkits"] = [<names this run added>]` (from the "— seeded" actions); older
  receipts lack the key.
- Roster report (after the toolkit step, only when `sdd-coder` is installed): read the `sdd-coder` section of
  `.parrot/mcp-toolkits.yaml`, build `RosterConfig(seats=kwargs["roster"])`, run
  `RosterProbe(smoke=None).probe(roster)` (static: credentials/CLIs only, no model call, no network) with
  `asyncio.run`, and emit:
  - `note: sdd-coder seats available: <label, …>; unavailable: <label> (<reason>), …`
  - `warning:` when fewer than two available seats are both `kind: mcp` and listed in `complexity.strong_models`
    ("complex tasks will have no retry seat — configure codex/gemini/nova credentials, see issue:569e81756247").
  Any failure while building or probing the roster → one `warning:` line, never an exception out of `install`.
- `uninstall_sdd_integration()`: call `uninstall_toolkits(root, receipt["toolkits"], hosts)` for the names this
  install recorded; never remove a toolkit the user installed themselves.
- `install_sdd_integration(..., sdd_coder: bool = True)`; CLI flag `--no-sdd-coder` on `parrot sdd install`.
- `sdd_status()` gains `"toolkits": {"sdd-coder": <ToolkitState value>, "bounded-source": <…>}` from
  `parrot.mcp.toolkit_install.inventory(root)`.
- Docs: `docs/getting-started.md` — the SDD install now registers the two MCP toolkits, how to read the roster
  note, `--no-sdd-coder`.
- Tests: `packages/ai-parrot/tests/sdd/test_installer_toolkits.py`.

**NOT in scope**:
- Changing the shipped roster template, or adding seats automatically.
- Smoke-testing seats (real model calls) at install time.
- `parrot claude install` (wiki integration) — unchanged.
- Moving `bounded-source` (TASK-5112).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `toolkits` plan step, install/uninstall, roster report, receipt, status |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `--no-sdd-coder` |
| `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` | CREATE | Plan, install, idempotence, receipt/uninstall, roster note, opt-out |
| `docs/getting-started.md` | MODIFY | Toolkits registered by the SDD install |

---

## Codebase Contract (Anti-Hallucination)

Verified on `origin/feat-FEAT-633-parrot-installer` at `577ebd9056` (2026-11-03).

### Verified Imports
```python
from parrot.mcp.toolkit_install import ToolkitState, install_toolkits, inventory, uninstall_toolkits  # toolkit_install.py:32,97,158,187
from parrot.mcp.hosts import HostKind                                     # imported by toolkit_install.py:18
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe            # roster.py:27
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig           # models.py:294
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_install.py
class ActionReport(BaseModel):                       # line 55
    actions: list[str]; warnings: list[str]; failed_hosts: dict[HostKind, str]
def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport   # line 158
    # preflight -> seed -> reconcile -> approvals; raises ValueError BEFORE any write on unknown name / bad config
    # actions: "<name> — seeded"; warnings: "<name> — already installed", "<name> — template drift: …"
def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport  # line 187
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]              # line 97

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py
class RosterProbe:                                                     # line 27 — "Never raises"
    def __init__(self, *, config_getter=conf.config.get, which=shutil.which, smoke=None, smoke_timeout_s=60)
    async def probe(self, roster: RosterConfig, *, excluded=None) -> List[SeatProbeResult]   # line 41
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class RosterConfig(BaseModel): seats: List[RosterSeat] (min_length=1); complexity: ComplexityPolicy  # line 294
class SeatProbeResult(BaseModel): label; kind; backend; available; reason; model_used               # ~line 310
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:120-129 — how the toolkit builds RosterConfig
#   from its yaml kwargs (roster=list[dict], lint, feedback, suspension_policy; complexity via model_copy)

# packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml — kwargs.roster (shipped seats: qwen/nova,
#   gemini/google-compat, codex-spark/codex, haiku native, gpt-5.6-terra/codex, gpt-5.6-sol/codex, opus native)

# packages/ai-parrot/src/parrot/sdd/installer.py
PlanAction = Literal[...]                                       # line 75 — add "toolkits"
def load_receipt(root) -> dict                                  # line 203 — must tolerate/keep "toolkits"
def plan_install(root, hosts, *, force, hook, base_branch, dangerous_guard=True)  # line 447
    # last steps: base-branch (492), dangerous-guard (494)
def install_sdd_integration(root, hosts=("claude",), *, force, dry_run, portable, base_branch, push_base,
                            hotfix_base, dangerous_guard=True) -> list[str]       # line 918; dispatch at ~993
def uninstall_sdd_integration(root, hosts=("claude",), *, dry_run=False) -> list[str]   # line 1022
def sdd_status(root: Path) -> dict[str, Any]                    # line 1160

# packages/ai-parrot/src/parrot/sdd/cli.py — install command (line 87), last option "--no-dangerous-guard" (line 82)
```

### Does NOT Exist
- ~~`parrot sdd install --no-sdd-coder`~~ — added by this task
- ~~`receipt["toolkits"]`~~ — new key
- ~~a synchronous `RosterProbe.probe`~~ — it is `async`; run it with `asyncio.run` (install is sync)
- ~~a core `bounded-source` toolkit~~ — exists only after TASK-5112

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer_toolkits.py", "action": "CREATE"},
    {"path": "docs/getting-started.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#install_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#uninstall_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#inventory",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#RosterProbe",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#plan_install",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#uninstall_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#sdd_status",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#install"
  ]
}
```

---

## Implementation Notes

- Keep every new import lazy (inside the step), like `_install_ledger_hooks_step`: importing the sdd_coder package
  pulls `parrot.conf`/navconfig, which `parrot sdd install --help` must not pay for.
- `install_toolkits` raises `ValueError` before writing on a malformed `.parrot/mcp-toolkits.yaml`; the SDD install
  must turn that into a `warning:` and continue (the rest of the SDD install already happened).
- Tests: patch `RosterProbe` with an injected `config_getter`/`which` (constructor kwargs) instead of touching the
  real environment; assert on the note/warning text.

---

## Acceptance Criteria

- [ ] Fresh repo: `parrot sdd install` leaves `.parrot/mcp-toolkits.yaml` with `sdd-coder` and `bounded-source`
      sections and `.mcp.json` with `parrot-sdd-coder` and `parrot-bounded-source` entries; Claude approvals synced.
- [ ] Re-install changes nothing in those files (byte-identical) and duplicates nothing.
- [ ] A toolkit the user installed before is not recorded in `receipt["toolkits"]`; uninstall leaves it in place
      and removes only the recorded ones.
- [ ] With no credentials and no `codex` CLI: the note lists `haiku`, `opus` as available and the others with
      reasons, and the strong-seat `warning:` is printed. With injected credentials for two strong MCP seats: no warning.
- [ ] `--no-sdd-coder` writes no toolkit config; `--dry-run` prints `plan: toolkits …` and writes nothing.
- [ ] A malformed `.parrot/mcp-toolkits.yaml` → `warning:` line, install still finishes.
- [ ] `sdd_status()` reports both toolkit states.
- [ ] `test_installer.py`, `test_installer_dangerous_guard.py`, `test_installer_base_branch.py`, `test_sdd_cli.py` still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer_toolkits.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_base_branch.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_installer_toolkits.py
import json
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import install_sdd_integration, sdd_status, uninstall_sdd_integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    return tmp_path


def test_install_registers_both_toolkits(repo: Path) -> None:
    install_sdd_integration(repo)
    servers = json.loads((repo / ".mcp.json").read_text())["mcpServers"]
    assert {"parrot-sdd-coder", "parrot-bounded-source"} <= set(servers)


def test_reinstall_is_byte_identical(repo: Path) -> None: ...
def test_preexisting_toolkit_is_not_recorded_or_removed(repo: Path) -> None: ...
def test_roster_note_and_strong_seat_warning(repo: Path, monkeypatch) -> None: ...
def test_no_sdd_coder_opt_out(repo: Path) -> None: ...
def test_dry_run_writes_nothing(repo: Path) -> None: ...
def test_malformed_toolkit_config_is_a_warning(repo: Path) -> None: ...
def test_status_reports_toolkits(repo: Path) -> None: ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — branch `feat-FEAT-633-parrot-installer` (never on `dev`)
2. **Check dependencies** — TASK-5112 must be `done` in `sdd/tasks/index/parrot-installer.json`
3. **Read the spec** amendment C34 and **verify the Codebase Contract** (line numbers move after TASK-5112)
4. **Update status** → `"in-progress"`, commit only the index file
5. **Implement**, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
6. **Commit the code** — stage only the files listed above
7. **Close the task** with `parrot sdd task close TASK-5113 parrot-installer verified`
8. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**: Claude Sonnet 5.5 (sdd-start, sequential)
**Date**: 2026-11-03
**Notes**: New `toolkits` plan step (+ `toolkits-remove` on uninstall), `receipt["toolkits"]` records only toolkits this run
seeded, static roster note/strong-seat warning via `RosterProbe(smoke=None)`, `--no-sdd-coder`, `sdd_status()["toolkits"]`,
docs. All new imports lazy; any toolkit/roster failure is a `warning:` line. Strong seat = kind mcp AND (backend, model)
in `complexity.strong_models`. Tests: new suite (9) + all of tests/sdd pass. Note: run the sdd suites with an ABSOLUTE
PYTHONPATH — a relative one makes subprocess-based tests import the main checkout and fail spuriously.
