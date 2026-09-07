$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$stopScript = Join-Path $PSScriptRoot "stop-n8n.ps1"
$startScript = Join-Path $PSScriptRoot "start-n8n.ps1"
$dockerRecoveryScript = Join-Path $PSScriptRoot "restart-docker-and-ai-operator.ps1"

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

if (-not (Test-DockerEngine)) {
    Write-Host "Docker engine is unavailable. Starting full Docker recovery..." -ForegroundColor Yellow
    & $dockerRecoveryScript
    exit
}

Push-Location $projectDirectory
try {
    Write-Host "Restarting the AI Operator stack..." -ForegroundColor Cyan
    & $stopScript
    & $startScript

    $deadline = (Get-Date).AddSeconds(60)
    $apiReady = $false
    $n8nReady = $false

    do {
        try {
            $schema = Invoke-RestMethod "http://127.0.0.1:8000/openapi.json" -TimeoutSec 3
            $apiReady = $schema.info.title -eq "AI Commitment Operator"
        }
        catch { $apiReady = $false }

        try {
            $health = Invoke-WebRequest "http://127.0.0.1:5678/healthz" -UseBasicParsing -TimeoutSec 3
            $n8nReady = $health.StatusCode -eq 200
        }
        catch { $n8nReady = $false }

        if (-not ($apiReady -and $n8nReady)) {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline -and -not ($apiReady -and $n8nReady))

    if (-not $apiReady) { throw "AI Operator did not become ready on port 8000 within 60 seconds." }
    if (-not $n8nReady) { throw "n8n did not become ready on port 5678 within 60 seconds." }

    Write-Host "" 
    Write-Host "AI Operator and n8n are ready." -ForegroundColor Green
    Write-Host "Dashboard: http://127.0.0.1:8000/dashboard"
    Write-Host "n8n:       http://127.0.0.1:5678"
}
finally {
    Pop-Location
}
