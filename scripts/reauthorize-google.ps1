$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectDirectory "venv\Scripts\python.exe"
$calendarCheck = Join-Path $projectDirectory "calendar_auth.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "The project virtual environment was not found. Complete the README installation first."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectDirectory "credentials.json"))) {
    throw "credentials.json was not found in the project directory."
}

Write-Host "A Google authorization page will open in your browser."
Write-Host "Approve both Gmail and Google Calendar access, then return to this window."
Push-Location $projectDirectory
try {
    & $python $calendarCheck
    if ($LASTEXITCODE -ne 0) {
        throw "Google authorization did not complete successfully."
    }
}
finally {
    Pop-Location
}
Write-Host "Google authorization is ready. You can retry the failed dashboard action."
