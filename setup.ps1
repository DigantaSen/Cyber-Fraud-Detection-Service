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
Write-Host "[2/4] Starting infrastructure via Docker Compose (this may take a while to pull images)..." -ForegroundColor Yellow
docker compose up -d

Write-Host "Waiting for all containers to become healthy (timeout: 10 minutes)..." -ForegroundColor Yellow
$timeout = [DateTime]::UtcNow.AddMinutes(10)

# Containers that explicitly disable healthchecks — they are considered OK once "running"
$noHealthcheckContainers = @("platform-outbox-publisher", "platform-search-consumer",
                              "platform-kafka-init", "platform-minio-init")

while ([DateTime]::UtcNow -lt $timeout) {
    $all = docker compose ps --format json | ConvertFrom-Json
    if ($null -eq $all -or $all.Count -eq 0) {
        Write-Host "Waiting for Docker Compose to start containers..." -ForegroundColor DarkGray
        Start-Sleep 5
        continue
    }

    $unhealthy = $all | Where-Object {
        $name = $_.Name
        if ($noHealthcheckContainers -contains $name) {
            # For containers with disabled healthchecks: only need State == "running"
            $_.State -ne "running"
        } elseif ($_.Health -and $_.Health -ne "") {
            # Container has an active healthcheck — must be "healthy"
            $_.Health -ne "healthy"
        } else {
            # No healthcheck configured — just needs to be "running"
            $_.State -ne "running"
        }
    }

    if ($null -eq $unhealthy -or $unhealthy.Count -eq 0) {
        Write-Host "All containers are running and healthy!" -ForegroundColor Green
        break
    }

    $names = ($unhealthy.Name -join ', ')
    Write-Host "Still waiting for: $names" -ForegroundColor DarkGray
    Start-Sleep 5
}

if ([DateTime]::UtcNow -ge $timeout) {
    Write-Host "Warning: Timed out waiting for containers. Some may still be starting." -ForegroundColor Red
    Write-Host "You can check status with: docker compose ps" -ForegroundColor Yellow
}

# 3. Provision Kafka Topics
Write-Host "[3/4] Provisioning Kafka Topics..." -ForegroundColor Yellow
docker compose exec kafka /bin/bash /infra/kafka/provision-topics.sh

# 4. Provision OpenSearch Indices
# Note: case_index and evidence_index are created automatically by the search service
# on startup (opensearch_client.py -> ensure_indices()). This step just waits for
# OpenSearch to be ready and confirms the indices exist.
Write-Host "[4/4] Verifying OpenSearch Indices..." -ForegroundColor Yellow
Write-Host "Waiting for OpenSearch cluster health to be yellow/green..." -ForegroundColor DarkGray

$osReady = $false
for ($i = 0; $i -lt 5; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=30s" -Method GET -ErrorAction Stop
        if ($health.timed_out -eq $false -and ($health.status -eq 'yellow' -or $health.status -eq 'green')) {
            $osReady = $true
            break
        }
        Write-Host "OpenSearch not ready yet, retrying... ($($i+1)/5)" -ForegroundColor DarkGray
    } catch {
        Write-Host "OpenSearch unreachable, retrying... ($($i+1)/5)" -ForegroundColor DarkGray
        Start-Sleep 10
    }
}

if ($osReady) {
    Write-Host "OpenSearch is ready (status: $($health.status))." -ForegroundColor Green
    Write-Host "Note: case_index and evidence_index are created automatically by the search service on first startup." -ForegroundColor DarkGray
    # Verify indices exist (the search service creates them)
    try {
        $indices = Invoke-RestMethod -Uri "http://localhost:9200/_cat/indices?format=json" -Method GET
        $indexNames = $indices | ForEach-Object { $_.index }
        if ($indexNames -contains "case_index") {
            Write-Host "  case_index:     OK" -ForegroundColor Green
        } else {
            Write-Host "  case_index:     Not yet created (will be created when search service starts)" -ForegroundColor Yellow
        }
        if ($indexNames -contains "evidence_index") {
            Write-Host "  evidence_index: OK" -ForegroundColor Green
        } else {
            Write-Host "  evidence_index: Not yet created (will be created when search service starts)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  Could not list indices: $_" -ForegroundColor DarkGray
    }
} else {
    Write-Host "Warning: OpenSearch did not become ready in time." -ForegroundColor Red
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "You can now access:"
Write-Host "  Grafana:         http://localhost:3000  (admin/admin)"
Write-Host "  Kong Gateway:    http://localhost:8000"
Write-Host "  Search API:      http://localhost:8006"
Write-Host "  MinIO Console:   http://localhost:9001  (minioadmin/change_me_minio)"
Write-Host "  Neo4j Browser:   http://localhost:7474  (neo4j/change_me_neo4j)"
Write-Host "  OpenSearch:      http://localhost:9200"
Write-Host "=============================================" -ForegroundColor Cyan

