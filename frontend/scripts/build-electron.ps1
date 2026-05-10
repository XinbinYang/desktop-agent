param(
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Split-Path -Parent $ScriptDir

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    if (![string]::IsNullOrWhiteSpace($env:DESKTOP_AGENT_RELEASE_DIR)) {
        $OutputDir = $env:DESKTOP_AGENT_RELEASE_DIR
    }
    else {
        $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $OutputDir = Join-Path "release-packaged" $Stamp
    }
}

Push-Location $FrontendDir
try {
    Write-Host "[build-electron] Output: $OutputDir"
    & npx electron-builder "--config.directories.output=$OutputDir"
    $BuilderExitCode = $LASTEXITCODE

    if ($BuilderExitCode -ne 0) {
        exit $BuilderExitCode
    }

    $ResolvedOutputDir = Resolve-Path -LiteralPath $OutputDir
    $LatestFile = Join-Path $FrontendDir "release-packaged\latest.txt"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LatestFile) | Out-Null
    Set-Content -LiteralPath $LatestFile -Value $ResolvedOutputDir.Path -Encoding UTF8
    Write-Host "[build-electron] Latest output written to $LatestFile"
}
finally {
    Pop-Location
}
