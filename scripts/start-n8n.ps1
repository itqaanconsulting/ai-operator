$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectDirectory ".env.n8n"
$composeFile = Join-Path $projectDirectory "compose.n8n.yml"

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

docker compose --env-file $environmentFile -f $composeFile up -d
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose could not start n8n."
}

Write-Host "n8n is starting at http://127.0.0.1:5678"
