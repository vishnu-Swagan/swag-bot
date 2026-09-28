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

if ($env:SWAG_REF -and $Spec -like "*git+*") {
  $Spec = "$Spec@$($env:SWAG_REF)"
}

function Invoke-Step([string[]]$Command) {
  if ($DryRun) {
    Write-Output ("would run: " + ($Command -join " "))
    return
  }
  & $Command[0] $Command[1..($Command.Length - 1)]
}

$OriginalPath = $env:PATH
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $LocalBin) {
  $env:PATH = "$LocalBin;$OriginalPath"
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

Write-Output "Model choices (local and free cloud): https://github.com/vishnu-Swagan/swag-bot/blob/main/docs/MODELS.md"

Invoke-Step @("uv", "tool", "install", "--quiet", $Spec)

$BinDir = Join-Path $env:USERPROFILE ".local\bin"
if ($DryRun) {
  Write-Output "would run: uv tool update-shell"
} else {
  $uv = Get-Command uv -ErrorAction SilentlyContinue
  if ($uv) {
    try {
      $discovered = (& $uv.Source tool dir --bin 2>$null)
      if ($discovered) { $BinDir = "$discovered".Trim() }
    } catch {}
    $saved = $env:PATH
    $env:PATH = $OriginalPath
    try { & $uv.Source tool update-shell | Out-Null } catch {}
    $env:PATH = $saved
  }
}
$env:PATH = "$BinDir;$env:PATH"
$already = @($OriginalPath -split ';' | Where-Object { $_ -eq $BinDir })
if ($already.Count -eq 0) {
  Write-Output "swag is not on PATH for new shells yet. Open a new shell, or add it for this one:"
  Write-Output "  `$env:PATH = `"$BinDir;`$env:PATH`""
  Write-Output "uv tool update-shell records that directory when it is missing from PATH."
}

$SwagBin = Join-Path $BinDir "swag.exe"
if (-not (Test-Path $SwagBin)) {
  $SwagBin = Join-Path $BinDir "swag"
}

if ($AssumeYes) {
  Invoke-Step @($SwagBin, "setup", "--auto", "--yes")
} else {
  Invoke-Step @($SwagBin, "setup", "--auto")
}

if ($SwagArgs.Count -gt 0) {
  Invoke-Step (@($SwagBin) + $SwagArgs)
}
