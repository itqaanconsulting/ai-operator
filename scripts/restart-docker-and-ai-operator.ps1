$ErrorActionPreference = "Stop"

$dockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$restartStackScript = Join-Path $PSScriptRoot "restart-ai-operator.ps1"

function Test-DockerEngine {
    $check = Start-Process -FilePath "docker.exe" -ArgumentList "info" -PassThru -WindowStyle Hidden
    if (-not $check.WaitForExit(5000)) {
        $check.Kill()
        $check.WaitForExit()
        return $false
    }
    return $check.ExitCode -eq 0
}

if (-not (Test-Path -LiteralPath $dockerDesktopPath)) {
    throw "Docker Desktop was not found at: $dockerDesktopPath"
}

Write-Host "Stopping Docker Desktop..." -ForegroundColor Yellow
$dockerProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -in @("Docker Desktop", "com.docker.backend", "com.docker.proxy")
}

if ($dockerProcesses) {
    $dockerProcesses | Stop-Process -Force
    $shutdownDeadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Seconds 1
        $stillRunning = Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -in @("Docker Desktop", "com.docker.backend", "com.docker.proxy")
        }
    } while ($stillRunning -and (Get-Date) -lt $shutdownDeadline)
}

Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
Start-Process -FilePath $dockerDesktopPath
Write-Host "Waiting for the Docker engine (this can take a few minutes)..."

$deadline = (Get-Date).AddMinutes(3)
$engineReady = $false
do {
    Start-Sleep -Seconds 5
    $engineReady = Test-DockerEngine
    if (-not $engineReady) {
        Write-Host "." -NoNewline
    }
} while ((Get-Date) -lt $deadline -and -not $engineReady)

Write-Host ""

if (-not $engineReady) {
    throw "Docker Desktop did not become ready within 3 minutes. Open Docker Desktop to inspect its status."
}

Write-Host "Docker engine is ready." -ForegroundColor Green
& $restartStackScript
