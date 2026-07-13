# setup.ps1
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  AI Fraud Detection Platform - Setup" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Environment variables
if (-not (Test-Path ".env")) {
    Write-Host "[1/4] Creating .env from .env.example..." -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
    } else {
        Write-Host "Warning: .env.example not found, creating an empty .env file." -ForegroundColor Red
        New-Item -ItemType File -Name ".env" | Out-Null
    }
} else {
    Write-Host "[1/4] .env already exists. Skipping." -ForegroundColor Green
}

# 2. Docker Compose Up
Write-Host "[2/4] Starting infrastructure via Docker Compose (this may take a while to pull 8GB of images)..." -ForegroundColor Yellow
docker compose up -d

Write-Host "Waiting for all containers to become healthy..." -ForegroundColor Yellow
while ($true) {
    # Check for unhealthy or starting containers
    # - If container has a healthcheck, it must be "healthy"
    # - If container has no healthcheck, it must be in "running" state
    $unhealthy = docker compose ps --format json | ConvertFrom-Json | Where-Object {
        ($_.Health -and $_.Health -ne "healthy") -or (-not $_.Health -and $_.State -ne "running")
    }
    
    # Check if ANY containers actually exist (avoid early exit if docker compose is still booting)
    $all = docker compose ps --format json | ConvertFrom-Json
    if ($all.Count -gt 0 -and ($null -eq $unhealthy -or $unhealthy.Count -eq 0)) { 
        Write-Host "All containers are running and healthy!" -ForegroundColor Green
        break 
    }
    
    $names = if ($unhealthy) { ($unhealthy.Name -join ', ') } else { "Waiting for docker engine..." }
    Write-Host "Still waiting for: $names" -ForegroundColor DarkGray
    Start-Sleep 5
}

# 3. Provision Kafka Topics
Write-Host "[3/4] Provisioning Kafka Topics..." -ForegroundColor Yellow
docker compose exec kafka /bin/bash /infra/kafka/provision-topics.sh

# 4. Provision OpenSearch Indices
Write-Host "[4/4] Provisioning OpenSearch Indices..." -ForegroundColor Yellow
Write-Host "Waiting for OpenSearch cluster health to be yellow/green..." -ForegroundColor DarkGray

$osReady = $false
$retries = 3
for ($i = 0; $i -lt $retries; $i++) {
    try {
        # OpenSearch natively waits up to 30s if wait_for_status=yellow is passed
        $health = Invoke-RestMethod -Uri "http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=30s" -Method GET -ErrorAction Stop
        if ($health.timed_out -eq $false -and ($health.status -eq 'yellow' -or $health.status -eq 'green')) {
            $osReady = $true
            break
        }
        Write-Host "OpenSearch not ready yet, retrying... ($($i+1)/$retries)" -ForegroundColor DarkGray
    } catch {
        Write-Host "OpenSearch unreachable, retrying... ($($i+1)/$retries)" -ForegroundColor DarkGray
        Start-Sleep 10
    }
}

if ($osReady) {
    Write-Host "OpenSearch is ready. Creating indices..." -ForegroundColor Green
    
    $caseJson = Get-Content "infra\opensearch\case_index.json" -Raw
    $evidenceJson = Get-Content "infra\opensearch\evidence_index.json" -Raw
    
    # Create Case Index
    try {
        Invoke-RestMethod -Uri "http://localhost:9200/case_index" -Method PUT -ContentType "application/json" -Body $caseJson -ErrorAction Stop | Out-Null
        Write-Host "Created case_index." -ForegroundColor Green
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 400) {
            Write-Host "case_index already exists. Skipping." -ForegroundColor DarkGray
        } else {
            Write-Host "Failed to create case_index: $_" -ForegroundColor Red
        }
    }
    
    # Create Evidence Index
    try {
        Invoke-RestMethod -Uri "http://localhost:9200/evidence_index" -Method PUT -ContentType "application/json" -Body $evidenceJson -ErrorAction Stop | Out-Null
        Write-Host "Created evidence_index." -ForegroundColor Green
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 400) {
            Write-Host "evidence_index already exists. Skipping." -ForegroundColor DarkGray
        } else {
            Write-Host "Failed to create evidence_index: $_" -ForegroundColor Red
        }
    }
} else {
    Write-Host "Warning: Failed to provision OpenSearch indices. OpenSearch did not become ready." -ForegroundColor Red
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "✅ Setup Complete!" -ForegroundColor Green
Write-Host "You can now access:"
Write-Host "  Grafana:            http://localhost:3000  (admin/admin)"
Write-Host "  Kong Gateway:       http://localhost:8000"
Write-Host "  MinIO Console:      http://localhost:9001  (minioadmin/change_me_minio)"
Write-Host "  Neo4j Browser:      http://localhost:7474  (neo4j/change_me_neo4j)"
Write-Host "=============================================" -ForegroundColor Cyan
