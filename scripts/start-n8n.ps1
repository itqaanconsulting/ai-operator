$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectDirectory ".env.n8n"
$composeFile = Join-Path $projectDirectory "compose.n8n.yml"
$applicationEnvironmentFile = Join-Path $projectDirectory ".env"

if (-not (Test-Path -LiteralPath $applicationEnvironmentFile)) {
    throw "Missing .env. Configure the AI Operator before starting the Docker stack."
}

if (-not (Test-Path -LiteralPath $environmentFile)) {
    $secretBytes = New-Object byte[] 48
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomGenerator.GetBytes($secretBytes)
    }
    finally {
        $randomGenerator.Dispose()
    }
    $encryptionKey = [Convert]::ToBase64String($secretBytes)
    "N8N_ENCRYPTION_KEY=$encryptionKey" | Set-Content -LiteralPath $environmentFile -Encoding utf8
    Write-Host "Created local n8n encryption key in .env.n8n"
}

if (-not (Select-String -LiteralPath $environmentFile -Pattern '^AI_OPERATOR_WEBHOOK_SECRET=' -Quiet)) {
    $secretBytes = New-Object byte[] 48
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $randomGenerator.GetBytes($secretBytes) }
    finally { $randomGenerator.Dispose() }
    $webhookSecret = [Convert]::ToBase64String($secretBytes)
    "AI_OPERATOR_WEBHOOK_SECRET=$webhookSecret" | Add-Content -LiteralPath $environmentFile -Encoding utf8
    Write-Host "Created local AI Operator webhook secret in .env.n8n"
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if ($process.CommandLine -like "*uvicorn*main:app*") {
        Stop-Process -Id $listener.OwningProcess -Force
        Write-Host "Stopped the host AI Operator so Docker can use port 8000"
    }
    elseif ($process.Name -eq "com.docker.backend.exe") {
        try {
            $existingApi = Invoke-RestMethod "http://127.0.0.1:8000/openapi.json" -TimeoutSec 5
        }
        catch {
            throw "Docker owns port 8000, but the service is not a reachable AI Operator API."
        }
        if ($existingApi.info.title -ne "AI Commitment Operator") {
            throw "Docker port 8000 belongs to another application; refusing to replace it."
        }
        Write-Host "Existing Docker AI Operator detected on port 8000"
    }
    else {
        throw "Port 8000 belongs to an unrelated process; refusing to stop it."
    }
}

docker compose --env-file $environmentFile -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose could not start n8n."
}

Write-Host "AI Operator is starting at http://127.0.0.1:8000"
Write-Host "n8n is starting at http://127.0.0.1:5678"
