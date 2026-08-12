[CmdletBinding()]
param(
    [switch] $IncludeLiveTests,

    [ValidateRange(1, 65535)]
    [int] $SecondPort = 0,

    [switch] $SkipSync,

    [switch] $SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($SecondPort -and -not $IncludeLiveTests) {
    throw "-SecondPort requires -IncludeLiveTests."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required but was not found on PATH. Install uv and try again."
}

function Invoke-Uv {
    param(
        [Parameter(Mandatory, Position = 0)]
        [string[]] $Arguments
    )

    Write-Host ("+ uv " + ($Arguments -join " "))
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv exited with code $LASTEXITCODE."
    }
}

$projectRoot = $PSScriptRoot
$previousSecondPort = $env:HOUDINI_CODEMODE_SECOND_PORT

Push-Location -LiteralPath $projectRoot
try {
    if (-not $SkipSync) {
        # Keep the development environment aligned with the committed lockfile.
        Invoke-Uv @("sync", "--frozen")
    }

    if (-not $SkipTests) {
        # Live tests are opt-in because they can mutate disposable scene content.
        Invoke-Uv @("run", "--frozen", "pytest", "-m", "not live")

        if ($IncludeLiveTests) {
            if ($SecondPort) {
                $env:HOUDINI_CODEMODE_SECOND_PORT = [string] $SecondPort
            }
            Invoke-Uv @("run", "--frozen", "pytest", "-m", "live")
        }
    }

    # Ignore local uv source overrides when validating the distributable package.
    Invoke-Uv @("build", "--no-sources")
}
finally {
    if ($null -eq $previousSecondPort) {
        Remove-Item Env:HOUDINI_CODEMODE_SECOND_PORT -ErrorAction SilentlyContinue
    }
    else {
        $env:HOUDINI_CODEMODE_SECOND_PORT = $previousSecondPort
    }
    Pop-Location
}
