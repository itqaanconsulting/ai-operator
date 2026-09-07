$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectDirectory ".env.n8n"
$composeFile = Join-Path $projectDirectory "compose.n8n.yml"

function Test-DockerEngine {
    try {
        $check = Start-Process -FilePath "docker.exe" -ArgumentList "info" -PassThru -WindowStyle Hidden
        if (-not $check.WaitForExit(5000)) {
            $check.Kill()
            $check.WaitForExit()
            return $false
        }
        return $check.ExitCode -eq 0
    }
    catch {
        return $false
    }
}

if (Test-DockerEngine) {
    Write-Host "Stopping AI Operator and n8n gracefully..." -ForegroundColor Cyan
    & docker compose --env-file $environmentFile -f $composeFile down
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose could not stop the AI Operator stack. Docker Desktop was left running."
    }
    Write-Host "Containers stopped. Persistent database and n8n data were preserved." -ForegroundColor Green
}
else {
    Write-Host "Docker engine is already unavailable; skipping the container stop." -ForegroundColor Yellow
}

$desktopProcesses = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $desktopProcesses) {
    Write-Host "Docker Desktop is already closed." -ForegroundColor Green
    exit 0
}

Write-Host "Closing Docker Desktop gracefully..." -ForegroundColor Cyan
$stop = Start-Process -FilePath "docker.exe" -ArgumentList "desktop", "stop" -PassThru -WindowStyle Hidden
if (-not $stop.WaitForExit(60000)) {
    $stop.Kill()
    $stop.WaitForExit()
    throw "Docker Desktop did not close within 60 seconds. Use the tray menu and choose Quit Docker Desktop."
}
if ($stop.ExitCode -ne 0) {
    throw "Docker Desktop could not be closed through its CLI. Use the tray menu and choose Quit Docker Desktop."
}

Write-Host "AI Operator, n8n, and Docker Desktop are safely stopped." -ForegroundColor Green
