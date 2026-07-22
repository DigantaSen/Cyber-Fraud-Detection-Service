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
| **Telecom Admin Portal** | http://localhost:5174 | `telecom.admin@fraud.gov.in` / `Telecom@2024!` |
| **Bank Fraud Monitor** | http://localhost:5173 | `bank.officer@fraud.gov.in` / `BankOff@2024!` |
| **MinIO Console** (Storage) | http://localhost:9001 | `minioadmin` / `change_me_minio` |
| **Neo4j Browser** (Graph) | http://localhost:7474 | `neo4j` / `change_me_neo4j` |
| **Redis Cache** | localhost:6379 | `change_me_redis` |

---

## 🧠 Key Platform Assumptions & Business Rules

1. **⚡ Real-Time Telecom Interdiction Path (T15 — <300ms SLA)**:
   - Synchronous bypass path for active telecom scam calls: `Telecom Event` ➔ `Event Processing` ➔ `Inference Orchestrator` (`scam-nlp` + `audio-analyzer` under a 200ms budget).
   - On `HIGH`/`CRITICAL` risk verdict: Concurrently executes **Bank Pre-Transfer Block** (`POST /bank/block-transfer`) and **MHA Webhook Alert** (`POST /alert`), returning a `BLOCK` interdiction decision to the telecom carrier within **<300ms P99 SLA** (measured: ~87ms).
   - Asynchronous outbox writes (`TelecomEvent.Ingested` & `Intervention.Requested`) execute via background tasks *after* the HTTP response returns to preserve legal admissibility without blocking the SLA.

2. **🏦 Bank Portal Involvement Scope (4-Condition Rule)**:
   - Since there is no separate form input field for Transaction ID in the Citizen Report Form, a case is **ONLY** routed to and displayed in the Bank Portal to stop transactions if **ALL 4 CONDITIONS** are satisfied:
     1. **Transaction ID / UTR / Ref Number** is present in the title or description text (e.g. `TXN-987654`, `UTR: 9876543210`, `Ref #12345`).
     2. **Fraud Bank Account Number or UPI ID** (e.g. `suspect@okicici`, `987654321098`) is specified in the suspect section or description.
     3. **Monetary Amount** is explicitly mentioned in the title/description in any Indian numeric format (e.g. `1.55 lakh`, `2.5 Lakhs`, `1.5 crore`, `50,000`, `₹75,000`, `INR 1,20,000`, `Rs 50000`).
     4. **Risk Tier** is **`HIGH`** or **`CRITICAL`** (or fused score ≥ 70).
   - *If any condition is missing, the Bank does NOT get involved, and the case remains within Telecom or Law Enforcement (MHA) scope.*

3. **🚨 MHA National Portal Alert Triggers (T13-C)**:
   - MHA alerts are automatically triggered for both **`HIGH`** and **`CRITICAL`** risk tiers when AI multi-source fusion, evidence re-analysis, or investigator overrides escalate threat indicators. Real-time alerts stream to the `gov-mha` portal via Server-Sent Events (SSE).

5. **🏦 Bank Interdiction & Action Workflow (3-Tab System & Notifications)**:
   - **Newest-First Display**: Transactions across all tabs (Pending Review, Blocked, Dismissed) are sorted chronologically with the newest cases at the top.
   - **3-Tab Workflow**:
     - **⚠️ Pending Review**: Active HIGH/CRITICAL cases matching the 4-condition rule. Bank officials can select **🚫 Block Transaction** or **👁 No Action / Dismiss**.
     - **🚫 Blocked**: Confirmed blocked cases. Blocking writes an immutable `BANK_ACTION:BLOCKED` note into `investigation.cases` and dispatches in-app notifications to both the Citizen (reporter) and Investigator.
     - **👁 Dismissed**: Dismissed cases where no action was taken (`BANK_ACTION:DISMISSED`), archived without external notifications.
   - **Citizen & Investigator Visual Feedback**:
     - **Citizen Portal**: Renders a recovery banner (*"Bank has Blocked this Transaction — Money recovery process initiated"*).
     - **Investigator Portal**: Displays a middle operational card (`BANK INTERDICTION: Transaction Blocked`) positioned below the 4-step lifecycle path and above the AI verdict grid.

4. **📁 Evidence Integrity & Signed Packages**:
   - Evidence presigned URLs bind exact `Content-Type` headers for tamper-resistant MinIO uploads.
   - Reporting service generates canonical RS256-signed JSON intelligence packages for law enforcement and government court admissibility.

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
│   ├── search/                 # ✅ T8f — OpenSearch Kafka Consumer (Diganta) - COMPLETED
│   ├── inference-orchestrator/ # ✅ T8  — Multi-source AI Fusion (Diganta) - COMPLETED
│   ├── event-processing/       # ✅ T8b — Kafka backbone + webhooks (Diganta) - COMPLETED
│   ├── audit/                  # ✅ T7  — Immutable Audit Log (Diganta) - COMPLETED
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
| **Diganta** | Infra, Orchestrator, Event Processing, Audit, Search, BFFs | T1, T2, T3, T3b, T4c, ✅T7, T8, ✅T8b, ✅T8f |
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
