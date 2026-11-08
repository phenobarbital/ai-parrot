# HOTFIX-installer-uv-shadowing-3: PowerShell installer — same uv model as the POSIX installer

**Feature**: installer-uv-shadowing (the `--global` installer's pinned uv shadows the user's uv on PATH)
**Spec**: `sdd/briefs/installer-uv-shadowing.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-installer-uv-shadowing-2
**Assigned-to**: unassigned

---

## Context

`install-parrot.ps1 -Global` has the same bug as the POSIX installer. It copies `uv.exe` and `uvx.exe` into
`$home_\bin` (`install-parrot.ps1:221-228`) and prepends `$bin` to the User PATH (`:167`), so it shadows the
user's uv. This task ports task 2's model, keeping the two installers equivalent:

- a compatible system uv (`>=0.11.28,<0.12`, outside `$home_`) is recorded in `$home_\libexec\uv-path`;
- otherwise the pinned `uv.exe` goes to `$home_\libexec` (no `uvx.exe`);
- a version-skew guard for older ai-parrot releases;
- legacy `bin\uv.exe` / `bin\uvx.exe` are removed after a successful install.

Windows is not officially supported (`:137`), so its tests are mostly static. The pwsh harness tests are skipped
when `pwsh` is absent (brief assumption E). This task depends on task 2 because both rewrite `SHA256SUMS` and the
same doc page.

---

## Scope

- Add `$UvMin = '0.11.28'; $UvMax = '0.12'` next to `$UvVersion` (`:116`), with a parity test against `parrot.self_.uv`.
- Add the functions `Get-UvVersion`, `ConvertTo-UvVersion` (pads to 3 parts, because .NET orders `0.12` before
  `0.12.0`), `Test-UvInRange`, `Find-SystemUv` and `Select-Uv` (sets the mode before `Write-Plan`).
- `Install-Global`: per-mode download, record or reuse into `$home_\libexec`; `& $uv` for venv and pip; the
  version-skew guard after pip; legacy cleanup after the credentials step, warn-only.
- Make `Write-Plan` mode-aware. Its last promise becomes "Your own uv is never modified, moved or removed".
- Tests in `tests/docs/test_install_powershell.py`; regenerate `SHA256SUMS`; update the Windows part of
  `docs/getting-started.md` (around lines 170-180).

**NOT in scope**: the POSIX installer (task 2); the Python runtime (task 1); Machine-scope PATH (never touched);
pinning the uv checksum (`issue:6e31d9355edc`); the `-Python` default (`issue:a786fec203e1`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.ps1` | MODIFY | Range constants, system-uv detection, libexec layout, skew guard, legacy cleanup, plan text |
| `packages/ai-parrot/tests/docs/test_install_powershell.py` | MODIFY | Parity test, static ordering and layout checks, updated plan-text assertions |
| `scripts/install/SHA256SUMS` | MODIFY | Regenerated |
| `docs/getting-started.md` | MODIFY | Windows `-Global` description |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/main` on 2026-11-08. Re-grep the verbatim anchors (line numbers drift).

### Verified Imports
```python
from parrot.self_ import uv as uv_mod  # created by HOTFIX-installer-uv-shadowing-1
```

### Existing Signatures to Use
```powershell
# scripts/install/install-parrot.ps1
$UvVersion = '0.11.28'                                          # line 116
function Write-Plan([string]$Url, [string]$Spec, [string]$Home_, [string]$Py) {   # line 120; line 126 = the "never used or modified" sentence
function Test-Preflight([string]$Home_) {                       # line 133
function Add-UserPath([string]$Dir) {                           # line 162; prepends at 167 (unchanged)
function Install-Global {                                       # line 185
  $bin = Join-Path $home_ 'bin'; $venv = Join-Path $home_ 'venv'; $uv = Join-Path $bin 'uv.exe'   # line 203
  $dl = Join-Path ([IO.Path]::GetTempPath()) "parrot-uv-$PID"   # line 204
  Write-Plan $url "$spec $tools" $home_ $py                     # line 205
  $script:Created = [System.Collections.Generic.List[string]]::new()   # line 207
  # lines 213-229: download / verify / extract / 'place uv in the managed bin dir' (uv.exe + uvx.exe)
  # line 235: & $uv venv ... ; line 237: & $uv pip install --python (Join-Path $venv 'Scripts\python.exe') $spec $tools
  # lines 248-254: self doctor --runtime-only (throws on $LASTEXITCODE)
  # lines 257-263: credentials step (warn-only); then -With components; catch → rollback $Created; finally removes $dl
```
```python
# packages/ai-parrot/tests/docs/test_install_powershell.py
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.ps1"   # line 16
def _flat(text: str) -> str:                       # line 21
_TEXT                                              # the script text, used by the static tests
def test_global_rejects_unknown_component(tmp_path) -> None:   # line 89; asserts the old sentence is ABSENT at 101
def test_global_pins_and_verifies_uv() -> None:    # line 110
def test_post_install_doctor_precedes_components() -> None:   # line 126 — index-ordering pattern to copy
def test_global_dry_run(tmp_path) -> None:         # line 210 (pwsh-gated); asserts the old sentence at 227
def _run_offline_install(tmp_path, *, fake_parrot) -> ...:   # line 136 (pwsh-gated, _OFFLINE_XFAIL)
```

### Does NOT Exist
- ~~`$UvMin` / `$UvMax` / `Select-Uv` / `Find-SystemUv`~~: added by this task.
- ~~Machine-scope PATH edits~~: forbidden (`test_global_pins_and_verifies_uv` asserts `'Machine'` is absent).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/install/install-parrot.ps1", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/docs/test_install_powershell.py", "action": "MODIFY"},
    {"path": "scripts/install/SHA256SUMS", "action": "MODIFY"},
    {"path": "docs/getting-started.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/docs/test_install_powershell.py#test_global_pins_and_verifies_uv",
    "sym:packages/ai-parrot/tests/docs/test_install_powershell.py#test_post_install_doctor_precedes_components",
    "sym:packages/ai-parrot/tests/docs/test_install_powershell.py#test_global_dry_run"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The user's uv is never written, moved or deleted. The only `Remove-Item` targets added are `$bin\uv.exe` and
  `$bin\uvx.exe`.
- `Select-Uv` is read-only (runs `<uv> --version` only) and runs before `Write-Plan`, under `-DryRun` too.
- Record the path as `Get-Command` reports it (`.Source`), without resolving symlinks or junctions.
- Compare versions with `[version]` objects padded to three parts.
- Every side effect goes through `Run`, and every new path goes into `$script:Created`.
- Legacy cleanup is warn-only and comes after the runtime doctor (the catch-block rollback cannot restore deleted files).
- Keep the `'User'`-scope-only PATH behavior and `Get-FileHash` verification (static tests check both).

---

## Implementation Blueprint

### Steps (in order)
1. Add the constants and helpers. *Why*: decision 1, and installer parity with POSIX.
2. Call `Select-Uv` before `Write-Plan`, and pass the mode in. *Why*: the plan states what will happen (C14a).
3. Branch the uv step per mode into `$libexec`; drop `uvx.exe`. *Why*: decisions 2-3.
4. Add the skew guard after pip and the legacy cleanup after credentials. *Why*: assumptions A and C.
5. Tests, then `SHA256SUMS`, then docs.

### `scripts/install/install-parrot.ps1` (MODIFY)
```powershell
# AFTER — insert below line 116 ($UvVersion = '0.11.28')
$UvMin = '0.11.28'; $UvMax = '0.12'   # compatible uv: UvMin <= v < UvMax (kept equal to parrot.self_.uv by tests)

function ConvertTo-UvVersion([string]$V) {  # '0.12' -> [version]'0.12.0'; $null when unparsable
  if ($V -notmatch '^\d+(\.\d+){0,3}') { return $null }
  $parts = @($Matches[0] -split '\.'); while ($parts.Count -lt 3) { $parts += '0' }
  return [version]($parts -join '.')
}
function Get-UvVersion([string]$Exe) {  # '0.11.28' from `<exe> --version`; $null when it cannot run
  try { $out = (& $Exe --version 2>$null) -join ' ' } catch { return $null }
  if ($LASTEXITCODE -or -not $out) { return $null }
  foreach ($tok in ($out -split '\s+')) { if ($tok -match '^\d+(\.\d+)*') { return $Matches[0] } }
  return $null
}
function Test-UvInRange([string]$V) {
  $v_ = ConvertTo-UvVersion $V; if ($null -eq $v_) { return $false }
  return ($v_ -ge (ConvertTo-UvVersion $UvMin)) -and ($v_ -lt (ConvertTo-UvVersion $UvMax))
}
function Find-SystemUv([string]$Home_) {  # first uv.exe on PATH outside $Home_\bin and $Home_\libexec; $null if none
  # FILL IN: Get-Command uv.exe -All -CommandType Application -ErrorAction SilentlyContinue; skip entries whose
  # directory equals (case-insensitive, trailing '\' trimmed, via Resolve-Path when it exists) $Home_\bin or
  # $Home_\libexec; return the first .Source.
}
function Select-Uv([string]$Home_) {  # read-only: sets $script:UvMode managed|system|download, UvBin, SysUv, SysUvVer
  # FILL IN: same order as choose_uv in install-parrot.sh — $Home_\libexec\uv.exe in range → managed;
  # else Find-SystemUv in range → system; else download (UvBin = $Home_\libexec\uv.exe).
}
```
```powershell
# Write-Plan: add a [string]$Mode parameter (and use $script:SysUv / $script:SysUvVer); three variants worded as in
# install-parrot.sh's print_plan. Replace line 126's sentence with:
# "Your own uv is never modified, moved or removed; uv.exe/uvx.exe that an older parrot installer left in
#  $Home_\bin are removed after a successful install."
```
```powershell
# In Install-Global:
#  - before Write-Plan:   Select-Uv $home_   ;  $libexec = Join-Path $home_ 'libexec'  ;  $uv = $script:UvBin
#  - download mode only: the scratch dir + download/verify/extract steps, then
#      Run -Why "place uv $UvVersion in $libexec (not on PATH)" -Cmd { ... copy uv.exe only, write-then-rename ... }
#    creating $libexec first (tracked in $Created)
#  - system mode: create $libexec (tracked), then
#      Run -Why "record your uv $($script:SysUvVer) ($($script:SysUv)) in $libexec\uv-path" -Cmd {
#        Set-Content -LiteralPath "$libexec\uv-path.tmp" -Value $script:SysUv -Encoding utf8
#        Move-Item "$libexec\uv-path.tmp" "$libexec\uv-path" -Force }     (track uv-path in $Created when new)
#  - managed mode: Write-Host "Reusing uv at $uv"
#  - after the pip step, before the shims — skew guard (assumption A):
#      if (-not $DryRun) { & (Join-Path $venv 'Scripts\python.exe') -c 'import parrot.self_.uv' 2>$null
#        if ($LASTEXITCODE) { $script:UvLegacyCompat = $true; Write-Warning '...predates the libexec uv layout...'
#          Run -Why "place uv $UvVersion in $bin for this older ai-parrot" -Cmd { ... } } }
#    FILL IN the -Cmd: copy $libexec\uv.exe when its version is exactly $UvVersion, otherwise download+verify the
#    pinned zip; never copy the user's uv.
#  - after the credentials try/catch and before the -With loop — legacy cleanup when -not $script:UvLegacyCompat:
#      foreach ($n in @('uv.exe', 'uvx.exe')) { $p = Join-Path $bin $n; if (Test-Path $p) {
#        try { Run -Why "remove the legacy $p (an older installer put it on PATH, shadowing your uv)" -Cmd { Remove-Item -Force -LiteralPath $p } }
#        catch { Write-Warning "could not remove $p: $($_.Exception.Message)" } } }
```
**Why this shape**: it mirrors `install-parrot.sh` step for step, so a reviewer can diff the two, and the parity
test keeps the constants equal.

### FILL IN checklist
- [ ] `test_uv_constants_match_runtime`: parse `$UvVersion = '…'`, `$UvMin = '…'` and `$UvMax = '…'` from `_TEXT`
      and compare them with `uv_mod`.
- [ ] Update `test_global_rejects_unknown_component` (line 101) and `test_global_dry_run` (line 227) to the new sentence.
- [ ] Static: `'libexec'` appears in `Install-Global`; the old `@('uv.exe', 'uvx.exe')` placement list is gone;
      `import parrot.self_.uv` appears after the pip step; the legacy cleanup comes after `self doctor --runtime-only`
      (index ordering, as in `test_post_install_doctor_precedes_components`).
- [ ] pwsh-gated harness tests: update any `bin\uv.exe` expectations to `libexec` (they are skipped without pwsh).

---

## Acceptance Criteria

- [ ] `$UvVersion`, `$UvMin` and `$UvMax` equal `parrot.self_.uv`'s constants.
- [ ] The plan is mode-aware and no longer says "never used or modified".
- [ ] `uv.exe` goes to `$home_\libexec`, never `$home_\bin`, except under the skew guard. `uvx.exe` is no longer installed.
- [ ] A compatible system uv is recorded, not copied, and is never removed.
- [ ] Legacy `bin\uv.exe` / `bin\uvx.exe` are removed only after the runtime doctor passed, and only when the skew
      guard did not trigger.
- [ ] `SHA256SUMS` matches both installers.
- [ ] All Validation Commands pass (pwsh-gated tests may be skipped).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/docs/test_install_powershell.py -q`
- `pytest packages/ai-parrot/tests/docs/test_ci_install_wiring.py -q`
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_install_powershell.py — new static tests
import re

from parrot.self_ import uv as uv_mod


def test_uv_constants_match_runtime() -> None:
    found = {k: re.search(rf"\${k} = '([^']+)'", _TEXT).group(1) for k in ("UvVersion", "UvMin", "UvMax")}
    assert found == {"UvVersion": uv_mod.PINNED_UV_VERSION, "UvMin": uv_mod.UV_MIN_VERSION,
                     "UvMax": uv_mod.UV_MAX_VERSION}


def test_uv_goes_to_libexec_and_uvx_is_not_installed() -> None:
    body = _TEXT[_TEXT.index("function Install-Global") :]
    assert "'libexec'" in body and "@('uv.exe', 'uvx.exe')" not in body.split("legacy")[0]


def test_skew_guard_follows_pip_and_cleanup_follows_doctor() -> None:
    body = _TEXT[_TEXT.index("function Install-Global") :]
    assert body.index("pip install") < body.index("import parrot.self_.uv")
    assert body.index("self doctor --runtime-only") < body.index("remove the legacy")
```

---

## Agent Instructions

1. Work in the brief's worktree (`hotfix-installer-uv-shadowing-installer-uv-shadowing` under the worktree root),
   never on `main`. HOTFIX-installer-uv-shadowing-2 must be `done` in the per-brief index.
2. Read the brief and `install-parrot.sh` as task 2 left it. Mirror its wording and order.
3. Re-grep every verbatim anchor before editing.
4. Touch only the four listed files.
5. After the last installer edit: `cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS`.
6. Run every Validation Command with `PYTHONPATH=packages/ai-parrot/src`. Run `ruff check` on the test file.
7. Commit code: `fix(install): HOTFIX-installer-uv-shadowing-3 — PowerShell installer keeps uv off PATH, reuses a compatible uv`.
8. Close with `parrot sdd task close HOTFIX-installer-uv-shadowing-3 installer-uv-shadowing verified`, fill in the
   Completion Note, and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
