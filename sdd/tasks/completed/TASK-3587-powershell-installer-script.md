# TASK-3587: Write scripts/install/install-parrot.ps1 and its test

**Feature**: FEAT-586 — Public Install & Getting-Started Guide for AI-Parrot
**Spec**: `sdd/specs/parrot-install-guide.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4: the Windows 10+ PowerShell installer, a mirror of
the POSIX script's flag set. **No dependency on TASK-3584 or TASK-3586**: it
derives from the spec (§3 M4) and shares no files, so it runs concurrently.

---

## Scope

- Create `scripts/install/install-parrot.ps1` with parameters mirroring the POSIX
  flags: `-Provider`, `-Extras`, `-Venv`, `-Python`, `-WithWiki`, `-InstallCli`,
  `-SystemDeps`, `-DryRun`, `-Help`. **Use `-Provider`, never `-Host`** — `$Host`
  is a reserved PowerShell automatic variable (spec §6 "Does NOT Exist").
- Same contract as TASK-3586: Python guard `>=3.11,<3.14`; create-or-reuse venv;
  install `ai-parrot` + provider/extras; announce every command; `-DryRun` total;
  `-SystemDeps` gates `winget`; `-InstallCli` npm-installs `@latest` (no pin).
- Create `packages/ai-parrot/tests/docs/test_install_powershell.py` with
  `test_powershell_script_syntax` (parses via `pwsh`; **skips when `pwsh` is
  absent** — spec §7 risk).

**NOT in scope**: the POSIX script; CI wiring; the guide.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.ps1` | CREATE | Windows installer, parameter-driven, idempotent, `-DryRun` |
| `packages/ai-parrot/tests/docs/test_install_powershell.py` | CREATE | Parse-check via `pwsh`, skipped when absent |

---

## Codebase Contract (Anti-Hallucination)

### Verified facts
- Supported Python `>=3.11,<3.14` — `packages/ai-parrot/pyproject.toml:18`.
- Windows venv activation path is `.venv\Scripts\Activate.ps1`.
- CLI-backed providers: `@anthropic-ai/claude-code` / `@openai/codex` via npm,
  installed at `@latest` (no pin — spec AC18).

### Does NOT Exist
- ~~`-Host` as a parameter name~~ — collides with the `$Host` automatic variable;
  use `-Provider` (spec §6).
- ~~an RTK step / `ai-parrot[rtk]`~~ — out of scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "scripts/install/install-parrot.ps1", "action": "CREATE" },
    { "path": "packages/ai-parrot/tests/docs/test_install_powershell.py", "action": "CREATE" }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `[CmdletBinding()]` + `param(...)`; `$ErrorActionPreference = 'Stop'`.
- A `Run` helper echoing purpose+command before executing (or only echoing under
  `-DryRun`) — the AC8 transparency contract.
- Idempotent venv; announce every `winget`/`npm` command.

### References in Codebase
- the POSIX installer from TASK-3586 — mirror its flags and messages
  (read it if already merged; otherwise mirror the spec §3 M3/M4 contract).

---

## Implementation Blueprint

### Steps (in order)
1. Declare `param(...)` with `-Provider` default and `-Help` — *why*: predictable UX,
   and `-Provider` avoids the `$Host` clash.
2. Add a `Run` function that writes "→ <purpose>: <cmd>" then invokes (skips under
   `-DryRun`) — *why*: AC8 + dry-run totality in one place.
3. Python guard, then venv → package/extras → optional CLI → optional wiki.

### `scripts/install/install-parrot.ps1` (CREATE)
```powershell
<# AI-Parrot installer (Windows) — automates the AI-Parrot getting-started guide (FEAT-586).
   Never destructive; announces every privileged/network command. #>
[CmdletBinding()]
param(
  [string]$Provider = 'anthropic',   # NOT -Host: $Host is reserved
  [string]$Extras = '',
  [string]$Venv = '.venv',
  [string]$Python = 'python',
  [switch]$WithWiki,
  [switch]$InstallCli,
  [switch]$SystemDeps,
  [switch]$DryRun,
  [switch]$Help
)
$ErrorActionPreference = 'Stop'

function Run([string]$Why, [scriptblock]$Cmd) {
  Write-Host "→ $Why: $($Cmd.ToString().Trim())"
  if (-not $DryRun) { & $Cmd }
}

# Python guard (AC10):
$pyver = (& $Python -c 'import sys;print("%d.%d"%sys.version_info[:2])').Trim()
if ($pyver -notin @('3.11','3.12','3.13')) { throw "unsupported Python $pyver; need >=3.11,<3.14" }

# FILL IN: -Help block; optional -SystemDeps (winget) via Run; venv create-or-reuse
#          (.venv\Scripts\Activate.ps1); Run 'install ai-parrot' uv pip/pip install
#          "ai-parrot[<provider,extras>]"; optional -InstallCli (@latest npm);
#          optional -WithWiki (wikitoolkit build) — every side effect via Run.
```
**Why this shape**: `-Provider` (not `-Host`) is mandatory to avoid the automatic-
variable clash. `Run` mirrors the POSIX `run()` so the two scripts stay
behaviourally identical.

### `packages/ai-parrot/tests/docs/test_install_powershell.py` (CREATE)
```python
"""Parse-check for scripts/install/install-parrot.ps1 (FEAT-586, TASK-3587)."""
from __future__ import annotations
import shutil, subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.ps1"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_powershell_script_syntax() -> None:
    """PowerShell parses the script with zero errors."""
    assert SCRIPT.is_file()
    # FILL IN: run pwsh -NoProfile -Command with
    #          [Parser]::ParseFile(path,[ref]$null,[ref]$errs); exit 1 if $errs —
    #          assert returncode 0. Bounded by AC9.
    raise NotImplementedError
```
**Why this shape**: the skip guard makes the suite green on Linux CI where `pwsh`
is usually absent (spec §7 risk); the parse call is `FILL IN`.

### FILL IN checklist
- [ ] `-Help` block + `-SystemDeps`/`-InstallCli`/`-WithWiki` branches via `Run`; bounded by spec §3 M4
- [ ] venv create-or-reuse + package/extras steps; bounded by AC9
- [ ] `test_powershell_script_syntax` parse call; bounded by AC9

---

## Acceptance Criteria
- [ ] Parameters mirror the POSIX flags; `-Provider` used (never `-Host`) (spec AC9, §6)
- [ ] `-DryRun` prints the plan and touches nothing (spec AC9)
- [ ] Refuses Python outside `>=3.11,<3.14` (spec AC10)
- [ ] Every winget/npm command announced (spec AC8)
- [ ] Parse test passes where `pwsh` exists, skips cleanly otherwise

## Validation Commands
- `pytest packages/ai-parrot/tests/docs/test_install_powershell.py::test_powershell_script_syntax -q`

---

## Test Specification
```python
def test_powershell_script_syntax(): ...   # skipped when pwsh absent
```

---

## Agent Instructions
1. Read the spec (§3 M4, §6, §7).
2. Confirm the `$Host` caveat and the Windows activation path.
3. Index status → in-progress.
4. Implement from the blueprint; complete every `# FILL IN`.
5. Run the Validation Command (or confirm the skip on a pwsh-less box).
6. Move to `sdd/tasks/completed/`, index → done, fill the note.

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-21
**Notes**: Created `scripts/install/install-parrot.ps1` (mirrors
`install-parrot.sh`'s flags/contract: `-Provider` — never `-Host` —,
`-Extras`, `-Venv`, `-Python`, `-WithWiki`, `-InstallCli`, `-SystemDeps`,
`-DryRun`, `-Help`; `Run` transparency helper; Python guard before any
other step; create-or-reuse venv; same provider→extra mapping) and
`packages/ai-parrot/tests/docs/test_install_powershell.py`
(`test_powershell_script_syntax`, `pytest.mark.skipif` when `pwsh` is
absent). `pwsh` is not installed in this environment, so the syntax test
skips cleanly here (verified) rather than actually parsing — brace/paren
balance was checked manually (34/34, 45/45) as a best-effort substitute;
CI (TASK-3588) is where this test will actually execute the parser.
`black --check` clean on the new Python test file. `ruff` is not installed
in the shared `.venv` in this environment (dev extra not synced) so
`ruff check` could not be run — flagged for the human/code review.
**Deviations from spec**: none.
