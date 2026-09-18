$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$compose = @('--env-file', '.env', '-f', 'infrastructure/compose.yml', '-f', 'infrastructure/compose.release.yml')

function Fail-Build {
    param([string]$Reason)
    Write-Output ('{"action":"build-worker-image","status":"failed","reason":"' + $Reason + '"}')
    exit 2
}

Push-Location $root
try {
    $commit = & git rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
        Fail-Build 'commit_unavailable'
    }
    $dirty = & git status --porcelain --untracked-files=all
    if ($LASTEXITCODE -ne 0 -or $dirty) {
        Fail-Build 'checkout_not_clean'
    }

    $tag = 'quakestrike-workers:' + $commit
    $images = & docker compose @compose --profile init config --images 2>$null
    if ($LASTEXITCODE -ne 0 -or @($images) -notcontains $tag) {
        Fail-Build 'configured_tag_mismatch'
    }

    $revision = & docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' $tag 2>$null
    if ($LASTEXITCODE -eq 0) {
        if ($revision.Trim() -ne $commit) {
            Fail-Build 'tag_already_exists_with_different_source'
        }
        Write-Output ('{"action":"build-worker-image","status":"reused","commit":"' + $commit + '"}')
        exit 0
    }

    $null = & docker build --quiet --label "org.opencontainers.image.revision=$commit" -t $tag -f workers/Dockerfile workers
    if ($LASTEXITCODE -ne 0) {
        Fail-Build 'image_build_failed'
    }
    Write-Output ('{"action":"build-worker-image","status":"built","commit":"' + $commit + '"}')
} finally {
    Pop-Location
}
