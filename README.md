# AI Fraud Detection Platform

> AI-powered Digital Public Safety platform — Multi-source ML fusion, real-time fraud detection, graph intelligence, and geospatial crime mapping.

---

## ⚡ 1-Click Setup

Follow these simple steps to spin up the entire production-grade infrastructure locally.

### Step 1 — Prerequisites
Ensure **Docker Desktop** is installed and running (the whale icon must be visible in your taskbar). 
- If you don't have it, [download it here](https://www.docker.com/products/docker-desktop/).
- Ensure you have allocated at least **6GB of RAM** to Docker (Settings → Resources).

### Step 2 — Run the Setup Script
Open a **PowerShell terminal** inside this project directory and run:

```powershell
.\setup.ps1
```
*This script will automatically create your `.env` file, pull all required Docker images (~8GB), boot 14 services, wait for them to become healthy, and provision all required Kafka topics and OpenSearch indices.*

### Step 3 — Verify
Once the script completes successfully, the platform is ready! You can explore the observability and administrative dashboards here:

| Dashboard | URL | Credentials |
|---|---|---|
| **Grafana** (Observability) | http://localhost:3000 | `admin` / `admin` |
| **Kong Admin** (API Gateway) | http://localhost:8001 | — |
| **MinIO Console** (Storage) | http://localhost:9001 | `minioadmin` / `change_me_minio` |
| **Neo4j Browser** (Graph) | http://localhost:7474 | `neo4j` / `change_me_neo4j` |

---

## Project Structure

```text
.
├── backend/
│   ├── auth/                   # T4  - Identity & Auth (Surjit)
│   ├── case/                   # T5a - Case Management (Surjit)
│   ├── citizen-bff/            # T4b - Citizen BFF (Surjit)
│   ├── department-bffs/        # T4c - Bank, Telecom, and Gov BFFs (Diganta)
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
├── docs/                       ← API contracts + LLD sequences
├── docker-compose.yml
└── setup.ps1                   ← 1-Click setup script
```

---

## Team Assignments

| Member | Services | Tasks |
|---|---|---|
| **Diganta** | Infra, Orchestrator, Event Processing, Audit, Search, BFFs | T1, T2, T3, T3b, T4c, T7, T8, T8b, T8f |
| **Surjit** | Auth, Case, Citizen BFF, Bot, Citizen/Bank/Telecom UIs | T4, T4b, T5a, T5b, T5c, T5d, T5e |
| **Nilkanta** | Evidence, Reporting, Investigator BFF, Graph, Geo, Notification, Inv/Gov UIs | T6a, T6b, T6c, T6d, T5f, T8c, T8d, T8e |
| **Kushal** | All 4 ML models + Edge sync | T9, T10a-d, T11, T12 |

## Commit Convention

```text
feat(case): add Pending_AI → Investigating re-entry on AI timeout
fix(orchestrator): retry ML model once before marking UNAVAILABLE
docs(design): finalize case.md API contract v1
test(evidence): assert scan_file() stub called on every confirmed upload
```

**Never commit:** `.env`, model weights (`*.pt`, `*.pkl`), datasets, DB dumps — see `.gitignore`.
