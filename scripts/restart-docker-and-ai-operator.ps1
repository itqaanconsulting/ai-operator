$ErrorActionPreference = "Stop"

$dockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$restartStackScript = Join-Path $PSScriptRoot "restart-ai-operator.ps1"

if (-not (Test-Path -LiteralPath $dockerDesktopPath)) {
    throw "Docker Desktop was not found at: $dockerDesktopPath"
}

Write-Host "Stopping Docker Desktop..." -ForegroundColor Yellow
$dockerProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -in @("Docker Desktop", "com.docker.backend", "com.docker.proxy")
}

if ($dockerProcesses) {
    $dockerProcesses | Stop-Process -Force
    $dockerProcesses | Wait-Process -Timeout 30 -ErrorAction SilentlyContinue
}

Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
Start-Process -FilePath $dockerDesktopPath -WindowStyle Hidden

$deadline = (Get-Date).AddMinutes(3)
$engineReady = $false
do {
    Start-Sleep -Seconds 5
    docker info *> $null
    $engineReady = $LASTEXITCODE -eq 0
} while ((Get-Date) -lt $deadline -and -not $engineReady)

if (-not $engineReady) {
    throw "Docker Desktop did not become ready within 3 minutes. Open Docker Desktop to inspect its status."
}

Write-Host "Docker engine is ready." -ForegroundColor Green
& $restartStackScript
