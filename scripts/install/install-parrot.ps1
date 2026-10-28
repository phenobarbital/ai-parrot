<#
AI-Parrot installer (Windows) — automates the AI-Parrot getting-started guide
(FEAT-586). Never destructive; announces every privileged/network command
before it runs.

.PARAMETER Provider
    Comma-separated list of provider keys: anthropic|openai|google|
    claude-code|codex-code. Default: anthropic. Named -Provider (never
    -Host: $Host is a reserved PowerShell automatic variable).

.PARAMETER Extras
    Additional ai-parrot extras, comma-separated (e.g. jev,rust).

.PARAMETER Venv
    Virtualenv directory. Default: .venv.

.PARAMETER Python
    Python interpreter to use. Default: python.

.PARAMETER WithWiki
    Run `wikitoolkit build` after install.

.PARAMETER InstallCli
    npm-install the LATEST MINOR (@latest) of the claude/codex CLI for a
    CLI-backed provider (claude-code/codex-code). Pins no version.

.PARAMETER SystemDeps
    Install OS packages via winget (opt-in; never run automatically).

.PARAMETER DryRun
    Print every command, with its purpose, without executing anything.

.PARAMETER Global
    Build the managed runtime under $env:PARROT_HOME (default ~\.parrot):
    pinned uv, uv-managed Python, venv, shims in bin\ added to the USER PATH.

.PARAMETER Version
    With -Global: pin ai-parrot and ai-parrot-tools to this version.

.PARAMETER With
    With -Global: comma-separated components to add via `parrot self add`.

.PARAMETER Help
    Show this help and exit.
#>
[CmdletBinding()]
param(
  [string]$Provider = 'anthropic',   # NOT -Host: $Host is reserved
  [string]$Extras = '',
  [string]$Venv = '.venv',
  [string]$Python = 'python',
  [switch]$WithWiki,
  [Alias('Global')][switch]$GlobalMode,
  [string]$Version = '',
  [string]$With = '',
  [switch]$InstallCli,
  [switch]$SystemDeps,
  [switch]$DryRun,
  [switch]$Help
)
$ErrorActionPreference = 'Stop'

function Show-Usage {
  Get-Help $PSCommandPath -Full | Out-String -Width 100
}

if ($Help) {
  Show-Usage
  exit 0
}

# Run "<purpose>" { scriptblock }
# Announces the purpose + the command before running it (AC8). Under
# -DryRun it only announces — it never executes anything, so callers must
# route every side-effecting command through it to keep -DryRun total.
function Run {
  param(
    [Parameter(Mandatory = $true)][string]$Why,
    [Parameter(Mandatory = $true)][scriptblock]$Cmd
  )
  Write-Host "-> $($Why): $($Cmd.ToString().Trim())"
  if (-not $DryRun) {
    # Native commands never throw on a non-zero exit: reset, run, then turn a failure into a terminating error.
    $global:LASTEXITCODE = 0
    & $Cmd
    if ($LASTEXITCODE) { throw "$Why failed (exit $LASTEXITCODE)" }
  }
}

function Resolve-Extras {
  # Map provider keys to ai-parrot extras (mirrors install-parrot.sh / guide §3).
  $script:AllExtras = $Extras
  $script:CliProviders = @()
  foreach ($p in ($Provider -split ',')) {
    switch ($p) {
      'anthropic' { $extra = 'anthropic' }
      'openai' { $extra = 'openai' }
      'google' { $extra = 'google' }
      'claude-code' { $extra = 'claude-agent'; $script:CliProviders += 'claude-code' }
      'codex-code' { $extra = 'codex-agent'; $script:CliProviders += 'codex-code' }
      default {
        Write-Error "Unknown provider '$p'; expected one of: anthropic|openai|google|claude-code|codex-code"
        exit 1
      }
    }
    if ([string]::IsNullOrEmpty($script:AllExtras)) {
      $script:AllExtras = $extra
    } else {
      $script:AllExtras = "$script:AllExtras,$extra"
    }
  }
}
$UvVersion = '0.11.28'
$MinFreeKB = 2097152   # C14b gate: 2 GiB free under PARROT_HOME (managed CPython + venv + wheel cache)
$RawBase = 'https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install'   # C14a non-piped alternative

function Write-Plan([string]$Url, [string]$Spec, [string]$Home_, [string]$Py) {  # C14a — first output; no side effects
  Write-Host @"
This installer will download uv $UvVersion from $Url and verify it against $Url.sha256,
create $Home_\{bin,venv,python} (a uv-managed Python $Py and a venv with $Spec),
and add $Home_\bin to your USER PATH (never Machine).
A uv already on your PATH is never used or modified. Existing $Home_ data is never touched.
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
  $probe = Join-Path $anc ".parrot-write-probe-$PID"
  try { [IO.File]::Create($probe).Dispose(); Remove-Item -Force $probe }
  catch { Write-Error "preflight: $anc is not writable — fix: set PARROT_HOME to a writable directory"; exit 1 }
  $freeKB = [math]::Floor(([IO.DriveInfo]::new((Resolve-Path $anc).Path)).AvailableFreeSpace / 1KB)
  if ($freeKB -lt $MinFreeKB) { Write-Error "preflight: only ${freeKB}KB free under $anc (need $MinFreeKB) — fix: free disk space or set PARROT_HOME elsewhere"; exit 1 }
  if ($DryRun) { Write-Host 'preflight: network checks skipped (-DryRun)'; return }
  foreach ($u in @('https://github.com', 'https://pypi.org/simple/')) {
    try { Invoke-WebRequest -Uri $u -Method Head -UseBasicParsing | Out-Null }
    catch { Write-Error "preflight: $u unreachable — fix: check your network/proxy"; exit 1 }
  }
  Write-Host 'preflight: ok'
}

$script:OriginalUserPath = $null
$script:PythonSet = $PSBoundParameters.ContainsKey('Python')   # script-level bound-ness; the function's own $PSBoundParameters differs
$script:VenvSet = $PSBoundParameters.ContainsKey('Venv')

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
  if ($script:VenvSet -or $WithWiki -or $SystemDeps) {
    Write-Error '-Global cannot be combined with -Venv, -WithWiki or -SystemDeps'; exit 1
  }
  if ($PSVersionTable.PSVersion.Major -lt 6) {   # Windows PowerShell 5.1 needs TLS 1.2 enabled explicitly
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
  }
  $home_ = if ($env:PARROT_HOME) { $env:PARROT_HOME } else { Join-Path $HOME '.parrot' }
  $py = if ($script:PythonSet) { $Python } else { '3.12' }
  Resolve-Extras
  $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
  $target = if ("$arch" -eq 'Arm64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-pc-windows-msvc' }
  $asset = "uv-$target.zip"
  $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$asset"
  $spec = "ai-parrot[$AllExtras]"; if ($Version) { $spec = "$spec==$Version" }
  # rev 0.5 C20 — ai-parrot-tools at the same version pin (wikitoolkit mcp's wiki tools live in parrot_tools.wiki)
  $tools = 'ai-parrot-tools'; if ($Version) { $tools = "$tools==$Version" }
  $bin = Join-Path $home_ 'bin'; $venv = Join-Path $home_ 'venv'; $uv = Join-Path $bin 'uv.exe'
  $dl = Join-Path ([IO.Path]::GetTempPath()) "parrot-uv-$PID"
  Write-Plan $url "$spec $tools" $home_ $py      # C14a — before anything else
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
    Run -Why 'place uv in the managed bin dir' -Cmd {
      foreach ($n in @('uv.exe', 'uvx.exe')) {
        $f = Get-ChildItem -Path $dl -Filter $n -Recurse -File | Select-Object -First 1
        if (-not $f) { if ($n -eq 'uv.exe') { throw "uv.exe not found in $asset" } else { continue } }
        $dst = Join-Path $bin $n
        if (-not (Test-Path $dst)) { $script:Created.Add($dst) }
        Copy-Item $f.FullName "$dst.tmp" -Force; Move-Item "$dst.tmp" $dst -Force
      }
    }
    $pyDir = Join-Path $home_ 'python'
    if (-not $DryRun -and -not (Test-Path $pyDir)) { $Created.Add($pyDir) }
    $env:UV_PYTHON_INSTALL_DIR = $pyDir
    if (-not (Test-Path $venv)) {
      if (-not $DryRun) { $Created.Add($venv) }
      Run -Why "create the managed venv (Python $py)" -Cmd { & $uv venv $venv --python $py --python-preference only-managed }
    }
    Run -Why "install $spec $tools into the managed venv" -Cmd { & $uv pip install --python (Join-Path $venv 'Scripts\python.exe') $spec $tools }
    foreach ($s in @('parrot', 'wikitoolkit', 'bookstore')) {
      $src = Join-Path $venv "Scripts\$s.exe"; $dst = Join-Path $bin "$s.exe"
      Run -Why "expose $s" -Cmd {
        if (-not (Test-Path $dst)) { $script:Created.Add($dst) }
        Copy-Item $src "$dst.tmp" -Force; Move-Item "$dst.tmp" $dst -Force
      }
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
    # The base runtime is verified: a failing component warns and exits non-zero, never rolls it back (as install-parrot.sh).
    foreach ($c in ($With -split ',' | Where-Object { $_ })) {
      try { Run -Why "add component $c (parrot self add $c)" -Cmd { & (Join-Path $bin 'parrot.exe') self add $c } }
      catch { Write-Warning "'parrot self add $c' failed: $($_.Exception.Message); the base runtime stays installed"; $script:ComponentFailed = $true }
    }
  } catch {
    Write-Warning "install failed: $($_.Exception.Message) — rolling back what this run created"
    for ($i = $Created.Count - 1; $i -ge 0; $i--) { Remove-Item -Recurse -Force -LiteralPath $Created[$i] -ErrorAction SilentlyContinue }
    if ($null -ne $script:OriginalUserPath) { [Environment]::SetEnvironmentVariable('Path', $script:OriginalUserPath, 'User') }
    throw
  } finally {
    if (-not $DryRun -and (Test-Path $dl)) { Remove-Item -Recurse -Force $dl }
  }
}

if ($GlobalMode) { Install-Global; Write-Host 'Done.'; if ($script:ComponentFailed) { exit 1 }; exit 0 }

# Python guard (AC10) — refuse anything outside >=3.11,<3.14 BEFORE any
# other step (including -DryRun), same as the POSIX installer.
try {
  $pyver = (& $Python -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>$null).Trim()
} catch {
  Write-Error "unsupported Python: could not execute '$Python'"
  exit 1
}
if ([string]::IsNullOrEmpty($pyver) -or ($pyver -notin @('3.11', '3.12', '3.13'))) {
  Write-Error "unsupported Python $pyver; AI-Parrot needs >=3.11,<3.14"
  exit 1
}

# -SystemDeps: OS packages via winget. Opt-in only; never runs on its own.
if ($SystemDeps) {
  Run -Why 'install Python and git via winget' -Cmd { winget install Python.Python.3.12; winget install Git.Git }
}

# venv: create-or-reuse (never delete an existing one).
if (Test-Path $Venv) {
  Write-Host "Reusing existing virtualenv at $Venv"
} else {
  Run -Why 'create the virtualenv' -Cmd { & $Python -m venv $Venv }
}
$VenvPip = Join-Path $Venv 'Scripts\pip.exe'
$VenvBin = Join-Path $Venv 'Scripts'

Resolve-Extras

# Install ai-parrot + the resolved provider/extra set.
Run -Why "install ai-parrot with extras: $AllExtras" -Cmd { & $VenvPip install "ai-parrot[$AllExtras]" }

# -InstallCli: npm-install the LATEST MINOR (@latest) of each requested
# CLI-backed provider's CLI binary. Pins no version — see spec §6/AC18.
if ($InstallCli) {
  foreach ($cli in $CliProviders) {
    switch ($cli) {
      'claude-code' {
        Run -Why 'install the latest minor of the Claude Code CLI' -Cmd { npm install -g @anthropic-ai/claude-code@latest }
      }
      'codex-code' {
        Run -Why 'install the latest minor of the Codex CLI' -Cmd { npm install -g @openai/codex@latest }
      }
    }
  }
  if ($CliProviders.Count -eq 0) {
    Write-Warning '-InstallCli passed but no CLI-backed provider (claude-code/codex-code) was requested; nothing to do'
  }
}

# -WithWiki: build the local codebase knowledge graph after install.
if ($WithWiki) {
  $WikiToolkit = Join-Path $VenvBin 'wikitoolkit.exe'
  Run -Why 'build the wikitoolkit knowledge graph' -Cmd { & $WikiToolkit build }
}

Write-Host 'Done.'
