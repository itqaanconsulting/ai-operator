$ErrorActionPreference = "Stop"

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdministrator) {
    Write-Host "Administrator access is required to restart the Docker service." -ForegroundColor Yellow
    Write-Host "Accept the Windows permission prompt to continue."
    $elevatedArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $elevatedArguments
    exit
}

$dockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$restartStackScript = Join-Path $PSScriptRoot "restart-ai-operator.ps1"

Write-Host "Docker recovery started." -ForegroundColor Cyan
Write-Host "Administrator access confirmed."

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
$dockerService = Get-Service -Name "com.docker.service" -ErrorAction SilentlyContinue
if ($dockerService -and $dockerService.Status -ne "Stopped") {
    Write-Host "Stopping Docker system service..."
    Stop-Service -Name "com.docker.service" -Force
}

$dockerProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -in @("Docker Desktop", "com.docker.backend", "com.docker.proxy", "docker")
}

if ($dockerProcesses) {
    foreach ($dockerProcess in $dockerProcesses) {
        Write-Host "Stopping $($dockerProcess.ProcessName) ($($dockerProcess.Id))..."
        Stop-Process -Id $dockerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $shutdownDeadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Seconds 1
        $stillRunning = Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -in @("Docker Desktop", "com.docker.backend", "com.docker.proxy", "docker")
        }
    } while ($stillRunning -and (Get-Date) -lt $shutdownDeadline)
}

if ($stillRunning) {
    Write-Host "Some Docker processes restarted automatically; continuing with Docker Desktop startup." -ForegroundColor Yellow
}

if ($dockerService) {
    Write-Host "Starting Docker system service..."
    Start-Service -Name "com.docker.service"
    $dockerService.WaitForStatus("Running", (New-TimeSpan -Seconds 30))
    Write-Host "Docker system service is running."
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
