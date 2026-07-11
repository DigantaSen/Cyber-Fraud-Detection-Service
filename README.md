# AI Fraud Detection Platform

> AI-powered Digital Public Safety platform — Multi-source ML fusion, real-time fraud detection, graph intelligence, and geospatial crime mapping.

---

## ⚡ Full Setup — Step by Step

Follow these steps **exactly in order**. Each step must succeed before moving to the next.

---

### Step 1 — Install Docker Desktop

> Skip if Docker Desktop is already installed and running (whale icon in taskbar).

1. Download: **https://www.docker.com/products/docker-desktop/**
2. Run the installer — accept defaults
3. **Restart your PC** after install (required for PATH to update)
4. Launch Docker Desktop from Start Menu — wait for the whale icon to appear in the taskbar
5. Verify in a **new** PowerShell/Terminal window:

```powershell
docker --version
# Expected: Docker version 26.x.x, build ...

docker compose version
# Expected: Docker Compose version v2.x.x
```

> ⚠️ If you see "docker is not recognized": Docker Desktop is not running, or you need to **restart VS Code / your terminal** after installing.

---

### Step 2 — Open the Project

Open a **new PowerShell terminal** inside VS Code (`` Ctrl+` ``) and confirm you're in the right directory:

```powershell
# You should see this path
pwd
# C:\path\to\AI_Fraud_Detection_System

# Confirm docker-compose.yml is here
Test-Path docker-compose.yml
# True
```

---

### Step 3 — Configure Environment

```powershell
# .env was already copied, verify it exists
Test-Path .env
# True

# Optional: open and review .env — change any "change_me_*" values
# The defaults work fine for local development
notepad .env
```

---

### Step 4 — Pull Images (Optional — speeds up Step 5)

This downloads all Docker images in the background while you work.

```powershell
docker compose pull
# Takes 5-10 min depending on internet speed
# Images: ~8 GB total (OpenSearch + Neo4j + Kafka + Grafana stack are the largest)
```

---

### Step 5 — Start All Infrastructure

```powershell
docker compose up -d
```

> **Cold start after images are pulled: ~90 seconds.**

Watch the output — you should see services starting one by one. When it returns to the prompt, move to Step 6.

---

### Step 6 — Verify All Services Are Healthy

```powershell
docker compose ps
```

All services should show `healthy` or `running`. Wait and re-run if any show `starting`:

```powershell
# Re-check every 15 seconds until all are healthy
while ($true) {
    $unhealthy = docker compose ps --format json | ConvertFrom-Json | Where-Object { $_.Health -ne "healthy" -and $_.State -ne "running" }
    if ($unhealthy.Count -eq 0) { Write-Host "All services healthy!"; break }
    Write-Host "Still starting: $($unhealthy.Name -join ', ') — waiting..."
    Start-Sleep 15
}
```

**Expected services (14):** postgres, postgis, neo4j, redis, opensearch, opensearch-dashboards, kafka, minio, minio-init, kong, prometheus, grafana, loki, tempo

---

### Step 7 — Provision Kafka Topics

Creates all **29 domain event topics** with 12 partitions each and tiered retention (Case: 7 days, Audit: 30 days, Predictions: 14 days).

```powershell
docker compose exec kafka /bin/bash /infra/kafka/provision-topics.sh
```

> If the script isn't found inside the container yet, run it from the host instead:

```powershell
# Alternative: run the script inline
docker compose exec kafka /bin/bash -c "
KAFKA_BIN=/opt/bitnami/kafka/bin
B=localhost:9092

# Case domain — 7 day retention (604800000 ms)
for topic in case.created case.updated case.assigned case.closed; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Evidence domain — 7 day retention
for topic in evidence.uploaded evidence.deleted; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Audio domain — 7 day retention
for topic in audio.uploaded audio.processed; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Prediction domain — 14 day retention (1209600000 ms)
for topic in prediction.requested prediction.completed prediction.failed prediction.overridden; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=1209600000 2>/dev/null && echo \"OK: \$topic\"
done

# Notification domain — 7 day retention
for topic in notification.requested notification.sent notification.delivered notification.failed mhaalert.sent; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Audit domain — 30 day retention (2592000000 ms)
for topic in audit.recorded; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=2592000000 2>/dev/null && echo \"OK: \$topic\"
done

# Entity / Graph domain — 14 day retention
for topic in entity.relationship.discovered fraud.ring.node.identified; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=1209600000 2>/dev/null && echo \"OK: \$topic\"
done

# User / Identity domain — 7 day retention
for topic in user.registered user.login.failed; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Telecom / Interdiction domain — 7 day retention
for topic in callsession.initiated callsession.flagged intervention.requested; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Geospatial domain — 7 day retention
for topic in geo.layer.updated counterfeit.scan.submitted; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=604800000 2>/dev/null && echo \"OK: \$topic\"
done

# Reporting domain — 14 day retention
for topic in report.generated intelligence.package.generated; do
  \$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --create --if-not-exists \
    --topic \$topic --partitions 12 --replication-factor 1 \
    --config retention.ms=1209600000 2>/dev/null && echo \"OK: \$topic\"
done

echo '--- All 29 topics ---'
\$KAFKA_BIN/kafka-topics.sh --bootstrap-server \$B --list | sort
"
```

---

### Step 8 — Create OpenSearch Indices

Creates `case_index` and `evidence_index` with explicit field mappings. **1 shard (single local node).**

```powershell
# Wait for OpenSearch to be fully ready first
Start-Sleep 5

# Create case_index — 15 explicit fields, dynamic mapping OFF
Invoke-RestMethod -Method PUT -Uri "http://localhost:9200/case_index" `
  -ContentType "application/json" `
  -Body '{
    "settings": { "number_of_shards": 1, "number_of_replicas": 0 },
    "mappings": {
      "dynamic": "false",
      "properties": {
        "caseId":              { "type": "keyword" },
        "title":               { "type": "text" },
        "description":         { "type": "text",    "analyzer": "standard" },
        "notes":               { "type": "text",    "analyzer": "standard" },
        "status":              { "type": "keyword" },
        "riskTier":            { "type": "keyword" },
        "confidence":          { "type": "float" },
        "fusedScore":          { "type": "float" },
        "jurisdictionId":      { "type": "keyword" },
        "assignedInvestigator":{ "type": "keyword" },
        "reporterPhone":       { "type": "keyword" },
        "complaintLocation":   { "type": "geo_point" },
        "reporterEntityName":  { "type": "text",    "fields": { "keyword": { "type": "keyword" } } },
        "createdAt":           { "type": "date" },
        "updatedAt":           { "type": "date" }
      }
    }
  }'

# Create evidence_index — 8 explicit fields
Invoke-RestMethod -Method PUT -Uri "http://localhost:9200/evidence_index" `
  -ContentType "application/json" `
  -Body '{
    "settings": { "number_of_shards": 1, "number_of_replicas": 0 },
    "mappings": {
      "dynamic": "false",
      "properties": {
        "evidenceId":  { "type": "keyword" },
        "caseId":      { "type": "keyword" },
        "fileName":    { "type": "text" },
        "mimeType":    { "type": "keyword" },
        "sha256":      { "type": "keyword" },
        "fileSize":    { "type": "long" },
        "uploadedBy":  { "type": "keyword" },
        "createdAt":   { "type": "date" }
      }
    }
  }'

Write-Host "Indices created. Verifying..."
Invoke-RestMethod "http://localhost:9200/_cat/indices?v"
```

---

### Step 9 — Verify All Access Points

Open each URL in your browser to confirm services are running:

```powershell
# Quick health check — run all at once
$services = @(
  @{Name="Kong Gateway";    Url="http://localhost:8000"},
  @{Name="Kong Admin";      Url="http://localhost:8001"},
  @{Name="Grafana";         Url="http://localhost:3000"},
  @{Name="MinIO Console";   Url="http://localhost:9001"},
  @{Name="OpenSearch";      Url="http://localhost:9200/_cluster/health"},
  @{Name="Prometheus";      Url="http://localhost:9090/-/healthy"},
  @{Name="Loki";            Url="http://localhost:3100/ready"},
  @{Name="Tempo";           Url="http://localhost:3200/ready"},
  @{Name="Neo4j";           Url="http://localhost:7474"}
)
foreach ($svc in $services) {
  try {
    $r = Invoke-WebRequest $svc.Url -TimeoutSec 5 -EA Stop
    Write-Host "OK  $($svc.Name)" -ForegroundColor Green
  } catch {
    Write-Host "FAIL $($svc.Name) — $($_.Exception.Message)" -ForegroundColor Red
  }
}
```

---

### Step 10 — Open Grafana (Observability Dashboard)

1. Go to **http://localhost:3000**
2. Login: `admin` / `admin`
3. Navigate to **Connections → Data Sources** — you should see **Prometheus, Loki, Tempo** pre-configured
4. Navigate to **Explore** → select Loki → logs will appear once backend services start

---

## ✅ Setup Complete

When all checks pass, the infrastructure is ready. Next steps:

```
Diganta → Start T2: write API contracts in /docs/
Surjit  → Copy backend/template/ to backend/auth/ and start T4 Auth Service
Nilkanta→ Copy backend/template/ to backend/evidence/ and start T6a Evidence Service
Kushal  → Read /docs/ml-contract.md (created in T2) and start T9 data prep
```

---

## Service URLs Reference

| Service | URL | Credentials |
|---|---|---|
| **Kong Gateway** (API entry) | http://localhost:8000 | — |
| **Kong Admin** | http://localhost:8001 | — |
| **Grafana** | http://localhost:3000 | admin / admin |
| **MinIO Console** | http://localhost:9001 | minioadmin / change_me_minio |
| **OpenSearch Dashboards** | http://localhost:5601 | — |
| **Neo4j Browser** | http://localhost:7474 | neo4j / change_me_neo4j |
| **Prometheus** | http://localhost:9090 | — |
| **Tempo (traces)** | http://localhost:3200 | — |
| **Loki (logs)** | http://localhost:3100 | — |
| **Kafka** (external) | localhost:29092 | — |
| **PostgreSQL** | localhost:5432 | platform_user / change_me_postgres |
| **PostGIS** | localhost:5434 | geo_user / change_me_postgis |

---

## Makefile Commands (requires GNU make)

Install make on Windows: `winget install GnuWin32.Make`

```bash
make up            # Start all services
make down          # Stop (keep data)
make down-v        # Stop + delete all data
make ps            # Service status
make logs          # Tail all logs
make logs-service s=kafka   # Tail one service
make kafka-topics  # Provision Kafka topics
make opensearch-index       # Create search indices
make kong-reload   # Reload Kong config
make health        # Health summary table
```

---

## Troubleshooting

### "docker is not recognized"
- Docker Desktop is not running → open it from Start Menu
- Or restart VS Code / terminal after installing Docker Desktop

### OpenSearch won't start (exit code 137)
- Increase Docker Desktop memory: **Settings → Resources → Memory → 6 GB minimum**

### Neo4j fails to start
- Check APOC plugin download — needs internet access
- Or remove `NEO4JPLUGINS` from compose and add APOC manually later

### Port already in use
- Check what's using the port: `netstat -ano | findstr :5432`
- Stop the conflicting service or change the port in `docker-compose.yml`

### Reset everything (nuclear option)
```powershell
docker compose down -v    # Deletes ALL data
docker compose up -d      # Fresh start (~90 seconds)
```

---

## Project Structure

```
.
├── backend/
│   ├── template/               ← Copy this for every new service
│   │   ├── main.py             ← FastAPI with OTel + loguru + /health endpoints
│   │   ├── config.py           ← Pydantic Settings (reads env/Vault)
│   │   ├── requirements.txt    ← All shared deps pinned
│   │   └── Dockerfile          ← Non-root, health check, uvicorn
│   ├── auth/                   # T4  - Identity & Auth (Surjit)
│   ├── case/                   # T5a - Case Management (Surjit)
│   ├── citizen-bff/            # T4b - Citizen BFF (Surjit)
│   ├── bank-bff/               # T4c - Bank BFF (Diganta)
│   ├── telecom-bff/            # T4c - Telecom BFF (Diganta)
│   ├── gov-bff/                # T4c - Gov BFF (Diganta)
│   ├── bot/                    # T5b - Conversational Bot (Surjit)
│   ├── evidence/               # T6a - Evidence Service (Nilkanta)
│   ├── reporting/              # T6b - Reporting + Intelligence Packages (Nilkanta)
│   ├── investigator-bff/       # T6d - Investigator BFF (Nilkanta)
│   ├── graph/                  # T8c - Entity Graph Service (Nilkanta)
│   ├── geospatial/             # T8d - Geospatial Intelligence (Nilkanta)
│   ├── notification/           # T8e — Notification + MHA Alert (Nilkanta)
│   ├── search/                 # T8f — OpenSearch Kafka Consumer (Diganta)
│   ├── inference-orchestrator/ # T8  — Multi-source AI Fusion (Diganta)
│   ├── event-processing/       # T8b — Kafka backbone + webhooks (Diganta)
│   └── audit/                  # T7  — Immutable Audit Log (Diganta)
├── frontend/
│   ├── citizen/                # T5c - Citizen UI (Surjit)
│   ├── investigator/           # T6c - Investigator Dashboard (Nilkanta)
│   ├── telecom/                # T5d - Telecom Administrator UI (Surjit)
│   ├── bank/                   # T5e - Bank Official UI (Surjit)
│   ├── gov/                    # T5f - Gov / MHA Portal (Nilkanta)
├── ml/
│   ├── scam-nlp/               # T10a (Kushal)
│   ├── counterfeit-cv/         # T10b (Kushal)
│   ├── graph-analyzer/         # T10c (Kushal)
│   ├── audio-analyzer/         # T10d (Kushal)
│   └── edge/                   # T11  (Kushal)
├── infra/                      ← All infrastructure config files
├── docs/                       ← T2/T3 API contracts + sequence diagrams
├── docker-compose.yml
├── Makefile
├── .env.example
└── .gitignore
```

## Team Assignments

| Member | Services | Tasks |
|---|---|---|
| **Diganta** | Infra, Orchestrator, Event Processing, Audit, Search, BFFs | T1, T2, T3, T3b, T4c, T7, T8, T8b, T8f |
| **Surjit** | Auth, Case, Citizen BFF, Bot, Citizen/Bank/Telecom UIs | T4, T4b, T5a, T5b, T5c, T5d, T5e |
| **Nilkanta** | Evidence, Reporting, Investigator BFF, Graph, Geo, Notification, Inv/Gov UIs | T6a, T6b, T6c, T6d, T5f, T8c, T8d, T8e |
| **Kushal** | All 4 ML models + Edge sync | T9, T10a-d, T11, T12 |

## Commit Convention

```
feat(case): add Pending_AI → Investigating re-entry on AI timeout
fix(orchestrator): retry ML model once before marking UNAVAILABLE
docs(design): finalize case.md API contract v1
test(evidence): assert scan_file() stub called on every confirmed upload
```

**Never commit:** `.env`, model weights (`*.pt`, `*.pkl`), datasets, DB dumps — see `.gitignore`
