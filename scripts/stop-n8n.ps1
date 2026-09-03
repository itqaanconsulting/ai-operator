$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectDirectory ".env.n8n"
$composeFile = Join-Path $projectDirectory "compose.n8n.yml"

docker compose --env-file $environmentFile -f $composeFile down
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose could not stop n8n."
}
