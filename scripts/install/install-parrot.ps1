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
    & $Cmd
  }
}

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

# Map provider keys to ai-parrot extras (mirrors install-parrot.sh / guide §3).
$AllExtras = $Extras
$CliProviders = @()
foreach ($p in ($Provider -split ',')) {
  switch ($p) {
    'anthropic' { $extra = 'anthropic' }
    'openai' { $extra = 'openai' }
    'google' { $extra = 'google' }
    'claude-code' { $extra = 'claude-agent'; $CliProviders += 'claude-code' }
    'codex-code' { $extra = 'codex-agent'; $CliProviders += 'codex-code' }
    default {
      Write-Error "Unknown provider '$p'; expected one of: anthropic|openai|google|claude-code|codex-code"
      exit 1
    }
  }
  if ([string]::IsNullOrEmpty($AllExtras)) {
    $AllExtras = $extra
  } else {
    $AllExtras = "$AllExtras,$extra"
  }
}

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
