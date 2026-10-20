# TASK-4075: Bootstrap: install-parrot.ps1 -Global mode (pinned uv, user PATH)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
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

## Amendments — spec rev 0.2 (2026-10-14)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3 C14, §5 resolved by
Jesus Lara) — the PowerShell mirror of TASK-4074's amendments. Every section below already
reflects these deltas; this list is the audit trail.

- **C14b — pre-install gate.** `-Global` evaluates `Test-Preflight` BEFORE any write and before
  the pinned-uv download: supported platform (Windows AMD64 — the TASK-4094 wheel matrix; Arm64
  is refused until a windows-arm64 core wheel exists), `Invoke-WebRequest` + `Get-FileHash`
  available (always true on PowerShell 5.1+, still asserted), `git` on PATH, a writable
  `PARROT_HOME` (nearest existing ancestor) with at least `$MinFreeKB` free, and GitHub + PyPI
  reachable (HEAD; skipped under `-DryRun`). A failed gate writes `preflight: <condition> — fix:
  <fix>` to the error stream and exits 1 with nothing written.
- **C14b — post-install runtime check.** After the shims and the user-PATH edit the script runs
  `parrot.exe self doctor --runtime-only` (TASK-4080) against the NEW managed runtime, pinned with
  `$env:PARROT_VENV = "$PARROT_HOME\venv"` so the launcher never redirects to a project venv. That
  scope checks only managed uv, Python, the runtime entry points and PATH; repository readiness,
  host configuration and optional-component checks are excluded. Only a RUNTIME failure throws
  into the EXISTING catch-rollback (only this run's paths; user PATH restored). A healthy runtime
  stays installed when the invoking repo has unauthenticated `gh`, an uncommitted ledger or
  outdated SDD assets. Under `-DryRun` it is only announced.
- **C14a — self-describing one-liner.** `-Global` prints, first, a `Write-Plan` paragraph: what is
  downloaded (uv `0.11.28`, URL, `.sha256`), where it writes (`PARROT_HOME\{bin,venv,python}` + the
  user PATH), that the user's own uv is never touched, and the non-piped alternative. Docs: TASK-4095.
- Tests: static assertions that the gate precedes the first `New-Item`, that the doctor step uses
  `--runtime-only` and precedes `self add`; pwsh-gated runtime tests that `-DryRun` prints plan +
  gate summary, that an unwritable `PARROT_HOME` ancestor exits 1 before any write, and the two
  offline post-install outcomes (runtime failure rolls back; repo-readiness failures keep the
  runtime) with fake `uv.exe`/`parrot.exe` scripts.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Verified current against dev 9f51c7735; no changes (`install-parrot.ps1`, `test_install_powershell.py` and
  `[project.scripts]` anchors unchanged; no commits since baseline).
- Open decisions — do not implement the affected part until resolved (spec rev 0.5 / owner):
  - `wikitoolkit mcp` now needs ai-parrot-tools (`wiki/tools.py:69-76`, `mcp_server.py:525-545, 566-574`; core
    `dependencies` lack it), so a managed venv with only `ai-parrot[...]` cannot serve it. Affected: the install
    spec in `Install-Global` (add `ai-parrot-tools`, same `-Version` pin, or a fix on the wiki side).

## Spec rev 0.5 — 2026-10-20
- Resolved (rev 0.5 D1): the real fix is on the wiki side — core serves `wikitoolkit mcp` on its own
  (wiki operation descriptors over core's stdio server); it is not part of this task. Until that fix
  lands, `Install-Global` also installs `ai-parrot-tools` as a bridge, in the same `uv pip install` call,
  with the same pin as `ai-parrot` (`ai-parrot-tools==<Version>` when `-Version` is given; both packages
  share one version, today `1.2.3`). Mark it with a `# D1 bridge` comment. The change that lands the D1
  fix removes that line; if the fix is already on the branch when this task is implemented, do not add
  the bridge at all. Never add `ai-parrot-tools` to the extras mapping or to core `dependencies`.
  Keep the bridge identical to TASK-4074's.
- Anchors re-checked on the working tree 2026-10-20: `install-parrot.ps1` (:33, :36-48, :63-72, :74-85,
  :101-121), `test_install_powershell.py` (:11-12, :15-16) and `pyproject.toml` `[project.scripts]`
  (:199-206) are all current.

---

## Scope

- Add parameters `-Global`, `-Version <X>`, `-With <comma list>`; keep every existing parameter
  working; `-DryRun` stays total (no network, no writes).
- Take the `-Global` branch BEFORE the Python guard; project mode is untouched.
- In global mode, before anything else: `Write-Plan` (C14a paragraph), then `Test-Preflight`
  (C14b gate: platform, download + checksum cmdlets, `git`, writable `PARROT_HOME` with
  `$MinFreeKB` free, GitHub/PyPI reachable — network skipped under `-DryRun`); any failed gate
  exits 1 with the condition and a fix BEFORE any directory is created.
- Download pinned uv `0.11.28` (`uv-x86_64-pc-windows-msvc.zip` or `uv-aarch64-pc-windows-msvc.zip`
  plus `.sha256`) from `https://github.com/astral-sh/uv/releases/download/0.11.28/`, verify with
  `Get-FileHash -Algorithm SHA256`, `Expand-Archive` into a scratch dir, place `uv.exe` in
  `$PARROT_HOME\bin` write-then-rename. Never touch a user's own uv.
- `$env:UV_PYTHON_INSTALL_DIR = "$PARROT_HOME\python"`; `uv venv "$PARROT_HOME\venv" --python <py>
  --python-preference only-managed` (default `<py>` = `3.12`).
- `uv pip install --python "$PARROT_HOME\venv\Scripts\python.exe" "ai-parrot[<extras>]==<ver>"`.
  *[rev 0.5]* Until the D1 fix lands, the same call also installs `ai-parrot-tools==<ver>` (`# D1 bridge`;
  removed by the change that lands the fix).
- Shims: COPY `venv\Scripts\{parrot,wikitoolkit,bookstore}.exe` into `$PARROT_HOME\bin` (copy to
  `*.tmp` then `Move-Item -Force`). Do NOT put `venv\Scripts` on PATH — it would shadow `python`.
- Add `$PARROT_HOME\bin` to the **User** PATH idempotently via
  `[Environment]::SetEnvironmentVariable('Path', …, 'User')` (never `Machine`), also prepend it to
  the current session's `$env:Path`, and print a "reopen your terminal" notice.
- After the base runtime is installed (shims + user PATH), run
  `& "$PARROT_HOME\bin\parrot.exe" self doctor --runtime-only` with
  `$env:PARROT_VENV = "$PARROT_HOME\venv"` through `Run`; a non-zero `$LASTEXITCODE` throws, which
  fires the catch-rollback (doctor's suggested fixes are already on stdout). Never the plain
  `self doctor`: repository/host/component failures must not roll back a healthy runtime. Only
  announced under `-DryRun`.
- Then run `& "$PARROT_HOME\bin\parrot.exe" self add <c>` for each `-With` component.
- Rollback (`trap`/`try…catch`) removes ONLY paths this run created and restores the user PATH
  value if this run changed it.
- Extend `test_install_powershell.py` with static assertions (always run) and pwsh-gated parse /
  dry-run tests (skipped when `pwsh` is absent, matching the existing soft pattern), including the
  C14 gate-order, plan-output and gate-before-write tests.

**NOT in scope**:
- `install-parrot.sh` (TASK-4074); CI legs + `SHA256SUMS` (TASK-4076); docs (TASK-4095).
- `parrot self update` re-copying shims after an upgrade — owned by TASK-4080 (see FILL IN on
  trampolines; record the requirement in the Completion Note).
- `parrot self doctor` itself and its SDD readiness checks (C15) — TASK-4080; this script only
  calls it. The full dependency check list lives once, in doctor (proposal C14/C15 decision);
  this script keeps only the pre-install gate.
- Machine-scope PATH, code signing, `winget` changes, project-mode behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.ps1` | MODIFY | `-Global` mode, new params, C14a plan paragraph, C14b preflight gate, pinned-uv bootstrap, exe shims, user PATH, post-install doctor, rollback |
| `packages/ai-parrot/tests/docs/test_install_powershell.py` | MODIFY | static + pwsh-gated tests for `-Global`, incl. C14 gate order / plan / gate-before-write |

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
- ~~a `parrot self` command (`self add`, `self doctor`, `self doctor --runtime-only`)~~ — TASK-4080
  (`--runtime-only` is a rev-0.2 addition there: managed uv, Python, runtime entry points and
  PATH only; mutually exclusive with `--sdd`); only announced under `-DryRun`.
- ~~`Test-Preflight`, `Write-Plan`, `$MinFreeKB`, `$RawBase`, any GitHub/PyPI reachability check
  in the `.ps1`~~ — new here (proposal C14a/C14b); network checks must be skipped under `-DryRun`.
- ~~a windows-arm64 core wheel~~ — TASK-4094's matrix is windows AMD64 only, so the platform gate
  refuses `Arm64` for `-Global` (the uv asset for arm64 exists, the ai-parrot wheel does not).
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
- **Gate before write (C14b)**: `Test-Preflight` runs before `$Created` is populated and before
  the first `New-Item` — *why*: a failed gate must leave nothing to roll back. Order: platform
  (`OSArchitecture -eq 'X64'`; `Arm64` refused — no windows-arm64 core wheel in TASK-4094) →
  cmdlets (`Get-Command Invoke-WebRequest, Get-FileHash`) → `git` (`Get-Command git`) →
  `PARROT_HOME` writable (nearest existing ancestor; probe with a `[IO.File]::Create` of a temp
  name then delete — the ONLY permitted write, inside the ancestor that already exists, never
  creating `PARROT_HOME`) + free space (`[IO.DriveInfo]::new($ancestor).AvailableFreeSpace / 1KB`
  ≥ `$MinFreeKB = 2097152`, 2 GiB) → network (`Invoke-WebRequest -Method Head -UseBasicParsing`
  against `https://github.com` and `https://pypi.org/simple/`; skipped under `-DryRun` with a
  printed notice). Failures: `Write-Error "preflight: <condition> — fix: <fix>"; exit 1`.
- **Post-install runtime check (C14b)**: `Run -Why 'verify the managed runtime (parrot self doctor
  --runtime-only)' -Cmd { $env:PARROT_VENV = $venv; & (Join-Path $bin 'parrot.exe') self doctor
  --runtime-only; if ($LASTEXITCODE) { throw "parrot self doctor --runtime-only failed (exit
  $LASTEXITCODE) — see its suggested fixes above" } }` sits after `Add-UserPath` and before the
  `-With` loop — *why*: a broken base runtime rolls back before components are added; native
  commands do not throw on non-zero exit, hence the explicit `$LASTEXITCODE` check. `PARROT_VENV`
  pins the launcher (TASK-4071: first in the resolution order) to the venv just built, so a
  project `.venv` in the invoking directory is never what gets checked; clear it afterwards
  (`Remove-Item Env:PARROT_VENV`). `--runtime-only` is mandatory — the plain scope adds
  repository readiness (`gh` auth, committed ledger, SDD asset currency — C15), host-config and
  component checks, none of which may roll back a healthy runtime.
- **Plan paragraph (C14a)**: `Write-Plan` is the FIRST output of `-Global` (before the gate), one
  paragraph on stdout: uv version + URL + `.sha256` verification, `PARROT_HOME\{bin,venv,python}` +
  the user PATH edit, "a uv already on your PATH is never used or modified", and the non-piped
  alternative (`Invoke-WebRequest` `install-parrot.ps1` + `SHA256SUMS` from `$RawBase`, compare
  `Get-FileHash`, read, run). Printed under `-DryRun` too.
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
   *why*: codex S10. `Write-Plan` and `Test-Preflight` are the first two things `Install-Global`
   does (C14a/C14b); the post-install doctor step follows `Add-UserPath` (C14b).
4. Extend the test file with static assertions (no pwsh needed) and pwsh-gated runtime checks,
   including the C14 ones.

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
$MinFreeKB = 2097152   # C14b gate: 2 GiB free under PARROT_HOME (managed CPython + venv + wheel cache)
$RawBase = 'https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install'   # C14a non-piped alternative

function Write-Plan([string]$Url, [string]$Spec, [string]$Home_, [string]$Py) {  # C14a — first output; no side effects
  Write-Host @"
This installer will download uv $UvVersion from $Url and verify it against $Url.sha256,
create $Home_\{bin,venv,python} (a uv-managed Python $Py and a venv with $Spec),
and add $Home_\bin to your USER PATH (never Machine). A uv already on your PATH is never used
or modified. Existing $Home_ data is never touched.
Prefer not to pipe a download into PowerShell? Invoke-WebRequest $RawBase/install-parrot.ps1 and
$RawBase/SHA256SUMS, compare (Get-FileHash install-parrot.ps1).Hash with the SHA256SUMS line, read
the script, then run it.
"@
}

function Test-Preflight([string]$Home_) {  # C14b — read-only gate, in order; never creates PARROT_HOME
  $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
  if ("$arch" -ne 'X64') { Write-Error "preflight: unsupported platform windows-$arch — fix: -Global needs an x64 Windows (no windows-$arch core wheel yet); use a project install"; exit 1 }
  foreach ($c in @('Invoke-WebRequest', 'Get-FileHash')) { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { Write-Error "preflight: $c unavailable — fix: use Windows PowerShell 5.1+ or PowerShell 7"; exit 1 } }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Error 'preflight: git not found — fix: install Git for Windows (the SDD flow and parrot self doctor need it)'; exit 1 }
  $anc = $Home_; while (-not (Test-Path $anc)) { $anc = Split-Path -Parent $anc }   # nearest existing ancestor
  # FILL IN: writability probe — create+delete a temp file inside $anc; on failure
  #          Write-Error "preflight: $anc is not writable — fix: set PARROT_HOME to a writable directory"; exit 1
  $freeKB = [math]::Floor(([IO.DriveInfo]::new((Resolve-Path $anc).Path)).AvailableFreeSpace / 1KB)
  if ($freeKB -lt $MinFreeKB) { Write-Error "preflight: only ${freeKB}KB free under $anc (need $MinFreeKB) — fix: free disk space or set PARROT_HOME elsewhere"; exit 1 }
  if ($DryRun) { Write-Host 'preflight: network checks skipped (-DryRun)'; return }
  # FILL IN: Invoke-WebRequest -Method Head -UseBasicParsing against https://github.com and https://pypi.org/simple/;
  #          on failure Write-Error "preflight: <host> unreachable — fix: check your network/proxy"; exit 1
  Write-Host 'preflight: ok'
}

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
  # D1 bridge *[rev 0.5]* — core-only `wikitoolkit mcp` still needs parrot_tools; same pin; drop when the D1 fix lands
  $toolsSpec = 'ai-parrot-tools'; if ($Version) { $toolsSpec = "$toolsSpec==$Version" }
  $bin = Join-Path $home_ 'bin'; $venv = Join-Path $home_ 'venv'; $uv = Join-Path $bin 'uv.exe'
  $dl = Join-Path ([IO.Path]::GetTempPath()) "parrot-uv-$PID"
  Write-Plan $url $spec $home_ $py      # C14a — before anything else
  Test-Preflight $home_                 # C14b — exits 1 on any failed gate; nothing written yet
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
    Run -Why "install $spec into the managed venv" -Cmd { & $uv pip install --python (Join-Path $venv 'Scripts\python.exe') $spec $toolsSpec }  # *[rev 0.5]* $toolsSpec = D1 bridge
    foreach ($s in @('parrot', 'wikitoolkit', 'bookstore')) {
      $src = Join-Path $venv "Scripts\$s.exe"; $dst = Join-Path $bin "$s.exe"
      Run -Why "expose $s" -Cmd { Copy-Item $src "$dst.tmp" -Force; Move-Item "$dst.tmp" $dst -Force }
    }
    Run -Why "add $bin to the user PATH" -Cmd { Add-UserPath $bin }
    # C14b — runtime scope only, pinned to the venv just built; native commands never throw on non-zero
    #        exit, so the explicit check routes a RUNTIME failure to the catch-rollback
    Run -Why 'verify the managed runtime (parrot self doctor --runtime-only)' -Cmd {
      $env:PARROT_VENV = $venv
      try {
        & (Join-Path $bin 'parrot.exe') self doctor --runtime-only
        if ($LASTEXITCODE) { throw "parrot self doctor --runtime-only failed (exit $LASTEXITCODE) — see its suggested fixes above" }
      } finally { Remove-Item Env:PARROT_VENV -ErrorAction SilentlyContinue }
    }
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
`-DryRun` stays total; `Write-Plan` and `Test-Preflight` are read-only and run before `$Created`
exists, so a failed gate leaves no trace (C14); the doctor step is the last base-install step, so
its failure rolls back the base runtime but never half-added components. `$PSBoundParameters` inside `Install-Global` refers to the FUNCTION's bound
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


def test_preflight_gate_precedes_first_write() -> None:
    """C14b: Write-Plan and Test-Preflight are called before $Created exists / the first New-Item in Install-Global."""
    body = _TEXT[_TEXT.index("function Install-Global") :]
    assert body.index("Write-Plan ") < body.index("Test-Preflight ") < body.index("$script:Created =") < body.index("New-Item")
    for needle in ("preflight: unsupported platform", "git not found", "$MinFreeKB", "network checks skipped (-DryRun)"):
        assert needle in _TEXT, needle


def test_post_install_doctor_precedes_components() -> None:
    """C14b: `self doctor --runtime-only` runs after Add-UserPath and before any `self add`, pinned via PARROT_VENV."""
    body = _TEXT[_TEXT.index("function Install-Global") :]
    assert body.index("Add-UserPath $bin") < body.index("self doctor --runtime-only") < body.index("self add $c")
    assert "if ($LASTEXITCODE) { throw" in body
    assert "$env:PARROT_VENV = $venv" in body
    assert "self doctor\n" not in body and "self doctor;" not in body, "plain-scope doctor must never gate the install"


def _run_offline_install(tmp_path: Path, *, fake_parrot: str) -> subprocess.CompletedProcess[str]:
    """C14b harness (pwsh-gated): a real -Global run with fakes — no network, no real HOME, no real PATH edit."""
    # FILL IN: fixture zip holding a fake `uv.exe` (a .cmd/.ps1 shim on Windows, a sh script under Linux
    #          pwsh) whose `venv <dir>` creates <dir>\Scripts\{python,wikitoolkit,bookstore}.exe stubs and
    #          writes `fake_parrot` as <dir>\Scripts\parrot.exe; `pip install` no-op) + its .sha256; stub
    #          Invoke-WebRequest via a module on PSModulePath that copies the fixture for the zip/.sha256 URLs
    #          and returns 200 for -Method Head; HOME/PARROT_HOME under tmp; `[Environment]::SetEnvironmentVariable`
    #          User scope must be diverted (e.g. an env flag the script honours ONLY under test is NOT allowed —
    #          instead assert on the announced Add-UserPath call and the restored value) — bounded by the two tests


_PARROT_RUNTIME_BROKEN = "echo 'uv: missing — fix: rerun the bootstrap'; exit 1"
_PARROT_REPO_NOT_READY = (
    "if ($args -contains '--runtime-only') { 'runtime: ok'; exit 0 }; "
    "'gh: not authenticated — fix: gh auth login'; 'ledger: uncommitted'; exit 1"
)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_post_install_runtime_failure_rolls_back(tmp_path: Path) -> None:
    """C14b: a failing `self doctor --runtime-only` removes what the run created and restores the user PATH."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_RUNTIME_BROKEN)
    assert result.returncode != 0
    assert "self doctor --runtime-only" in result.stdout and "suggested fixes above" in (result.stderr + result.stdout)
    assert not (tmp_path / "home" / ".parrot").exists()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_post_install_repo_readiness_failures_keep_runtime(tmp_path: Path) -> None:
    """C14b: unauthenticated gh / uncommitted ledger / outdated SDD assets never roll back a healthy runtime."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY)
    assert result.returncode == 0, result.stderr
    assert "gh: not authenticated" not in result.stdout
    home = tmp_path / "home" / ".parrot"
    assert (home / "bin" / "parrot.exe").exists() and (home / "venv").exists()


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
    assert "ai-parrot-tools==9.9.9" in result.stdout   # *[rev 0.5]* D1 bridge, same pin — remove with the bridge
    assert not home.exists()
    # C14a/C14b: plan paragraph and gate summary precede the first "->" announcement
    assert "never used or modified" in result.stdout and "SHA256SUMS" in result.stdout
    assert result.stdout.index("preflight: network checks skipped") < result.stdout.index("->")


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_global_gate_unwritable_home_exits_before_write(tmp_path: Path) -> None:
    """C14b: PARROT_HOME under a read-only parent fails the writability gate with nothing written."""
    ro = tmp_path / "ro"; ro.mkdir(); ro.chmod(0o555)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT), "-Global"],
        capture_output=True, text=True, check=False,
        env={"PARROT_HOME": str(ro / ".parrot"), **{k: v for k, v in os.environ.items() if k != "PARROT_HOME"}},
    )
    assert result.returncode == 1 and "not writable" in (result.stderr + result.stdout)
    assert not (ro / ".parrot").exists()
    # FILL IN: skip when running as root (root ignores 0o555); on Linux pwsh the platform gate sees
    #          the host arch — run with `-DryRun` removed only if the X64 check passes there, otherwise
    #          assert the platform refusal instead — bounded by "exits 1 before any write"
```
**Why**: static assertions always run in CI (pwsh is not guaranteed); the runtime tests follow the
existing soft `skipif` pattern. The C14 static tests pin the ORDER (gate before the first write,
doctor before components) because that order is the whole safety argument. FILL IN: replace the
`__import__("os")` with a top-level `import os` (add it to the imports) — bounded by ruff.

### FILL IN checklist
- [ ] `install-parrot.ps1::Resolve-Extras` — move lines 101-121 verbatim into `$script:` scope.
- [ ] `install-parrot.ps1::Install-Global` — refuse `-Venv`/`-WithWiki`/`-SystemDeps`.
- [ ] `install-parrot.ps1::Install-Global` — capture script-level `-Python` bound-ness into `$script:PythonSet`.
- [ ] `install-parrot.ps1::Install-Global` — verify zip layout, copy `uv.exe` (+`uvx.exe`) write-then-rename.
- [ ] `install-parrot.ps1::Install-Global` catch — reverse-remove `$Created`, restore user PATH if changed.
- [ ] Trampoline-copy validity — confirm with spike S1 windows leg (TASK-4068); else re-copy rule for `self update` (TASK-4080).
- [ ] TLS 1.2 enablement for Windows PowerShell 5.1.
- [ ] Test file — top-level `import os`.
- [ ] `install-parrot.ps1::Test-Preflight` — writability probe (create+delete inside the existing ancestor) and the GitHub/PyPI HEAD checks; bounded by "skipped under -DryRun" and "never creates PARROT_HOME".
- [ ] `test_global_gate_unwritable_home_exits_before_write` — root skip + platform-gate behaviour under Linux pwsh.
- [ ] `test_install_powershell.py::_run_offline_install` — fixture zip, fake `uv.exe`/`parrot.exe`, stubbed `Invoke-WebRequest`, diverted user-PATH write; bounded by the two C14b outcomes. If the User-scope PATH write cannot be diverted safely under pwsh on CI, keep the two tests pwsh-gated AND mark them `xfail(strict=False)` with the reason recorded in the Completion Note — never let a test edit the developer's real user PATH.

---

## Acceptance Criteria

- [ ] `-Global` is dispatched before the Python guard (static test) — codex S10.
- [ ] `-Global -DryRun` performs no download and creates nothing under `PARROT_HOME` (pwsh-gated test).
- [ ] Pinned uv `0.11.28` is downloaded for `x86_64`/`aarch64` `pc-windows-msvc` and verified with
      `Get-FileHash` against the release `.sha256`; a user's own uv is never touched.
- [ ] Managed Python lives under `$PARROT_HOME\python`; venv built with Python 3.12 by default.
- [ ] *[rev 0.5]* D1 bridge: until the core-only `wikitoolkit mcp` fix lands, the install call also
      installs `ai-parrot-tools` with the same pin as `ai-parrot` (one `uv pip install`, `# D1 bridge`);
      if the fix is already on the branch, no bridge is added.
- [ ] `parrot.exe`/`wikitoolkit.exe`/`bookstore.exe` are COPIED into `$PARROT_HOME\bin`
      (write-then-rename); `venv\Scripts` is never put on PATH.
- [ ] User PATH (never Machine) edited idempotently via `[Environment]::SetEnvironmentVariable`,
      with a reopen-terminal notice (spec §5 Windows AC).
- [ ] Rollback removes only paths created by this run; pre-existing `~/.parrot` data intact.
- [ ] **C14a**: `-Global` (also under `-DryRun`) prints, before any `->` line, what is downloaded
      (uv `0.11.28`, URL, `.sha256`), where it writes (`PARROT_HOME\{bin,venv,python}` + user PATH),
      that the user's own uv is never used or modified, and the non-piped alternative (raw-URL
      `install-parrot.ps1` + `SHA256SUMS`, `Get-FileHash`, read, run).
- [ ] **C14b gate before write**: a non-x64 platform, a missing `Invoke-WebRequest`/`Get-FileHash`,
      a missing `git`, an unwritable `PARROT_HOME` ancestor, less than `$MinFreeKB` free, or an
      unreachable GitHub/PyPI each exit 1 with `preflight: <condition> — fix: <fix>` BEFORE any
      directory is created; `-DryRun` skips only the network gates and says so.
- [ ] **C14b post-install runtime check**: after shims + user PATH the script runs
      `parrot.exe self doctor --runtime-only` with `PARROT_VENV` pinned to the new venv (never the
      plain scope); a non-zero exit code throws into the existing catch-rollback (only this run's
      paths; user PATH restored); `-DryRun` only announces the call.
- [ ] **C14b readiness never rolls back**: with a `parrot.exe` whose `--runtime-only` passes while
      the plain `self doctor` fails (unauthenticated `gh`, uncommitted ledger, outdated SDD
      assets), the run exits 0 and `bin\`, `venv\` and the user PATH entry remain.
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
def test_global_dry_run(tmp_path): ...                 # pwsh-gated runtime dry run (+ C14a plan, gate summary before "->")
def test_preflight_gate_precedes_first_write(): ...    # static, C14b order: Write-Plan < Test-Preflight < $Created < New-Item
def test_post_install_doctor_precedes_components(): ...# static, C14b: Add-UserPath < self doctor --runtime-only < self add; PARROT_VENV pinned
def test_global_gate_unwritable_home_exits_before_write(tmp_path): ...  # pwsh-gated: read-only parent → exit 1, nothing written
def test_post_install_runtime_failure_rolls_back(tmp_path): ...         # pwsh-gated, offline fakes: --runtime-only exit 1 → rollback
def test_post_install_repo_readiness_failures_keep_runtime(tmp_path): ...  # pwsh-gated: --runtime-only ok, plain doctor fails → stays
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
