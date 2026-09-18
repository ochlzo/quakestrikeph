$ErrorActionPreference = 'Stop'
$compose = @('--env-file', '.env', '-f', 'infrastructure/compose.yml', '-f', 'infrastructure/compose.release.yml')
. "$PSScriptRoot/consumer-health.ps1"

Assert-ConsumersHealthy -Action 'enable-beat' -Compose $compose

& docker compose @compose --profile beat up -d --wait beat
if ($LASTEXITCODE -ne 0) {
    & docker compose @compose --profile beat stop beat 2>$null | Out-Null
    Write-Output ('{"action":"enable-beat","status":"failed"}')
    exit 2
}
$beatId = (& docker compose @compose ps -q beat | Select-Object -First 1)
if ($LASTEXITCODE -ne 0 -or -not $beatId) {
    & docker compose @compose --profile beat stop beat 2>$null | Out-Null
    Write-Output ('{"action":"enable-beat","status":"failed","reason":"beat_unavailable"}')
    exit 2
}
$beatHealth = & docker inspect --format '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' $beatId
if ($LASTEXITCODE -ne 0 -or $beatHealth.Trim() -ne 'true|healthy') {
    & docker compose @compose --profile beat stop beat 2>$null | Out-Null
    Write-Output ('{"action":"enable-beat","status":"failed","reason":"beat_unhealthy"}')
    exit 2
}
$consumerHealth = Get-ConsumerHealth -Compose $compose
if ($consumerHealth -ne 'healthy') {
    & docker compose @compose --profile beat stop beat 2>$null | Out-Null
    Write-Output ('{"action":"enable-beat","status":"not_ready","reason":"' + $consumerHealth + '"}')
    exit 2
}
Write-Output ('{"action":"enable-beat","status":"enabled"}')
