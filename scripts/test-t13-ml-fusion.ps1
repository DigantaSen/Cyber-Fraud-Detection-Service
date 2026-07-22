[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [switch]$RunFailureScenarios,

    [string]$GatewayUrl = 'http://localhost:8000',
    [string]$InferenceUrl = 'http://localhost:8014',
    [string]$GraphUrl = 'http://localhost:8009',
    [int]$TimeoutSeconds = 45,
    [string]$RedisPassword = $env:REDIS_PASSWORD
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Pass([string]$Message) { Write-Host "PASS: $Message" -ForegroundColor Green }
function Fail([string]$Message) { throw "FAIL: $Message" }
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { Fail $Message }
}
function Invoke-Compose([string[]]$Arguments) {
    # Docker Compose writes ordinary progress messages to stderr. Do not merge
    # that stream into PowerShell's success output: with ErrorActionPreference
    # set to Stop, it becomes a false NativeCommandError despite exit code 0.
    $output = & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "docker compose $($Arguments -join ' ') failed: $($output | Out-String)" }
    return $output
}
function Get-LocalRedisPassword {
    if (-not [string]::IsNullOrWhiteSpace($RedisPassword)) { return $RedisPassword }

    $envFile = Join-Path $PSScriptRoot '..\.env'
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^REDIS_PASSWORD=' } | Select-Object -First 1
        if ($line) { return ($line -replace '^REDIS_PASSWORD=', '').Trim('"', "'") }
    }
    Fail 'Redis password is unavailable. Set REDIS_PASSWORD or pass -RedisPassword.'
}
function Get-DbScalar([string]$Sql) {
    return ((Invoke-Compose @('exec', '-T', 'postgres', 'psql', '-U', 'platform_user', '-d', 'platform', '-tAc', $Sql)) | Out-String).Trim()
}
function Get-RedisValue([string]$Key) {
    return ((Invoke-Compose @('exec', '-T', 'redis', 'redis-cli', '-a', $script:ResolvedRedisPassword, '--raw', 'GET', $Key)) | Out-String).Trim()
}
function New-Headers {
    return @{
        Authorization = "Bearer $Token"
        'Idempotency-Key' = [guid]::NewGuid().ToString()
        'X-Correlation-ID' = [guid]::NewGuid().ToString()
    }
}
function New-TestCase([string]$Title, [string]$Phone) {
    $body = @{
        title = $Title
        description = 'Urgent caller claiming to be RBI demanded an immediate UPI transfer or account freezing.'
        complaintType = 'UPI_FRAUD'
        suspectPhone = $Phone
        languageCode = 'en'
    } | ConvertTo-Json
    try {
        $response = Invoke-RestMethod "$GatewayUrl/api/v1/citizen/report" -Method Post -Headers (New-Headers) -ContentType 'application/json' -Body $body -ErrorAction Stop
    } catch {
        $message = $_.ErrorDetails.Message
        if ($message -match 'token expired|Bad token|INVALID_CREDENTIALS') {
            Fail 'citizen access token is invalid or expired. Refresh $token, then rerun the script.'
        }
        throw
    }
    $caseId = $response.data.caseId
    Assert-True (-not [string]::IsNullOrWhiteSpace($caseId)) "case creation returned no caseId"
    Write-Pass "created case $caseId"
    return $caseId
}
function Wait-Prediction([string]$CaseId) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try { $prediction = Invoke-RestMethod "$InferenceUrl/inference/cases/$CaseId/latest" -ErrorAction Stop } catch { $prediction = $null }
        if (-not $prediction) { Start-Sleep -Seconds 2 }
    } while (-not $prediction -and (Get-Date) -lt $deadline)

    Assert-True ($null -ne $prediction) "no persisted prediction for $CaseId after $TimeoutSeconds seconds"
    Assert-True (-not [string]::IsNullOrWhiteSpace($prediction.data.predictionId)) "prediction response for $CaseId has no predictionId"
    Write-Pass "prediction $($prediction.data.predictionId) persisted for $CaseId"
    return $prediction
}
function Wait-Ready([string]$Url) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest $Url -UseBasicParsing -ErrorAction Stop
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Fail "$Url did not become ready after $TimeoutSeconds seconds"
}
function Assert-CaseProjection([string]$CaseId, $Prediction) {
    $case = Invoke-RestMethod "$GatewayUrl/api/v1/citizen/cases/$CaseId" -Headers @{ Authorization = "Bearer $Token" }
    Assert-True ($case.data.prediction.predictionId -eq $Prediction.data.predictionId) 'Case API prediction does not match Orchestrator prediction'
    Write-Pass 'Case API exposes the persisted fused verdict'
}
function Assert-DatabaseConsistency([string]$CaseId, $Prediction) {
    $sql = "SELECT count(*), count(v.prediction_id), max(jsonb_array_length(v.model_breakdown)), max(v.status) FROM inference.predictions p LEFT JOIN inference.fused_verdicts v USING (prediction_id) WHERE p.case_id = '$CaseId';"
    $parts = (Get-DbScalar $sql).Split('|')
    Assert-True ($parts.Count -eq 4) "unexpected integrity query output: $($parts -join '|')"
    Assert-True ([int]$parts[0] -ge 1) "no prediction row exists for $CaseId"
    Assert-True ([int]$parts[1] -ge 1) "no fused verdict row exists for $CaseId"
    Assert-True ([int]$parts[2] -ge 1) "fused verdict has no model entries"
    Assert-True ($parts[3] -eq $Prediction.data.status) "API status $($Prediction.data.status) differs from DB status $($parts[3])"
    Write-Pass 'prediction and fused-verdict database rows are consistent'

    $predictionId = $Prediction.data.predictionId
    $timelineSql = "SELECT count(*) FROM investigation.case_timeline WHERE case_id = '$CaseId' AND event_type = 'Prediction.PendingReview' AND metadata->>'predictionId' = '$predictionId';"
    $reviewEvents = [int](Get-DbScalar $timelineSql)
    if ($Prediction.data.pendingReview) {
        # prediction.completed is consumed asynchronously by Case Service. Give
        # its projection a bounded time to commit before declaring a failure.
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ($reviewEvents -lt 1 -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 2
            $reviewEvents = [int](Get-DbScalar $timelineSql)
        }
        Assert-True ($reviewEvents -eq 1) "expected one pending-review timeline event, got $reviewEvents"
    } else {
        Assert-True ($reviewEvents -eq 0) "complete prediction unexpectedly has $reviewEvents pending-review timeline events"
    }
    Write-Pass 'review timeline has no duplicate consumer side effect'
}
function Assert-CaseCreatedPayload([string]$CaseId) {
    $sql = "SELECT payload FROM platform.outbox WHERE topic = 'case.created' AND payload->>'caseId' = '$CaseId' ORDER BY created_at DESC LIMIT 1;"
    $event = Get-DbScalar $sql
    foreach ($field in 'title', 'description', 'suspectAccount', 'languageCode') {
        Assert-True ($event -match ('"' + $field + '"')) "Case.Created payload is missing $field"
    }
    Write-Pass 'Case.Created contains the ML complaint payload'
}
function Assert-Logs([string]$CaseId) {
    $logs = (Invoke-Compose @('logs', '--tail', '500', 'inference-orchestrator') | Out-String)
    Assert-True ($logs -match [regex]::Escape("Active models for case $CaseId")) "no model-dispatch log exists for $CaseId"
    Assert-True ($logs -match 'ML results: responding=') 'no ML-results log exists'
    Write-Pass 'Orchestrator logged dispatch and ML results'
}

$graphWasStopped = $false
$oldThreshold = $null
$thresholdChanged = $false
$script:ResolvedRedisPassword = Get-LocalRedisPassword
try {
    $requiredServices = @(
        'case', 'inference-orchestrator', 'graph', 'graph-consumer', 'outbox-publisher',
        'ml-scam-nlp', 'ml-counterfeit-cv', 'ml-graph-analyzer', 'ml-audio-analyzer',
        'kafka', 'postgres', 'redis'
    )
    $runningServices = Invoke-Compose @('ps', '--status', 'running', '--services')
    $missingServices = $requiredServices | Where-Object { $_ -notin $runningServices }
    Assert-True (-not $missingServices) "required services are not running: $($missingServices -join ', ')"
    Write-Pass 'all required services are running'

    foreach ($url in @(
        "$InferenceUrl/health/ready", "$GraphUrl/health/ready",
        'http://localhost:8100/health/ready', 'http://localhost:8101/health/ready',
        'http://localhost:8102/health/ready', 'http://localhost:8103/health/ready'
    )) {
        $health = Invoke-WebRequest $url -UseBasicParsing
        Assert-True ($health.StatusCode -eq 200) "$url returned HTTP $($health.StatusCode)"
    }
    Write-Pass 'Orchestrator, Graph API, and four ML APIs are ready'

    $normalCaseId = New-TestCase 'T13 automated fusion test' '+919876543210'
    Assert-CaseCreatedPayload $normalCaseId
    $normalPrediction = Wait-Prediction $normalCaseId
    Assert-True ($normalPrediction.data.status -eq 'COMPLETE') "expected COMPLETE normal verdict, got $($normalPrediction.data.status)"
    Assert-True (-not $normalPrediction.data.pendingReview) 'normal verdict unexpectedly requires review'
    foreach ($model in 'scam-nlp', 'graph-analyzer') {
        Assert-True ($null -ne ($normalPrediction.data.modelBreakdown | Where-Object { $_.model -eq $model })) "normal verdict is missing $model"
    }
    Assert-True (-not [string]::IsNullOrWhiteSpace($normalPrediction.data.explanation)) 'normal verdict has no fused explanation'
    Write-Pass 'normal fusion verdict contains NLP, graph, and explanation'
    Assert-Logs $normalCaseId
    Assert-CaseProjection $normalCaseId $normalPrediction
    Assert-DatabaseConsistency $normalCaseId $normalPrediction

    $linkage = Invoke-RestMethod "$GraphUrl/api/v1/graph/linkages?entityId=%2B919876543210&hops=2"
    Assert-True ($linkage.status -eq 'success') '2-hop graph linkage request did not succeed'
    Assert-True ($linkage.data.anchor.id -eq '+919876543210') '2-hop graph linkage returned the wrong anchor'
    Write-Pass '2-hop graph linkage endpoint is available'

    if ($RunFailureScenarios) {
        # Set this before invoking Compose so finally restores the model even if
        # Docker emits a benign progress message while stopping it.
        $graphWasStopped = $true
        Invoke-Compose @('stop', 'ml-graph-analyzer') | Out-Null
        $runningGraph = Invoke-Compose @('ps', '--status', 'running', '--services', 'ml-graph-analyzer')
        Assert-True ($runningGraph -notcontains 'ml-graph-analyzer') 'graph model did not stop'
        Write-Pass 'graph model stopped for incomplete-verdict test'

        $incompleteCaseId = New-TestCase 'T13 automated incomplete-model test' '+919876543211'
        $incompletePrediction = Wait-Prediction $incompleteCaseId
        Assert-True ($incompletePrediction.data.status -eq 'INCOMPLETE') "expected INCOMPLETE, got $($incompletePrediction.data.status)"
        Assert-True ([bool]$incompletePrediction.data.pendingReview) 'incomplete verdict was not marked for review'
        $unavailableGraph = $incompletePrediction.data.modelBreakdown | Where-Object { $_.model -eq 'graph-analyzer' -and $_.status -eq 'UNAVAILABLE' }
        Assert-True ($null -ne $unavailableGraph) 'graph model is not marked UNAVAILABLE'
        Write-Pass 'partial verdict is INCOMPLETE and requires review'
        Assert-CaseProjection $incompleteCaseId $incompletePrediction
        Assert-DatabaseConsistency $incompleteCaseId $incompletePrediction

        Invoke-Compose @('start', 'ml-graph-analyzer') | Out-Null
        $graphWasStopped = $false
        $runningGraph = Invoke-Compose @('ps', '--status', 'running', '--services', 'ml-graph-analyzer')
        Assert-True ($runningGraph -contains 'ml-graph-analyzer') 'graph model did not restart'
        Wait-Ready 'http://localhost:8102/health/ready'
        Write-Pass 'graph model restarted'

        $oldThreshold = Get-RedisValue 'fusion:confidence_threshold'
        $thresholdChanged = $true
        Invoke-Compose @('exec', '-T', 'redis', 'redis-cli', '-a', $script:ResolvedRedisPassword, 'SET', 'fusion:confidence_threshold', '0.99') | Out-Null
        $configuredThreshold = Get-RedisValue 'fusion:confidence_threshold'
        Assert-True ($configuredThreshold -eq '0.99') "could not set fusion confidence threshold; Redis returned '$configuredThreshold'"
        Write-Pass 'confidence threshold set to 0.99'

        $reviewCaseId = New-TestCase 'T13 automated low-confidence test' '+919876543212'
        $reviewPrediction = Wait-Prediction $reviewCaseId
        Assert-True ($reviewPrediction.data.status -eq 'PENDING_REVIEW') "expected PENDING_REVIEW, got $($reviewPrediction.data.status)"
        Assert-True ([bool]$reviewPrediction.data.pendingReview) 'low-confidence verdict was not marked for review'
        Assert-CaseProjection $reviewCaseId $reviewPrediction
        Assert-DatabaseConsistency $reviewCaseId $reviewPrediction
        Write-Pass 'low-confidence verdict routes to HITL'
    }

    Write-Host 'PASS: T13 ML fusion verification completed' -ForegroundColor Green
}
finally {
    if ($graphWasStopped) {
        & docker compose start ml-graph-analyzer | Out-Null
        Write-Host 'INFO: restored ml-graph-analyzer' -ForegroundColor Yellow
    }
    if ($thresholdChanged) {
        if ([string]::IsNullOrWhiteSpace($oldThreshold)) {
            & docker compose exec -T redis redis-cli -a $script:ResolvedRedisPassword DEL fusion:confidence_threshold | Out-Null
        } else {
            & docker compose exec -T redis redis-cli -a $script:ResolvedRedisPassword SET fusion:confidence_threshold $oldThreshold | Out-Null
        }
        Write-Host 'INFO: restored fusion confidence threshold' -ForegroundColor Yellow
    }
}
