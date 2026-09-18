function Get-ConsumerHealth {
    param([string[]]$Compose)
    foreach ($service in @('dispatcher', 'data-ingestor')) {
        $containerIds = & docker compose @Compose ps -q $service
        $dockerExit = $LASTEXITCODE
        $containerId = @($containerIds) | Select-Object -First 1
        if ($dockerExit -ne 0 -or -not $containerId) {
            return 'consumer_unavailable'
        }
        $health = & docker inspect --format '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' $containerId
        if ($LASTEXITCODE -ne 0 -or $health.Trim() -ne 'true|healthy') {
            return 'consumer_unhealthy'
        }
    }
    return 'healthy'
}

function Assert-ConsumersHealthy {
    param([string]$Action, [string[]]$Compose)
    $health = Get-ConsumerHealth -Compose $Compose
    if ($health -ne 'healthy') {
        Write-Output ('{"action":"' + $Action + '","status":"not_ready","reason":"' + $health + '"}')
        exit 2
    }
}
