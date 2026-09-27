# One-command install for Swag Bot (Windows PowerShell).
#
# Asks before installing uv. Never installs Ollama or a model by itself.
# Keep $PypiPublished and $GitInstallUrl identical to
# src/swag_bot/onboarding/distribution.py.
$ErrorActionPreference = "Stop"

$PypiPublished = 0
$GitInstallUrl = "git+https://github.com/vishnu-Swagan/swag-bot"

$DryRun = $false
$AssumeYes = $false
$SwagArgs = @()
$SeenDash = $false

foreach ($arg in $args) {
  if (-not $SeenDash -and $arg -eq "--dry-run") {
    $DryRun = $true
    continue
  }
  if (-not $SeenDash -and ($arg -eq "--yes" -or $arg -eq "-y")) {
    $AssumeYes = $true
    continue
  }
  if (-not $SeenDash -and ($arg -eq "--help" -or $arg -eq "-h")) {
    Write-Output "Usage: install.ps1 [--dry-run] [--yes] [--] [swag arguments]"
    Write-Output "Example: ./scripts/install.ps1 --yes -- run `"Write hello.txt`""
    exit 0
  }
  if (-not $SeenDash -and $arg -eq "--") {
    $SeenDash = $true
    continue
  }
  if (-not $SeenDash -and $arg.StartsWith("-")) {
    Write-Error "unknown option: $arg"
    exit 1
  }
  $SeenDash = $true
  $SwagArgs += $arg
}

if ($PypiPublished -eq 1) {
  $Spec = "swag-bot[mcp,models]"
} else {
  $Spec = "swag-bot[mcp,models] @ $GitInstallUrl"
}

function Invoke-Step([string[]]$Command) {
  if ($DryRun) {
    Write-Output ("would run: " + ($Command -join " "))
    return
  }
  & $Command[0] $Command[1..($Command.Length - 1)]
}

$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $LocalBin) {
  $env:PATH = "$LocalBin;$env:PATH"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  if ($DryRun) {
    Write-Output "would run: powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
  } else {
    $installUv = $AssumeYes
    if (-not $installUv) {
      $reply = Read-Host "Install uv from https://astral.sh/uv/install.ps1 ? [y/N]"
      $installUv = $reply -match "^(y|yes)$"
    }
    if (-not $installUv) {
      Write-Error "uv is required. Install it from https://docs.astral.sh/uv/, then re-run this script."
      exit 2
    }
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if (Test-Path $LocalBin) {
      $env:PATH = "$LocalBin;$env:PATH"
    }
  }
}

Invoke-Step @("uv", "tool", "install", $Spec)

if ($AssumeYes) {
  Invoke-Step @("swag", "setup", "--auto", "--yes")
} else {
  Invoke-Step @("swag", "setup", "--auto")
}

if ($SwagArgs.Count -gt 0) {
  Invoke-Step (@("swag") + $SwagArgs)
}
