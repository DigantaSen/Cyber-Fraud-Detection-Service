# T13 Manual Test Plan — Multi-Source ML Fusion

Run every command below from the repository root in PowerShell. Each assertion throws on failure; a successful command prints `PASS`.

## Automated runner

The runner executes the service, event-payload, normal fusion, graph-linkage,
case-projection, database, and timeline checks in one command. It creates its
own test cases and fails at the first broken assertion:

```powershell
./scripts/test-t13-ml-fusion.ps1 -Token $token
```

The failure-mode checks intentionally stop `ml-graph-analyzer` and temporarily
set the Redis confidence threshold. Run them only in a local test environment;
the script restores both settings in `finally`, including on failure:

```powershell
./scripts/test-t13-ml-fusion.ps1 -Token $token -RunFailureScenarios
```

The runner reads `REDIS_PASSWORD` from `.env`. If your password is supplied
outside that file, pass it explicitly as `-RedisPassword '<password>'`.

The evidence checks remain manual because they require a real image or audio
file upload through the evidence workflow.

## 0. Build and service readiness

```powershell
docker compose up -d --build case inference-orchestrator graph graph-consumer outbox-publisher
$requiredServices = @(
  'case', 'inference-orchestrator', 'graph', 'graph-consumer', 'outbox-publisher',
  'ml-scam-nlp', 'ml-counterfeit-cv', 'ml-graph-analyzer', 'ml-audio-analyzer',
  'kafka', 'postgres', 'redis'
)
$runningServices = docker compose ps --status running --services
$missingServices = $requiredServices | Where-Object { $_ -notin $runningServices }
if ($missingServices) { throw "FAIL: required services are not running: $($missingServices -join ', ')" }
"PASS: all $($requiredServices.Count) required services are running"
```

Pass criteria: `case`, `inference-orchestrator`, `graph`, `outbox-publisher`, four `ml-*` services, Kafka, PostgreSQL, and Redis show `running` or `healthy`. The outbox publisher is required: it forwards `case.created` records from PostgreSQL to Kafka. If the build takes longer than one minute, rerun the first command; Docker reuses completed layers.

```powershell
$healthUrls = @(
  'http://localhost:8014/health/ready',
  'http://localhost:8009/health/ready',
  'http://localhost:8100/health/ready',
  'http://localhost:8101/health/ready',
  'http://localhost:8102/health/ready',
  'http://localhost:8103/health/ready'
)
foreach ($url in $healthUrls) {
  $response = Invoke-WebRequest $url -UseBasicParsing
  if ($response.StatusCode -ne 200) { throw "FAIL: $url returned $($response.StatusCode)" }
  "PASS: $url is ready"
}
```

This proves the Orchestrator, Graph API, and all four ML APIs are reachable before testing event flow.

## 1. Create a citizen case and capture its ID

Log in through the citizen portal. In DevTools → Application → Local Storage, copy the `accessToken` value. Then run:

```powershell
$token = '<paste-citizen-access-token>'
$headers = @{ Authorization = "Bearer $token"; 'Idempotency-Key' = [guid]::NewGuid().ToString(); 'X-Correlation-ID' = [guid]::NewGuid().ToString() }
$body = @{
  title = 'T13 UPI fusion test'
  description = 'Urgent: a caller claiming to be RBI told me to send money by UPI immediately or my account will be frozen.'
  complaintType = 'UPI_FRAUD'
  suspectPhone = '+919876543210'
  languageCode = 'en'
} | ConvertTo-Json
$created = Invoke-RestMethod http://localhost:8000/api/v1/citizen/report -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$caseId = $created.data.caseId
if (-not $caseId) { throw "FAIL: caseId missing: $($created | ConvertTo-Json -Depth 10)" }
"PASS: created case $caseId"
```

If Kong is not exposed on port 8000 in your setup, submit this same report in the citizen UI and copy `caseId` from its network response. Keep it in the current PowerShell session:

```powershell
$caseId = '<case-id-from-the-UI>'
```

## 2. Verify Case.Created has the full ML payload

```powershell
$sql = "SELECT payload FROM platform.outbox WHERE topic = 'case.created' AND payload->>'caseId' = '$caseId' ORDER BY created_at DESC LIMIT 1;"
$event = docker compose exec -T postgres psql -U platform_user -d platform -tAc $sql
if ($event -notmatch '"title"' -or $event -notmatch '"description"' -or $event -notmatch '"suspectAccount"' -or $event -notmatch '"languageCode"') { throw "FAIL: incomplete Case.Created payload: $event" }
"PASS: Case.Created contains title, description, suspectAccount, and languageCode"
```

This proves the Orchestrator has the complaint and anchor data required to invoke NLP and graph analysis.

## 3. Verify fusion persisted and published

Wait up to 30 seconds for Kafka processing, then run:

```powershell
$deadline = (Get-Date).AddSeconds(30)
do {
  try { $prediction = Invoke-RestMethod "http://localhost:8014/inference/cases/$caseId/latest" -ErrorAction Stop } catch { $prediction = $null }
  if (-not $prediction) { Start-Sleep -Seconds 2 }
} while (-not $prediction -and (Get-Date) -lt $deadline)

if (-not $prediction.data.predictionId) { throw "FAIL: no persisted prediction for $caseId after 30 seconds" }
if (@($prediction.data.modelBreakdown).Count -lt 2) { throw "FAIL: expected NLP and graph results: $($prediction | ConvertTo-Json -Depth 10)" }
foreach ($model in 'scam-nlp', 'graph-analyzer') {
  if (-not ($prediction.data.modelBreakdown | Where-Object { $_.model -eq $model })) { throw "FAIL: expected model '$model' is absent" }
}
if (-not $prediction.data.explanation) { throw 'FAIL: fused explanation is missing' }
"PASS: prediction $($prediction.data.predictionId) persisted with model explanations"
$prediction.data | ConvertTo-Json -Depth 10
```

Expected output: `status` is normally `COMPLETE`; `modelBreakdown` includes `scam-nlp` and `graph-analyzer`; `fusedScore`, `confidence`, `riskTier`, `signals`, and `explanation` are populated.

After the polling command above prints `PASS`, check the actual fan-out for
the same case. Do this before rebuilding/recreating `inference-orchestrator`:
Docker container logs are reset on recreation, and Kafka does not replay an
event that this consumer group has already acknowledged.

```powershell
$logs = docker compose logs --tail 500 inference-orchestrator | Out-String
$started = "Active models for case $caseId"
$finished = 'ML results: responding='

if ($logs -notmatch [regex]::Escape($started)) {
  throw "FAIL: no model-dispatch log for case $caseId. Create a fresh report if the service was rebuilt."
}
if ($logs -notmatch $finished) {
  throw "FAIL: no ML-results log for case $caseId."
}
"PASS: Orchestrator dispatched models and received ML results for $caseId"
```

## 4. Verify Case Service exposes the stored verdict

```powershell
$case = Invoke-RestMethod "http://localhost:8000/api/v1/citizen/cases/$caseId" -Headers @{ Authorization = "Bearer $token" }
if (-not $case.data.prediction.predictionId) { throw "FAIL: Case API did not return a persisted prediction: $($case | ConvertTo-Json -Depth 10)" }
if ($case.data.prediction.predictionId -ne $prediction.data.predictionId) { throw 'FAIL: Case API returned a different prediction than the Orchestrator' }
"PASS: Case API returns fused verdict $($case.data.prediction.predictionId)"
```

This proves the citizen and investigator UIs can render the persisted fusion result rather than the former stub.

## 5. Incomplete-model → Pending_AI test

```powershell
docker compose stop ml-graph-analyzer
$runningGraphModel = docker compose ps --status running --services ml-graph-analyzer
if ($runningGraphModel -contains 'ml-graph-analyzer') { throw 'FAIL: graph model did not stop' }
'PASS: graph model stopped'
```

Create a fresh case *after* stopping the model, then poll for its new verdict.
Do not reuse `$prediction` from the complete-case test: persisted verdicts are
immutable and stopping a model does not alter them.

```powershell
$incompleteHeaders = @{
  Authorization = "Bearer $token"
  'Idempotency-Key' = [guid]::NewGuid().ToString()
  'X-Correlation-ID' = [guid]::NewGuid().ToString()
}
$incompleteBody = @{
  title = 'T13 incomplete-model test'
  description = 'Urgent caller claiming to be RBI demanded an immediate UPI transfer.'
  complaintType = 'UPI_FRAUD'
  suspectPhone = '+919876543211'
  languageCode = 'en'
} | ConvertTo-Json
$created = Invoke-RestMethod 'http://localhost:8000/api/v1/citizen/report' -Method Post -Headers $incompleteHeaders -ContentType 'application/json' -Body $incompleteBody
$caseId = $created.data.caseId
if (-not $caseId) { throw 'FAIL: incomplete-flow case was not created' }

$deadline = (Get-Date).AddSeconds(30)
do {
  try { $prediction = Invoke-RestMethod "http://localhost:8014/inference/cases/$caseId/latest" -ErrorAction Stop } catch { $prediction = $null }
  if (-not $prediction) { Start-Sleep -Seconds 2 }
} while (-not $prediction -and (Get-Date) -lt $deadline)
if (-not $prediction) { throw "FAIL: no prediction for incomplete-flow case $caseId" }
"PASS: incomplete-flow case $caseId produced prediction $($prediction.data.predictionId)"
```

Verify the safe partial result:

```powershell
if ($prediction.data.status -ne 'INCOMPLETE') { throw "FAIL: expected INCOMPLETE, got $($prediction.data.status)" }
if (-not $prediction.data.pendingReview) { throw 'FAIL: incomplete verdict was not marked for review' }
$unavailable = $prediction.data.modelBreakdown | Where-Object { $_.model -eq 'graph-analyzer' -and $_.status -eq 'UNAVAILABLE' }
if (-not $unavailable) { throw 'FAIL: graph model is not marked UNAVAILABLE' }
"PASS: partial verdict is INCOMPLETE and requires review"
```

Verify the Case projection and restore the model:

```powershell
$sql = "SELECT status FROM investigation.cases WHERE case_id = '$caseId';"
$state = (docker compose exec -T postgres psql -U platform_user -d platform -tAc $sql).Trim()
if ($state -ne 'Pending_AI') { throw "FAIL: expected Pending_AI, got $state" }
'PASS: incomplete prediction routed the case to Pending_AI'
docker compose start ml-graph-analyzer
$runningGraphModel = docker compose ps --status running --services ml-graph-analyzer
if ($runningGraphModel -notcontains 'ml-graph-analyzer') { throw 'FAIL: graph model did not restart' }
'PASS: graph model restarted'
```

## 6. Low-confidence → Pending_AI HITL test

Save and then raise the threshold:

```powershell
$redisPassword = ((Get-Content .env | Where-Object { $_ -match '^REDIS_PASSWORD=' } | Select-Object -First 1) -replace '^REDIS_PASSWORD=', '')
$oldThreshold = docker compose exec -T redis redis-cli -a $redisPassword GET fusion:confidence_threshold
$thresholdReply = docker compose exec -T redis redis-cli -a $redisPassword SET fusion:confidence_threshold 0.99
if ($thresholdReply.Trim() -ne 'OK') { throw "FAIL: could not set threshold: $thresholdReply" }
'PASS: threshold set to 0.99'
```

Create and poll a fresh case. This block is deliberately self-contained so it
cannot reuse the complete or incomplete test's `$body`, `$caseId`, or
`$prediction` values.

```powershell
$reviewHeaders = @{
  Authorization = "Bearer $token"
  'Idempotency-Key' = [guid]::NewGuid().ToString()
  'X-Correlation-ID' = [guid]::NewGuid().ToString()
}
$reviewBody = @{
  title = 'T13 low-confidence review test'
  description = 'Urgent caller claiming to be RBI demanded an immediate UPI transfer.'
  complaintType = 'UPI_FRAUD'
  suspectPhone = '+919876543212'
  languageCode = 'en'
} | ConvertTo-Json
$created = Invoke-RestMethod 'http://localhost:8000/api/v1/citizen/report' -Method Post -Headers $reviewHeaders -ContentType 'application/json' -Body $reviewBody
$caseId = $created.data.caseId
if (-not $caseId) { throw 'FAIL: low-confidence case was not created' }

$deadline = (Get-Date).AddSeconds(30)
do {
  try { $prediction = Invoke-RestMethod "http://localhost:8014/inference/cases/$caseId/latest" -ErrorAction Stop } catch { $prediction = $null }
  if (-not $prediction) { Start-Sleep -Seconds 2 }
} while (-not $prediction -and (Get-Date) -lt $deadline)
if (-not $prediction) { throw "FAIL: no prediction for low-confidence case $caseId" }
"PASS: low-confidence case $caseId produced prediction $($prediction.data.predictionId)"
```

Then run:

```powershell
if ($prediction.data.status -ne 'PENDING_REVIEW') { throw "FAIL: expected PENDING_REVIEW, got $($prediction.data.status)" }
if (-not $prediction.data.pendingReview) { throw 'FAIL: low-confidence verdict was not marked for review' }
$state = (docker compose exec -T postgres psql -U platform_user -d platform -tAc "SELECT status FROM investigation.cases WHERE case_id = '$caseId';").Trim()
if ($state -ne 'Pending_AI') { throw "FAIL: expected Pending_AI, got $state" }
'PASS: low confidence routed the case to HITL'
```

Always restore Redis afterwards:

```powershell
if ([string]::IsNullOrWhiteSpace($oldThreshold)) { docker compose exec -T redis redis-cli -a $redisPassword DEL fusion:confidence_threshold } else { docker compose exec -T redis redis-cli -a $redisPassword SET fusion:confidence_threshold $oldThreshold }
'PASS: fusion threshold restored'
```

## 7. Database integrity and idempotency checks

```powershell
$sql = "SELECT count(*), count(v.prediction_id), max(jsonb_array_length(v.model_breakdown)), max(v.status) FROM inference.predictions p LEFT JOIN inference.fused_verdicts v USING (prediction_id) WHERE p.case_id = '$caseId';"
$integrity = (docker compose exec -T postgres psql -U platform_user -d platform -tAc $sql).Trim().Split('|')
if ($integrity.Count -ne 4) { throw "FAIL: unexpected integrity query output: $($integrity -join '|')" }
if ([int]$integrity[0] -lt 1) { throw "FAIL: no prediction row exists for $caseId" }
if ([int]$integrity[1] -lt 1) { throw "FAIL: no fused verdict row exists for $caseId" }
if ([int]$integrity[2] -lt 1) { throw "FAIL: fused verdict has no model breakdown" }
if ($integrity[3] -ne $prediction.data.status) { throw "FAIL: API status $($prediction.data.status) differs from DB status $($integrity[3])" }
"PASS: database has $($integrity[0]) prediction(s), $($integrity[1]) verdict(s), and $($integrity[2]) model entries"
```

For an `INCOMPLETE` or `PENDING_REVIEW` case, also ensure the consumer has
created exactly one review timeline event for its latest verdict:

```powershell
$predictionId = $prediction.data.predictionId
$sql = "SELECT count(*) FROM investigation.case_timeline WHERE case_id = '$caseId' AND event_type = 'Prediction.PendingReview' AND metadata->>'predictionId' = '$predictionId';"
$reviewEvents = (docker compose exec -T postgres psql -U platform_user -d platform -tAc $sql).Trim()
if ($prediction.data.pendingReview -and $reviewEvents -ne '1') { throw "FAIL: expected one pending-review timeline event, got $reviewEvents" }
if (-not $prediction.data.pendingReview -and $reviewEvents -ne '0') { throw "FAIL: complete prediction unexpectedly has $reviewEvents review events" }
'PASS: prediction persistence and review timeline are internally consistent'
```

Do not replay Kafka messages in a shared environment. The timeline assertion above
is the safe check for duplicate-consumer side effects.

## 8. Evidence-dependent model checks

Use the citizen UI to upload and confirm a PNG/JPEG against a
`COUNTERFEIT_CURRENCY` case, or a WAV/MP3/M4A/OGG file for audio. Wait for the
Evidence Service to mark it `VERIFIED`, then poll the case's latest prediction
with the Step 3 polling command. Set `$expectedModel` to the evidence type and
run:

```powershell
$expectedModel = 'counterfeit-cv' # use 'audio-analyzer' for audio evidence
if (-not $prediction.data.predictionId) { throw 'FAIL: poll the evidence-triggered prediction before this check' }
$evidenceModel = $prediction.data.modelBreakdown | Where-Object { $_.model -eq $expectedModel }
if (-not $evidenceModel) { throw "FAIL: $expectedModel was not invoked" }
if ($evidenceModel.status -eq 'UNAVAILABLE') {
  if ($prediction.data.status -ne 'INCOMPLETE' -or -not $prediction.data.pendingReview) {
    throw "FAIL: unavailable $expectedModel did not produce a safe incomplete review verdict"
  }
  "PASS: unavailable $expectedModel safely produced INCOMPLETE + pending review"
} elseif (-not $evidenceModel.explanation) {
  throw "FAIL: $expectedModel returned no explanation"
} else {
  "PASS: $expectedModel contributed score $($evidenceModel.score) with an explanation"
}

$logs = docker compose logs --tail 200 inference-orchestrator | Out-String
if ($logs -match 'Could not fetch evidence|exceeds the ML size limit') { 'INFO: evidence was safely rejected or unavailable' } else { 'PASS: evidence retrieval completed without safety rejection' }
```

Pass criteria: valid evidence produces `counterfeit-cv` or `audio-analyzer` in
`modelBreakdown`; missing, wrong-MIME, or oversized evidence produces that model
with `status: UNAVAILABLE` and a safe `INCOMPLETE` verdict.
