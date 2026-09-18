$ErrorActionPreference = 'Stop'
$compose = @('--env-file', '.env', '-f', 'infrastructure/compose.yml', '-f', 'infrastructure/compose.release.yml')
. "$PSScriptRoot/consumer-health.ps1"

Assert-ConsumersHealthy -Action 'poll-now' -Compose $compose

& docker compose @compose exec -T dispatcher quakestrike poll-now
exit $LASTEXITCODE
