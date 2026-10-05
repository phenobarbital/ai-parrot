# TASK-4075: Bootstrap: install-parrot.ps1 -Global mode (pinned uv, user PATH)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4072
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (Windows leg) — the PowerShell mirror of TASK-4074. The FEAT-586 installer
`scripts/install/install-parrot.ps1` builds a project venv with a system Python. FEAT-633 adds a
`-Global` mode that builds the managed runtime under `$env:PARROT_HOME` (default
`$HOME\.parrot`): pinned, checksum-verified `uv.exe`, uv-managed CPython 3.12 under
`$PARROT_HOME\python`, `$PARROT_HOME\venv` with ai-parrot, and `parrot.exe` / `wikitoolkit.exe` /
`bookstore.exe` exposed from `$PARROT_HOME\bin`, which is added to the **user** PATH (registry,
uv/rustup style) with a "reopen your terminal" notice (spec §5 Windows AC).

Codex S10 (spec §9): the `-Global` branch runs BEFORE the system-Python guard
(`install-parrot.ps1:74-85`) — a clean Windows machine has no `python`.

`~/.parrot` is a live data directory (spec §7): only `bin\`, `venv\`, `python\` may be added, and
rollback removes only what this run created.

---

## Scope

- Add parameters `-Global`, `-Version <X>`, `-With <comma list>`; keep every existing parameter
  working; `-DryRun` stays total (no network, no writes).
- Take the `-Global` branch BEFORE the Python guard; project mode is untouched.
- Download pinned uv `0.11.28` (`uv-x86_64-pc-windows-msvc.zip` or `uv-aarch64-pc-windows-msvc.zip`
  plus `.sha256`) from `https://github.com/astral-sh/uv/releases/download/0.11.28/`, verify with
  `Get-FileHash -Algorithm SHA256`, `Expand-Archive` into a scratch dir, place `uv.exe` in
  `$PARROT_HOME\bin` write-then-rename. Never touch a user's own uv.
- `$env:UV_PYTHON_INSTALL_DIR = "$PARROT_HOME\python"`; `uv venv "$PARROT_HOME\venv" --python <py>
  --python-preference only-managed` (default `<py>` = `3.12`).
- `uv pip install --python "$PARROT_HOME\venv\Scripts\python.exe" "ai-parrot[<extras>]==<ver>"`.
- Shims: COPY `venv\Scripts\{parrot,wikitoolkit,bookstore}.exe` into `$PARROT_HOME\bin` (copy to
  `*.tmp` then `Move-Item -Force`). Do NOT put `venv\Scripts` on PATH — it would shadow `python`.
- Add `$PARROT_HOME\bin` to the **User** PATH idempotently via
  `[Environment]::SetEnvironmentVariable('Path', …, 'User')` (never `Machine`), also prepend it to
  the current session's `$env:Path`, and print a "reopen your terminal" notice.
- After install, run `& "$PARROT_HOME\bin\parrot.exe" self add <c>` for each `-With` component.
- Rollback (`trap`/`try…catch`) removes ONLY paths this run created and restores the user PATH
  value if this run changed it.
- Extend `test_install_powershell.py` with static assertions (always run) and pwsh-gated parse /
  dry-run tests (skipped when `pwsh` is absent, matching the existing soft pattern).

**NOT in scope**:
- `install-parrot.sh` (TASK-4074); CI legs + `SHA256SUMS` (TASK-4076); docs (TASK-4095).
- `parrot self update` re-copying shims after an upgrade — owned by TASK-4080 (see FILL IN on
  trampolines; record the requirement in the Completion Note).
- Machine-scope PATH, code signing, `winget` changes, project-mode behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.ps1` | MODIFY | `-Global` mode, new params, pinned-uv bootstrap, exe shims, user PATH, rollback |
| `packages/ai-parrot/tests/docs/test_install_powershell.py` | MODIFY | static + pwsh-gated tests for `-Global` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test file (stdlib + pytest), same as today
import shutil                # verified: packages/ai-parrot/tests/docs/test_install_powershell.py:5
import subprocess            # verified: packages/ai-parrot/tests/docs/test_install_powershell.py:6
from pathlib import Path     # verified: packages/ai-parrot/tests/docs/test_install_powershell.py:7
import pytest                # verified: packages/ai-parrot/tests/docs/test_install_powershell.py:9
```

### Existing Signatures to Use
```powershell
# scripts/install/install-parrot.ps1
[CmdletBinding()]                                   # line 36
param(                                              # line 37 (script params; 2nd `param(` at :64 is Run's)
  [string]$Python = 'python',                       # line 41 — interpreter BINARY in project mode
  [switch]$WithWiki,                                # line 42
  [switch]$DryRun,                                  # line 45
  [switch]$Help                                     # line 46
)
$ErrorActionPreference = 'Stop'                     # line 48
function Run { param([string]$Why, [scriptblock]$Cmd) ... }   # lines 63-72 — "-> why: cmd"; skips under -DryRun
# Python guard (AC10)                               # lines 74-85 — executes $Python; exit 1 on failure
# Map provider keys to ai-parrot extras             # lines 101-121 — builds $AllExtras, $CliProviders
```
```python
# packages/ai-parrot/tests/docs/test_install_powershell.py
REPO_ROOT = Path(__file__).resolve().parents[4]                       # line 11
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.ps1"     # line 12
@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")   # line 15
def test_powershell_script_syntax() -> None:                          # line 16
```
- `.PARAMETER` help block lines 6-34 (comment-based help, shown by `Get-Help` in `Show-Usage`).
- Console-script names come from `packages/ai-parrot/pyproject.toml:199-206` (`parrot`,
  `wikitoolkit`, `bookstore`; repointed to launcher wrappers by TASK-4072 — names unchanged).
- uv Windows assets: `uv-<target>.zip` + `uv-<target>.zip.sha256`, targets
  `x86_64-pc-windows-msvc` / `aarch64-pc-windows-msvc`; the zip holds `uv.exe`, `uvx.exe`
  (and `uvw.exe`) at its root (verify on first real download — FILL IN).

### Does NOT Exist
- ~~any uv download, `-Global`, `-Version`, `-With`, or `PARROT_HOME` handling in the `.ps1`~~ — new here.
- ~~Machine-scope PATH editing~~ — forbidden; User scope only.
- ~~a `parrot self` command~~ — TASK-4080; only announced under `-DryRun`.
- ~~`pwsh` in the local dev environment / guaranteed on CI's ubuntu runner~~ — tests must stay
  soft (`skipif`), exactly like `test_powershell_script_syntax`.
- ~~a root-level `install.ps1`~~ — never create one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/install/install-parrot.ps1",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_install_powershell.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/docs/test_install_powershell.py#test_powershell_script_syntax"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```powershell
# Every side effect goes through Run (install-parrot.ps1:63-72) so -DryRun stays total:
Run -Why "download pinned uv $UvVersion ($target)" -Cmd { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing }
```

### Key Constraints
- Name the switch `[Alias('Global')][switch]$GlobalMode` — *why*: `$global:` is a PowerShell scope
  modifier; a variable literally named `$Global` is legal but confusing and easy to mis-type as a
  scope reference. The user-facing flag stays `-Global`.
- In global mode `-Python` is a uv Python request forwarded to `uv venv --python`; default `3.12`
  when `-not $PSBoundParameters.ContainsKey('Python')` — *why*: the guard never runs, so a
  nonexistent interpreter path must not matter under `-DryRun`.
- Refuse `-Venv`, `-WithWiki`, `-SystemDeps` together with `-Global` (exit 1, `Write-Error`).
- Shims are COPIES, not PATH entries. uv's Windows console-script trampolines (and pip/distlib
  launchers) embed the absolute path of the venv's `python.exe`; that path
  (`$PARROT_HOME\venv\Scripts\python.exe`) is stable, so a copied `.exe` stays valid. FILL IN:
  confirm on a real Windows run (spike S1 windows leg, TASK-4068) that a copied `parrot.exe`
  launches and that it survives an `ai-parrot` upgrade; if not, re-copy after every install (this
  script already re-copies on every run) and flag `parrot self update` (TASK-4080) to re-copy too.
- User PATH edit is idempotent: split on `;`, compare case-insensitively and trimmed of a trailing
  `\`, prepend only if absent. Read with `[Environment]::GetEnvironmentVariable('Path','User')`
  (may be `$null` — treat as empty).
- Download/checksum failure aborts BEFORE any shim copy or PATH change.
- Use `Invoke-WebRequest -UseBasicParsing` (Windows PowerShell 5.1 compatible) and set
  `[Net.ServicePointManager]::SecurityProtocol` to include TLS 1.2 when running under 5.1.
- Rollback tracks a `$Created = [System.Collections.Generic.List[string]]::new()` and the original
  user PATH; on failure remove tracked paths in reverse and restore PATH only if changed.

### References in Codebase
- `scripts/install/install-parrot.ps1:63-72` — `Run` contract.
- `scripts/install/install-parrot.ps1:101-121` — provider→extras mapping to reuse.
- `scripts/install/install-parrot.sh` after TASK-4074 — the POSIX mirror (same flag semantics).

---

## Implementation Blueprint

### Steps (in order)
1. Add the three params after `[switch]$WithWiki,` and their `.PARAMETER` help entries — *why*:
   `Show-Usage` renders comment-based help.
2. Move the provider→extras mapping (lines 101-121) into `function Resolve-Extras` defined before
   the guard and call it at the old location — *why*: global mode exits before that block.
3. Insert the global-mode functions + dispatch immediately before the Python guard comment —
   *why*: codex S10.
4. Extend the test file with static assertions (no pwsh needed) and pwsh-gated runtime checks.

### `scripts/install/install-parrot.ps1` (MODIFY)
```powershell
# occurrences: 1 (verified: grep -c '  [switch]$WithWiki,' scripts/install/install-parrot.ps1)
# AFTER — `  [switch]$WithWiki,` (verified: scripts/install/install-parrot.ps1:42)
#   (`param(` itself occurs 2x — :37 script params, :64 Run's params — so anchor on $WithWiki)
  [Alias('Global')][switch]$GlobalMode,
  [string]$Version = '',
  [string]$With = '',

# occurrences: 1 (verified: grep -c '.PARAMETER Help' scripts/install/install-parrot.ps1)
# REPLACE — `.PARAMETER Help` (verified: :33): insert `.PARAMETER Global`, `.PARAMETER Version`,
#   `.PARAMETER With` entries (same 4-space indented style) before it, then keep `.PARAMETER Help`.

# occurrences: 1 (verified: grep -c '# Map provider keys to ai-parrot extras (mirrors install-parrot.sh / guide §3).' scripts/install/install-parrot.ps1)
# REPLACE — lines 101-121 with `Resolve-Extras`; the body moves verbatim into the function below,
#   assigning `$script:AllExtras` / `$script:CliProviders`.

# occurrences: 1 (verified: grep -c '# Python guard (AC10) — refuse anything outside >=3.11,<3.14 BEFORE any' scripts/install/install-parrot.ps1)
# REPLACE — `# Python guard (AC10) — refuse anything outside >=3.11,<3.14 BEFORE any`
#   (verified: scripts/install/install-parrot.ps1:74) with this block followed by the original line.
function Resolve-Extras { }  # FILL IN: old lines 101-121 verbatim, $script: scope — bounded by existing parse test
$UvVersion = '0.11.28'

function Add-UserPath([string]$Dir) {
  $cur = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($null -eq $cur) { $cur = '' }
  $parts = $cur -split ';' | Where-Object { $_ -ne '' }
  if ($parts | Where-Object { $_.TrimEnd('\') -ieq $Dir.TrimEnd('\') }) { return }
  $script:OriginalUserPath = $cur
  [Environment]::SetEnvironmentVariable('Path', (@($Dir) + $parts) -join ';', 'User')
  $env:Path = "$Dir;$env:Path"
  Write-Host "Added $Dir to your user PATH — reopen your terminal to pick it up."
}

function Install-Global {
  # FILL IN: refuse -Venv/-WithWiki/-SystemDeps with -Global (Write-Error; exit 1) — bounded by Key Constraints
  $home_ = if ($env:PARROT_HOME) { $env:PARROT_HOME } else { Join-Path $HOME '.parrot' }
  $py = if ($PSBoundParameters.ContainsKey('Python')) { $Python } else { '3.12' }
  Resolve-Extras
  $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
  $target = if ("$arch" -eq 'Arm64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-pc-windows-msvc' }
  $asset = "uv-$target.zip"
  $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$asset"
  $spec = "ai-parrot[$AllExtras]"; if ($Version) { $spec = "$spec==$Version" }
  $bin = Join-Path $home_ 'bin'; $venv = Join-Path $home_ 'venv'; $uv = Join-Path $bin 'uv.exe'
  $dl = Join-Path ([IO.Path]::GetTempPath()) "parrot-uv-$PID"
  $script:Created = [System.Collections.Generic.List[string]]::new()
  try {
    foreach ($d in @($home_, $bin)) {
      if (-not (Test-Path $d)) { Run -Why "create $d" -Cmd { New-Item -ItemType Directory -Path $d | Out-Null }; if (-not $DryRun) { $Created.Add($d) } }
    }
    Run -Why 'create a scratch download dir' -Cmd { New-Item -ItemType Directory -Force -Path $dl | Out-Null }
    Run -Why "download pinned uv $UvVersion ($target)" -Cmd { Invoke-WebRequest -Uri $url -OutFile (Join-Path $dl $asset) -UseBasicParsing }
    Run -Why 'download the uv checksum' -Cmd { Invoke-WebRequest -Uri "$url.sha256" -OutFile (Join-Path $dl "$asset.sha256") -UseBasicParsing }
    Run -Why 'verify the uv checksum' -Cmd {
      $want = ((Get-Content (Join-Path $dl "$asset.sha256") -Raw).Trim() -split '\s+')[0]
      $got = (Get-FileHash -Algorithm SHA256 (Join-Path $dl $asset)).Hash
      if ($want -ine $got) { throw "checksum mismatch for $asset" }
    }
    Run -Why 'extract uv' -Cmd { Expand-Archive -Path (Join-Path $dl $asset) -DestinationPath $dl -Force }
    # FILL IN: copy uv.exe (+uvx.exe) to $bin as *.tmp then Move-Item -Force; track new files — bounded by "never touch the user's uv"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $home_ 'python'
    if (-not (Test-Path $venv)) {
      if (-not $DryRun) { $Created.Add($venv) }
      Run -Why "create the managed venv (Python $py)" -Cmd { & $uv venv $venv --python $py --python-preference only-managed }
    }
    Run -Why "install $spec into the managed venv" -Cmd { & $uv pip install --python (Join-Path $venv 'Scripts\python.exe') $spec }
    foreach ($s in @('parrot', 'wikitoolkit', 'bookstore')) {
      $src = Join-Path $venv "Scripts\$s.exe"; $dst = Join-Path $bin "$s.exe"
      Run -Why "expose $s" -Cmd { Copy-Item $src "$dst.tmp" -Force; Move-Item "$dst.tmp" $dst -Force }
    }
    Run -Why "add $bin to the user PATH" -Cmd { Add-UserPath $bin }
    foreach ($c in ($With -split ',' | Where-Object { $_ })) {
      Run -Why "add component $c" -Cmd { & (Join-Path $bin 'parrot.exe') self add $c }
    }
  } catch {
    # FILL IN: remove $Created in reverse; restore $script:OriginalUserPath if set — bounded by AC rollback
    throw
  } finally {
    if (-not $DryRun -and (Test-Path $dl)) { Remove-Item -Recurse -Force $dl }
  }
}

if ($GlobalMode) { Install-Global; Write-Host 'Done.'; exit 0 }

# Python guard (AC10) — refuse anything outside >=3.11,<3.14 BEFORE any
```
**Why this shape**: dispatch above the guard (codex S10); every side effect is inside `Run` so
`-DryRun` stays total. `$PSBoundParameters` inside `Install-Global` refers to the FUNCTION's bound
params — FILL IN: capture the script-level `$PSBoundParameters.ContainsKey('Python')` into
`$script:PythonSet` before the function is called. Do NOT touch `Run`, the guard, or project mode.
Scriptblocks passed to `Run` close over local variables only via dynamic scoping — keep the
variables in the function scope that calls `Run` (as above), never in a nested function.

### `packages/ai-parrot/tests/docs/test_install_powershell.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_powershell_script_syntax() -> None:' packages/ai-parrot/tests/docs/test_install_powershell.py)
# AFTER — end of file (after test_powershell_script_syntax, :15-30); append:

_TEXT = SCRIPT.read_text(encoding="utf-8")


def test_global_params_declared() -> None:
    """-Global / -Version / -With are script parameters."""
    assert "[Alias('Global')][switch]$GlobalMode" in _TEXT
    assert "[string]$Version" in _TEXT
    assert "[string]$With" in _TEXT


def test_global_branch_precedes_python_guard() -> None:
    """The -Global dispatch appears before the system-Python guard (codex S10)."""
    assert _TEXT.index("if ($GlobalMode)") < _TEXT.index("# Python guard (AC10)")


def test_global_pins_and_verifies_uv() -> None:
    """Pinned uv 0.11.28 is verified with Get-FileHash; PATH edits are User-scope only."""
    assert "0.11.28" in _TEXT
    assert "Get-FileHash" in _TEXT
    assert "'User'" in _TEXT
    assert "'Machine'" not in _TEXT


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_global_dry_run(tmp_path: Path) -> None:
    """-Global -DryRun with a bogus -Python exits 0 and writes nothing under PARROT_HOME."""
    home = tmp_path / "parrot-home"
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT), "-Global", "-DryRun", "-Python", "C:/nonexistent",
         "-Version", "9.9.9", "-With", "sdd"],
        capture_output=True,
        text=True,
        check=False,
        env={"PARROT_HOME": str(home), **{k: v for k, v in __import__("os").environ.items() if k != "PARROT_HOME"}},
    )
    assert result.returncode == 0, result.stderr
    assert "unsupported Python" not in result.stderr
    assert "==9.9.9" in result.stdout and "self add sdd" in result.stdout
    assert not home.exists()
```
**Why**: static assertions always run in CI (pwsh is not guaranteed); the runtime dry-run follows
the existing soft `skipif` pattern. FILL IN: replace the `__import__("os")` with a top-level
`import os` (add it to the imports) — bounded by ruff.

### FILL IN checklist
- [ ] `install-parrot.ps1::Resolve-Extras` — move lines 101-121 verbatim into `$script:` scope.
- [ ] `install-parrot.ps1::Install-Global` — refuse `-Venv`/`-WithWiki`/`-SystemDeps`.
- [ ] `install-parrot.ps1::Install-Global` — capture script-level `-Python` bound-ness into `$script:PythonSet`.
- [ ] `install-parrot.ps1::Install-Global` — verify zip layout, copy `uv.exe` (+`uvx.exe`) write-then-rename.
- [ ] `install-parrot.ps1::Install-Global` catch — reverse-remove `$Created`, restore user PATH if changed.
- [ ] Trampoline-copy validity — confirm with spike S1 windows leg (TASK-4068); else re-copy rule for `self update` (TASK-4080).
- [ ] TLS 1.2 enablement for Windows PowerShell 5.1.
- [ ] Test file — top-level `import os`.

---

## Acceptance Criteria

- [ ] `-Global` is dispatched before the Python guard (static test) — codex S10.
- [ ] `-Global -DryRun` performs no download and creates nothing under `PARROT_HOME` (pwsh-gated test).
- [ ] Pinned uv `0.11.28` is downloaded for `x86_64`/`aarch64` `pc-windows-msvc` and verified with
      `Get-FileHash` against the release `.sha256`; a user's own uv is never touched.
- [ ] Managed Python lives under `$PARROT_HOME\python`; venv built with Python 3.12 by default.
- [ ] `parrot.exe`/`wikitoolkit.exe`/`bookstore.exe` are COPIED into `$PARROT_HOME\bin`
      (write-then-rename); `venv\Scripts` is never put on PATH.
- [ ] User PATH (never Machine) edited idempotently via `[Environment]::SetEnvironmentVariable`,
      with a reopen-terminal notice (spec §5 Windows AC).
- [ ] Rollback removes only paths created by this run; pre-existing `~/.parrot` data intact.
- [ ] Project mode unchanged; `test_powershell_script_syntax` still passes where pwsh exists.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_install_powershell.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_install_powershell.py (additions — see blueprint)
def test_global_params_declared(): ...                 # static
def test_global_branch_precedes_python_guard(): ...    # static, codex S10
def test_global_pins_and_verifies_uv(): ...            # static: 0.11.28, Get-FileHash, User not Machine
def test_global_dry_run(tmp_path): ...                 # pwsh-gated runtime dry run
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4075 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
