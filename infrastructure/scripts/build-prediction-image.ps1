$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path

function Fail-Build {
    param([string]$Reason)
    Write-Output ('{"action":"build-prediction-image","status":"failed","reason":"' + $Reason + '"}')
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

    $baseTag = 'quakestrike-workers:' + $commit
    $tag = 'quakestrike-prediction:' + $commit
    $baseRevision = & docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' $baseTag 2>$null
    if ($LASTEXITCODE -ne 0 -or $baseRevision.Trim() -ne $commit) {
        Fail-Build 'base_image_unavailable'
    }
    $revision = & docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' $tag 2>$null
    if ($LASTEXITCODE -eq 0) {
        if ($revision.Trim() -ne $commit) {
            Fail-Build 'tag_already_exists_with_different_source'
        }
        Write-Output ('{"action":"build-prediction-image","status":"reused","commit":"' + $commit + '"}')
        exit 0
    }

    $null = & docker build --quiet --build-arg "BASE_IMAGE_TAG=$commit" --label "org.opencontainers.image.revision=$commit" -t $tag -f workers/prediction-worker/Dockerfile workers
    if ($LASTEXITCODE -ne 0) {
        Fail-Build 'image_build_failed'
    }
    Write-Output ('{"action":"build-prediction-image","status":"built","commit":"' + $commit + '"}')
} finally {
    Pop-Location
}
