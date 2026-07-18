# =============================================================
# T7 Audit Service — Smoke Test Script
# Usage: .\backend\audit\smoke_test.ps1
# Prereqs: platform stack running (docker compose up -d)
# =============================================================

$BASE = "http://localhost:8007"
$script:PASS = 0
$script:FAIL = 0

function Pass($msg) { Write-Host "  [PASS] $msg" -ForegroundColor Green;  $script:PASS++ }
function Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red;    $script:FAIL++ }
function Info($msg) { Write-Host "  [INFO] $msg" -ForegroundColor Cyan }

# Helper: run a SQL statement via docker exec (no inner-quote hell)
function Invoke-SQL($sql) {
    $bytes  = [System.Text.Encoding]::UTF8.GetBytes($sql)
    $b64    = [Convert]::ToBase64String($bytes)
    # Decode inside the container and pipe to psql — avoids all shell quoting issues
    $result = docker exec platform-postgres bash -c "echo '$b64' | base64 -d | psql -U platform_user -d platform 2>&1"
    return $result
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  T7 Audit Service -- Smoke Test"              -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# -- Test 1: Health /ready -----------------------------------------------------
Write-Host "[ Test 1 ] Health /ready" -ForegroundColor Yellow
try {
    $r = Invoke-RestMethod -Uri "$BASE/health/ready" -UseBasicParsing -ErrorAction Stop
    if ($r.status -eq "ready" -and $r.db -eq "ok") {
        Pass "/health/ready => status=ready, db=ok"
    } else {
        Fail "/health/ready unexpected body: $($r | ConvertTo-Json)"
    }
} catch { Fail "/health/ready failed: $_" }

# -- Test 2: Health /live ------------------------------------------------------
Write-Host ""
Write-Host "[ Test 2 ] Health /live" -ForegroundColor Yellow
try {
    $r = Invoke-RestMethod -Uri "$BASE/health/live" -UseBasicParsing -ErrorAction Stop
    if ($r.status -eq "alive") { Pass "/health/live => status=alive" }
    else { Fail "/health/live unexpected body: $($r | ConvertTo-Json)" }
} catch { Fail "/health/live failed: $_" }

# -- Test 3: Append-Only Trigger -----------------------------------------------
Write-Host ""
Write-Host "[ Test 3 ] Append-Only Trigger (UPDATE/DELETE must fail)" -ForegroundColor Yellow
$smokeId = [guid]::NewGuid().ToString()

$insertResult = Invoke-SQL "INSERT INTO audit.audit_log (event_type, entity_type, entity_id, payload) VALUES ('Smoke.Test', 'Test', '$smokeId'::uuid, '{""smoke"":true}');"
if ($insertResult -match "INSERT 0 1") {
    Pass "Direct INSERT succeeded"
} else {
    Fail "INSERT failed: $insertResult"
}

$updateResult = Invoke-SQL "UPDATE audit.audit_log SET event_type = 'Hacked' WHERE entity_id = '$smokeId'::uuid;"
if ($updateResult -match "cannot be updated or deleted") {
    Pass "UPDATE blocked by prevent_mutation() trigger"
} else {
    Fail "UPDATE was NOT blocked! Output: $updateResult"
}

$deleteResult = Invoke-SQL "DELETE FROM audit.audit_log WHERE entity_id = '$smokeId'::uuid;"
if ($deleteResult -match "cannot be updated or deleted") {
    Pass "DELETE blocked by prevent_mutation() trigger"
} else {
    Fail "DELETE was NOT blocked! Output: $deleteResult"
}

# -- Test 4: GET /audit/case/{id} — row visible in API -------------------------
Write-Host ""
Write-Host "[ Test 4 ] GET /audit/case/{caseId} -- row from DB visible in API" -ForegroundColor Yellow
$caseId = [guid]::NewGuid().ToString()
$casePayload = '{"caseId":"' + $caseId + '","caseNumber":"SMOKE-001"}'
Invoke-SQL "INSERT INTO audit.audit_log (event_type, entity_type, entity_id, payload) VALUES ('Case.Created', 'Case', '$caseId'::uuid, '$casePayload'::jsonb);" | Out-Null

try {
    $r = Invoke-RestMethod -Uri "$BASE/api/v1/audit/case/$caseId" `
         -Headers @{"X-User-Role" = "INVESTIGATOR"} -UseBasicParsing -ErrorAction Stop
    if ($r.data.total -ge 1 -and $r.data.items[0].eventType -eq "Case.Created") {
        Pass "GET /audit/case/$caseId => total=$($r.data.total), eventType=$($r.data.items[0].eventType)"
    } else {
        Fail "Wrong data: $($r | ConvertTo-Json -Depth 4)"
    }
} catch { Fail "GET /audit/case failed: $_" }

# -- Test 5: GET /audit/entity/{id} --------------------------------------------
Write-Host ""
Write-Host "[ Test 5 ] GET /audit/entity/{entityId}" -ForegroundColor Yellow
try {
    $r = Invoke-RestMethod -Uri "$BASE/api/v1/audit/entity/$caseId`?entityType=Case" `
         -Headers @{"X-User-Role" = "INVESTIGATOR"} -UseBasicParsing -ErrorAction Stop
    if ($r.data.total -ge 1) {
        Pass "GET /audit/entity/$caseId?entityType=Case => total=$($r.data.total)"
    } else {
        Fail "Returned 0 items"
    }
} catch { Fail "GET /audit/entity failed: $_" }

# -- Test 6: RBAC enforcement --------------------------------------------------
Write-Host ""
Write-Host "[ Test 6 ] RBAC enforcement" -ForegroundColor Yellow

# No role -> 403
try {
    Invoke-WebRequest -Uri "$BASE/api/v1/audit/case/$caseId" -UseBasicParsing -ErrorAction Stop | Out-Null
    Fail "Expected 403 (no role header) but got 200"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 403) { Pass "No X-User-Role => 403 FORBIDDEN_ROLE" }
    else { Fail "Expected 403, got $code" }
}

# CITIZEN role -> 403
try {
    Invoke-WebRequest -Uri "$BASE/api/v1/audit/case/$caseId" `
        -Headers @{"X-User-Role" = "CITIZEN"} -UseBasicParsing -ErrorAction Stop | Out-Null
    Fail "Expected 403 for CITIZEN role but got 200"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 403) { Pass "X-User-Role=CITIZEN => 403 FORBIDDEN_ROLE" }
    else { Fail "Expected 403 for CITIZEN, got $code" }
}

# ADMIN role -> 200
try {
    $r = Invoke-RestMethod -Uri "$BASE/api/v1/audit/case/$caseId" `
         -Headers @{"X-User-Role" = "ADMIN"} -UseBasicParsing -ErrorAction Stop
    if ($r.status -eq "success") { Pass "X-User-Role=ADMIN => 200 allowed" }
    else { Fail "ADMIN got unexpected: $($r | ConvertTo-Json)" }
} catch { Fail "ADMIN role request failed: $_" }

# -- Test 7: Invalid UUID -> 400 -----------------------------------------------
Write-Host ""
Write-Host "[ Test 7 ] Invalid UUID => 400 INVALID_UUID" -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri "$BASE/api/v1/audit/case/not-a-uuid" `
        -Headers @{"X-User-Role" = "INVESTIGATOR"} -UseBasicParsing -ErrorAction Stop | Out-Null
    Fail "Expected 400 for invalid UUID but got 200"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 400) { Pass "Invalid UUID => 400 INVALID_UUID" }
    else { Fail "Expected 400, got $code" }
}

# -- Test 8: Non-existent caseId -> 200 empty (not 404) ------------------------
Write-Host ""
Write-Host "[ Test 8 ] Non-existent caseId => 200 empty items (404 deferred to BFF)" -ForegroundColor Yellow
$ghostId = [guid]::NewGuid().ToString()
try {
    $r = Invoke-RestMethod -Uri "$BASE/api/v1/audit/case/$ghostId" `
         -Headers @{"X-User-Role" = "INVESTIGATOR"} -UseBasicParsing -ErrorAction Stop
    if ($r.data.total -eq 0 -and $r.data.items.Count -eq 0 -and $r.data.hasMore -eq $false) {
        Pass "Non-existent caseId => 200, total=0, items=[], hasMore=false"
    } else {
        Fail "Expected empty result, got: $($r | ConvertTo-Json -Depth 3)"
    }
} catch { Fail "Non-existent caseId request failed: $_" }

# -- Test 9: Cursor Pagination -------------------------------------------------
Write-Host ""
Write-Host "[ Test 9 ] Cursor Pagination (15 rows, limit=10 => 2 pages)" -ForegroundColor Yellow
$pgCaseId = [guid]::NewGuid().ToString()

# Insert 15 rows with a DO block
$doBlock = @"
DO `$`$ DECLARE i INT; BEGIN FOR i IN 1..15 LOOP INSERT INTO audit.audit_log (event_type, entity_type, entity_id, payload) VALUES ('Case.Updated', 'Case', '$pgCaseId'::uuid, ('{"step":' || i || ',"caseId":"$pgCaseId"}')::jsonb); END LOOP; END; `$`$;
"@
Invoke-SQL $doBlock | Out-Null

try {
    # Page 1
    $p1 = Invoke-RestMethod -Uri "$BASE/api/v1/audit/case/$pgCaseId`?limit=10" `
          -Headers @{"X-User-Role" = "INVESTIGATOR"} -UseBasicParsing -ErrorAction Stop
    $cursor = $p1.data.nextCursor

    if ($p1.data.items.Count -eq 10 -and $p1.data.hasMore -eq $true -and $p1.data.total -eq 15) {
        Pass "Page 1 => items=10, hasMore=true, total=15"
    } else {
        Fail "Page 1 wrong: items=$($p1.data.items.Count), hasMore=$($p1.data.hasMore), total=$($p1.data.total)"
    }

    # Page 2
    $p2 = Invoke-RestMethod -Uri "$BASE/api/v1/audit/case/$pgCaseId`?limit=10&cursor=$cursor" `
          -Headers @{"X-User-Role" = "INVESTIGATOR"} -UseBasicParsing -ErrorAction Stop

    if ($p2.data.items.Count -eq 5 -and $p2.data.hasMore -eq $false -and $null -eq $p2.data.nextCursor) {
        Pass "Page 2 => items=5, hasMore=false, nextCursor=null"
    } else {
        Fail "Page 2 wrong: items=$($p2.data.items.Count), hasMore=$($p2.data.hasMore)"
    }
} catch { Fail "Pagination test failed: $_" }

# -- Test 10: Prometheus metrics -----------------------------------------------
Write-Host ""
Write-Host "[ Test 10 ] Prometheus /metrics endpoint" -ForegroundColor Yellow
try {
    $metrics = Invoke-RestMethod -Uri "$BASE/metrics" -UseBasicParsing -ErrorAction Stop
    if ($metrics -match "http_requests_total") {
        Pass "/metrics => Prometheus format, http_requests_total present"
    } else {
        Fail "/metrics missing http_requests_total"
    }
} catch { Fail "/metrics failed: $_" }

# -- Summary -------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
$color = if ($script:FAIL -eq 0) { "Green" } else { "Red" }
Write-Host "  PASSED: $($script:PASS)   FAILED: $($script:FAIL)" -ForegroundColor $color
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

if ($script:FAIL -gt 0) { exit 1 } else { exit 0 }
