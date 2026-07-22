[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CitizenToken,

    [Parameter(Mandatory = $true)]
    [string]$InvestigatorToken,

    [string]$GatewayUrl = 'http://localhost:8000',
    [string]$InferenceUrl = 'http://localhost:8014',
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
    Fail 'Redis password is unavailable.'
}

$ResolvedRedisPassword = Get-LocalRedisPassword

# ── 1. Set Redis Threshold to 0.99 to force low-confidence PENDING_REVIEW ──
Write-Host "Setting Redis fusion threshold to 0.99 for HITL testing..."
$null = Invoke-Compose @('exec', '-T', 'redis', 'redis-cli', '-a', $script:ResolvedRedisPassword, 'SET', 'fusion:confidence_threshold', '0.99')
Write-Pass "Confidence threshold set to 0.99"

try {
    # ── 2. Create Case via Citizen API ──────────────────────────────────────────
    $citizenHeaders = @{
        Authorization = "Bearer $CitizenToken"
        'Idempotency-Key' = [guid]::NewGuid().ToString()
        'X-Correlation-ID' = [guid]::NewGuid().ToString()
    }
    $caseBody = @{
        title = 'T13b HITL Override Test'
        description = 'Caller claiming to be RBI officer demanding money'
        complaintType = 'UPI_FRAUD'
        suspectPhone = '+919998887776'
        languageCode = 'en'
    } | ConvertTo-Json

    $created = Invoke-RestMethod "$GatewayUrl/api/v1/citizen/report" -Method Post -Headers $citizenHeaders -ContentType 'application/json' -Body $caseBody
    $caseId = $created.data.caseId
    Assert-True ($null -ne $caseId) "Case created with ID $caseId"
    Write-Pass "Created test case $caseId"

    # ── 3. Wait for Orchestrator & verify Pending_AI state ──────────────────────
    $deadline = (Get-Date).AddSeconds(30)
    $prediction = $null
    do {
        try { $prediction = Invoke-RestMethod "$InferenceUrl/inference/cases/$caseId/latest" -ErrorAction Stop } catch { $prediction = $null }
        if (-not $prediction) { Start-Sleep -Seconds 2 }
    } while (-not $prediction -and (Get-Date) -lt $deadline)

    Assert-True ($null -ne $prediction) "Prediction produced for $caseId"
    Assert-True ($prediction.data.status -eq 'PENDING_REVIEW') "Prediction status is PENDING_REVIEW"
    Write-Pass "Prediction is PENDING_REVIEW as expected"

    # Verify Case DB state is Pending_AI
    $dbState = ((Invoke-Compose @('exec', '-T', 'postgres', 'psql', '-U', 'platform_user', '-d', 'platform', '-tAc', "SELECT status FROM investigation.cases WHERE case_id = '$caseId';")) | Out-String).Trim()
    Assert-True ($dbState -eq 'Pending_AI') "Case state in DB is Pending_AI"
    Write-Pass "Case status in PostgreSQL is Pending_AI"

    # ── 4. Validation Check: Short Justification (<10 chars) ───────────────────
    $shortOverrideBody = @{
        decision = 'APPROVE'
        justification = 'short'
        originalVerdictId = $prediction.data.predictionId
    } | ConvertTo-Json
    $investigatorHeaders = @{
        Authorization = "Bearer $InvestigatorToken"
        'Idempotency-Key' = [guid]::NewGuid().ToString()
        'X-Correlation-ID' = [guid]::NewGuid().ToString()
    }

    $failed = $false
    try {
        $null = Invoke-RestMethod "$GatewayUrl/api/v1/investigator/cases/$caseId/override" -Method Post -Headers $investigatorHeaders -ContentType 'application/json' -Body $shortOverrideBody
    } catch {
        $failed = $true
        Write-Pass "Validation correctly rejected justification <10 chars (HTTP 422)"
    }
    Assert-True $failed "Short justification was rejected"

    # ── 5. Perform Valid APPROVE Override ──────────────────────────────────────
    $validOverrideBody = @{
        decision = 'APPROVE'
        justification = 'Reviewed case evidence and confirmed RBI impersonation pattern.'
        originalVerdictId = $prediction.data.predictionId
    } | ConvertTo-Json

    $overrideRes = Invoke-RestMethod "$GatewayUrl/api/v1/investigator/cases/$caseId/override" -Method Post -Headers $investigatorHeaders -ContentType 'application/json' -Body $validOverrideBody
    Assert-True ($overrideRes.status -eq 'success') "Override API returned success"
    Write-Pass "APPROVE override submitted successfully"

    # ── 6. Verify State Transition & DB Persistence ────────────────────────────
    $newDbState = ((Invoke-Compose @('exec', '-T', 'postgres', 'psql', '-U', 'platform_user', '-d', 'platform', '-tAc', "SELECT status FROM investigation.cases WHERE case_id = '$caseId';")) | Out-String).Trim()
    Assert-True ($newDbState -eq 'Action_Taken') "Case state updated to Action_Taken"
    Write-Pass "Case state in DB updated to Action_Taken"

    # Verify OverrideRecord DB table
    $overrideCount = ((Invoke-Compose @('exec', '-T', 'postgres', 'psql', '-U', 'platform_user', '-d', 'platform', '-tAc', "SELECT count(*) FROM inference.override_records WHERE case_id = '$caseId' AND decision = 'APPROVE';")) | Out-String).Trim()
    Assert-True ($overrideCount -eq '1') "OverrideRecord inserted into DB"
    Write-Pass "Immutable OverrideRecord row persisted in PostgreSQL"

    # Verify Outbox Events
    $outboxCount = ((Invoke-Compose @('exec', '-T', 'postgres', 'psql', '-U', 'platform_user', '-d', 'platform', '-tAc', "SELECT count(*) FROM platform.outbox WHERE topic = 'prediction.overridden' AND payload->>'caseId' = '$caseId';")) | Out-String).Trim()
    Assert-True ([int]$outboxCount -ge 1) "Prediction.Overridden event present in outbox"
    Write-Pass "Prediction.Overridden event published to Kafka outbox"

    Write-Pass "T13b HITL Override Verification Completed Successfully!"

} finally {
    # Restore Redis threshold
    $null = Invoke-Compose @('exec', '-T', 'redis', 'redis-cli', '-a', $script:ResolvedRedisPassword, 'DEL', 'fusion:confidence_threshold')
    Write-Pass "Restored default Redis fusion confidence threshold"
}
