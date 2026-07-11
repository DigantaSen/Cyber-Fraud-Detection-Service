# High-Level Design (HLD)
**Project Name:** AI for Digital Public Safety (Distributed Platform)

---

## 1. Executive Summary
This High-Level Design (HLD) document defines the system architecture for the Digital Public Safety Distributed Platform. It translates the requirements outlined in the System Requirements Specification (SRS) into a concrete, cloud-agnostic microservices architecture. 

### 1.1 Architectural Boundary (AI Scope)
The design strictly separates the stateful, distributed workflow orchestration from the external AI Inference Platform to prevent scope creep.

```mermaid
flowchart LR
    subgraph Distributed Platform [IN SCOPE]
        Orch[Inference Orchestrator]
    end
    
    subgraph AI Platform [OUT OF SCOPE]
        AI[Model Inference & Training]
    end
    
    Orch <-->|REST / gRPC Contracts| AI
```

## 2. Architecture Principles
*   **Cloud-Agnostic:** Containerized, open-source technologies (e.g., Kubernetes, Kafka, PostgreSQL) allow deployment across AWS, Azure, GCP, or on-premises data centers with minimal modifications.
*   **Database-per-Service:** Each microservice completely owns its domain data. Direct database sharing is prohibited. In production, PgBouncer (transaction-mode connection pooler) sits in front of PostgreSQL to prevent DB connection exhaustion under horizontal scaling. For the hackathon demo, services connect directly to Postgres on port 5432.
*   **CQRS & Event-Driven Architecture (EDA):** The platform separates write models (ACID transactions) from read models (search/dashboards). State changes emit domain events, which update downstream read projections asynchronously. All Kafka topics are provisioned with **12 partitions** to allow up to 12 consumer pods per consumer group without rebalancing overhead.
*   **API-First & Contract Layer:** External APIs are versioned and strictly documented via OpenAPI specifications.
    *   **Production (Kubernetes):** Internal service-to-service communication uses **gRPC with strongly typed, versioned Protocol Buffers contracts** — lower latency, binary serialization, native streaming. Istio handles mTLS over gRPC automatically.
    *   **Docker Compose (local/demo):** Internal communication uses **HTTP/1.1 via `httpx.AsyncClient`** with connection pools. This provides identical contract semantics with simpler debugging and no proto compilation step.
*   **Stateless Horizontal Scaling:** All application services are stateless. All state is externalized to PostgreSQL, Redis, Neo4j, PostGIS, OpenSearch, or Kafka. Any service can be scaled to N replicas — Kafka consumer groups handle partition rebalancing automatically.
*   **Secrets Management:** Services read configuration from environment variables (`.env`) for the hackathon demo. Production deployment uses HashiCorp Vault with Vault Agent sidecar injection.
*   **Scalability Target:** 1M+ concurrent users, 5,000 RPS peak, 50,000 streaming events/second (SRS §10).

---

## 3. High-Level Logical Architecture

### 3.1 Domain Interaction Map
This component map illustrates the high-level flow of data across the distributed domains during a standard investigation.

```mermaid
flowchart LR
    Citizen[Citizen App / Mobile Edge] --> API[API Gateway]
    Command[Command Center] --> API
    Bank[Bank Portal] --> API
    Telco[Telecom Portal] --> API
    Gov[Gov Portal] --> API
    
    API --> BFF_Cit[Citizen BFF]
    API --> BFF_Inv[Investigator BFF]
    API --> BFF_Bank[Bank BFF]
    API --> BFF_Telco[Telecom BFF]
    API --> BFF_Gov[Gov BFF]
    API --> EventProc
    API --> Search[Search Service]
    API --> Auth[Identity Service]
    
    BFF_Cit --> Case[Case Service]
    BFF_Cit --> Bot[Conversational Bot]
    BFF_Cit --> Ev[Evidence Service]
    
    BFF_Inv --> Case
    BFF_Inv --> Ev
    BFF_Inv --> Search[Search Service]
    BFF_Inv --> Report[Reporting Service]
    BFF_Inv --> Entity[Entity Graph Service]
    
    BFF_Bank --> EventProc[Event Processing]
    BFF_Telco --> EventProc
    BFF_Gov --> Report
    BFF_Gov --> Notify[Notification Service]
    
    Case --> Orch[Inference Orchestrator]
    Bot --> Orch
    EventProc --> Orch
    Orch --> Entity
    Orch <-->|REST / gRPC| AI_Ext[AI Platform]
    
    Case --> Kafka{{Kafka}}
    Ev --> Kafka
    Report --> Kafka
    Orch --> Kafka
    EventProc --> Kafka
    
    Kafka --> Entity[Entity Graph Service]
    Kafka --> Search
    Kafka --> Notify[Notification Service]
    Kafka --> Geo[Geospatial Intelligence Service]
    Kafka --> Audit[Audit Service]
    BFF_Inv --> Geo
```

### 3.2 Control Plane vs. Data Plane
The architecture is explicitly divided into a **Control Plane** (managing platform operations, edge routing, and security) and a **Data Plane** (managing business logic, investigations, and inference).

```mermaid
flowchart TD
    %% External Actors
    Client_Citizen([Citizen App / Web])
    Client_LEO([Command Center / Investigators])
    Client_Bank([Bank Official Portal])
    Client_Telco([Telecom Admin Portal])
    Client_Gov([Gov / MHA Portal])
    
    subgraph Control Plane
        Gateway[Kong API Gateway]
        Router_Cit{Citizen API Route}
        Router_Inv{Investigator API Route}
        Router_Bank{Bank API Route}
        Router_Telco{Telecom API Route}
        Router_Gov{Gov API Route}
        Router_Event{Event Webhook Route}
        Router_Search{Search API Route}
        Svc_Auth[Identity Service]
        Svc_Config[Configuration Service]
        Svc_Audit[Audit Service]
        Observability[Observability Stack]
    end

    subgraph Data Plane
        BFF_Cit[Citizen BFF]
        BFF_Inv[Investigator BFF]
        BFF_Bank[Bank BFF]
        BFF_Telco[Telecom BFF]
        BFF_Gov[Gov BFF]
        Svc_Case[Case Management Service]
        Svc_Inference[Inference Orchestrator]
        Svc_Event[Event Processing Service]
        Svc_Entity[Entity Graph Service]
        Svc_Evidence[Evidence Management Service]
        Svc_Search[Investigation Search Service]
        Svc_Notify[Notification Service]
        Svc_Report[Reporting Service]
        Svc_Bot[Conversational Bot Service]
        Svc_Geo[Geospatial Intelligence Service]
    end

    %% External
    Ext_AI[AI Inference Platform]
    Kafka{{Apache Kafka Event Bus}}

    Client_Citizen --> Gateway
    Client_LEO --> Gateway
    Client_Bank --> Gateway
    Client_Telco --> Gateway
    Client_Gov --> Gateway
    
    Gateway --> Router_Cit
    Gateway --> Router_Inv
    Gateway --> Router_Bank
    Gateway --> Router_Telco
    Gateway --> Router_Gov
    Gateway --> Router_Event
    Gateway --> Router_Search
    Gateway --> Svc_Auth
    
    Router_Cit --> BFF_Cit
    Router_Inv --> BFF_Inv
    Router_Bank --> BFF_Bank
    Router_Telco --> BFF_Telco
    Router_Gov --> BFF_Gov
    Router_Event --> Svc_Event
    Router_Search --> Svc_Search
    
    BFF_Cit --> Svc_Case & Svc_Evidence & Svc_Bot
    BFF_Inv --> Svc_Case & Svc_Evidence & Svc_Search & Svc_Report & Svc_Geo & Svc_Entity
    BFF_Bank --> Svc_Event
    BFF_Telco --> Svc_Event
    BFF_Gov --> Svc_Report & Svc_Notify
    
    %% Event Publishing
    Svc_Auth & Svc_Case & Svc_Inference & Svc_Evidence & Svc_Event & Svc_Report & Svc_Geo -.->|Publishes Events| Kafka
    
    %% Event Consumption
    Kafka -.->|Consumes Events| Svc_Entity & Svc_Notify & Svc_Audit & Svc_Search & Svc_Report & Svc_Geo
```

---

## 4. Core Services Definition

The platform is decomposed into **15 core services**. To bridge naturally into the Low-Level Design (LLD), the API contracts and event flows are summarized below.

### 4.1 Edge & Aggregation Layers
1.  **API Gateway:**
    *   *Technology:* **Kong 3 (DB-less mode)**. Declarative YAML configuration in `/infra/kong/kong.yml` — no Kong database required.
    *   *Responsibilities:* Edge proxy, JWT validation (RS256), rate limiting (IP + token), correlation ID injection.
    *   *Plugins active (hackathon):* `jwt`, `rate-limiting`, `correlation-id`, `response-ratelimiting`.
    *   *Production extensions:* `request-id`, `opentelemetry` (traces routed via OTel Collector to Tempo).
2.  **BFFs (Citizen, Investigator, Bank, Telecom, Gov):**
    *   *Responsibilities:* Aggregates microservice data for UI consumption. Owned by Surjit (Citizen, Bank, Telecom) and Nilkanta (Investigator, Gov).

### 4.2 Control Plane Services
3.  **Identity Service:**
    *   *Provides:* `Login`, `Verify MFA`, `Manage RBAC`
    *   *Publishes:* `User.Registered`, `User.LoginFailed`
4.  **Configuration Service:**
    *   *Responsibilities:* Feature flags, env profiles, fusion weight management.
    *   *Hackathon implementation:* Redis keys (`fusion:weights`, `fusion:enabled_models`) serve this function directly — satisfying FR-14.4 (hot-reload without restart) without a separate service binary. Production Kubernetes deployment uses a dedicated Configuration Service backed by Vault and Redis.
5.  **Audit Service:**
    *   *Responsibilities:* Immutable ledger.
    *   *Consumes:* `*.Created`, `*.Updated` (All state changes)

### 4.3 Data Plane Services
6.  **Case Management Service:** 
    *   *Provides:* `Create Case`, `Update Case State`, `Assign Case`
    *   *Consumes:* `Prediction.Completed`, `Evidence.Verified`
    *   *Publishes:* `Case.Created`, `Case.Updated`, `Case.Assigned`
7.  **Inference Orchestrator Service:** 
    *   *Provides:* `Request Prediction`, `Get Prediction Status`
    *   *Consumes:* `Case.Created`, `Evidence.Uploaded`
    *   *Publishes:* `Prediction.Requested`, `Prediction.Completed`, `Prediction.Failed`
8.  **Event Processing Service:** 
    *   *Provides:* Ingestion webhooks for external async telemetry; synchronous gRPC streaming endpoint for the real-time interdiction path.
    *   *Publishes:* `TelecomEvent.Ingested`, `Transaction.Ingested`, `Intervention.Requested`
9.  **Entity Graph Service:** 
    *   *Provides:* `Query Linkages`, `Find Shortest Path`
    *   *Consumes:* `Case.Created`, `Prediction.Completed`
    *   *Publishes:* `Entity.RelationshipDiscovered`
10. **Evidence Management Service:** 
    *   *Provides:* `Upload Evidence`, `Generate Presigned URL`, `Verify Hash`
    *   *Consumes:* `Case.Closed` (Triggers archival lock)
    *   *Publishes:* `Evidence.Uploaded`, `Evidence.Deleted`
11. **Investigation Search Service:** 
    *   *Provides:* `Fuzzy Search`, `Faceted Filter`
    *   *Consumes:* `Case.*`, `Evidence.*`, `Prediction.*` (Builds eventually consistent read model)
12. **Notification Service:** 
    *   *Provides:* `Send Alert`, `Update Preferences`, `Dispatch MHA Alert`
    *   *Consumes:* `Prediction.Completed`, `Case.Assigned`, `CallSession.Flagged`
    *   *Publishes:* `Notification.Requested`, `Notification.Sent`, `MHAAlert.Sent`
    *   *Note:* The MHA alert channel is a high-priority, dedicated webhook path bypassing standard notification queues. Delivery latency SLO: < 5 seconds from `CallSession.Flagged`.
13. **Conversational Bot Service:**
    *   *Provides:* `Process Message`, `Get Session State`
    *   *Note:* Strictly proxies all NLP requests through the Inference Orchestrator to maintain a single, tightly controlled AI integration boundary.
14. **Reporting Service:** 
    *   *Provides:* `Generate NCRB Report`, `Export CSV`, `Generate Intelligence Package`
    *   *Consumes:* `Case.Closed`, `Audit.Recorded`
    *   *Publishes:* `Report.Generated`, `IntelligencePackage.Generated`
    *   *Note:* Intelligence Packages are cryptographically signed bundles (case records, evidence hashes, graph exports, AI audit trail, chain-of-custody logs) suitable for court submission.
15. **Geospatial Intelligence Service:**
    *   *Provides:* `Get Hotspot Map`, `Query Patrol Zones`, `Export GeoJSON Layer`, `Get Cross-District Density`
    *   *Consumes:* `Case.Created`, `CounterfeitScan.Submitted`, `Prediction.Completed`
    *   *Publishes:* `GeoLayer.Updated`
    *   *Note:* Geospatial data is stored in PostGIS. Hotspot layer updates must occur within 60 seconds of the triggering event. Cross-district queries are scoped to the requesting investigator's RBAC jurisdiction.

---

## 5. Data Architecture & CQRS

### 5.1 Domain Ownership Diagram
Each bounded context strictly owns its data.

```mermaid
flowchart TD
    subgraph Data Domains
        IdD[Identity Domain] --> IdS[Identity Service] --> IdDB[(PostgreSQL 16)]
        CaseD[Investigation Domain] --> CaseS[Case Service] --> CaseDB[(PostgreSQL 16)]
        GraphD[Entity Domain] --> GraphS[Entity Graph Service] --> GraphDB[(Neo4j 5 + APOC)]
        SearchD[Search Domain] --> SearchS[Search Service] --> SearchDB[(OpenSearch 2)]
        EvidD[Evidence Domain] --> EvidS[Evidence Service] --> EvidDB[(MinIO / S3)]
        ReportD[Reporting Domain] --> ReportS[Reporting Service] --> ReportDB[(PostgreSQL 16)]
        BotD[Bot Domain] --> BotS[Conversational Bot Service] --> BotDB[(Redis 7)]
        GeoD[Geospatial Domain] --> GeoS[Geospatial Service] --> GeoDB[(PostGIS 3.4 — dedicated container)]
        AuditD[Audit Domain] --> AuditS[Audit Service] --> AuditDB[(PostgreSQL 16)]
        OrchD[Inference Domain] --> OrchS[Inference Orchestrator] --> OrchDB[(PostgreSQL 16)]
    end
```

> **Data Store Notes:** PostGIS runs in its own dedicated container (`postgis/postgis:16-3.4`), separate from the primary PostgreSQL instance, to maintain strict Database-per-Service isolation. OpenSearch serves as the CQRS read model for case and evidence search. Each domain's PostgreSQL tables live in the primary instance under separate schemas.

### 5.2 Command Query Responsibility Segregation (CQRS) & Transactional Outbox
To optimize complex dashboards without joining across microservices, the architecture uses CQRS powered by the **Transactional Outbox Pattern**. State mutations (Commands) occur in PostgreSQL alongside an Outbox table. An outbox publisher relays these to Kafka, updating downstream read projections asynchronously.

```mermaid
flowchart LR
    WriteAPI[Write API / Command] --> Postgres[(PostgreSQL Write DB)]
    Postgres --> Outbox[(Outbox Table)]
    Outbox --> Publisher[Outbox Publisher]
    Publisher --> Kafka{{Kafka}}
    Kafka --> Projection[Search Projection Service]
    Projection --> OpenSearch[(OpenSearch Read DB)]
    ReadAPI[Read API / Query] --> OpenSearch
```

---

## 6. Event Streaming Architecture

### 6.1 Kafka Architecture Flow
All events are published as plain JSON. The platform uses Kafka KRaft mode (no Zookeeper) with **12 partitions per topic** for parallel consumer scaling. In production, a Confluent Schema Registry enforces backward and forward JSON Schema compatibility at the producer before reaching the broker.

Kafka runs in **KRaft mode** (Kafka 3.6+, `bitnamilegacy/kafka:3.6`). No Zookeeper.

```mermaid
flowchart LR
    Producer[Service Producer] --> Partition[Topic Partition]
    Partition --> Broker[Kafka Broker]
    Broker -->|Consumes| CG[Consumer Group]
    
    CG -->|Success| Commit[Commit Offset]
    CG -->|Failure| RetryTopic[Retry Topic]
    
    RetryTopic -->|Max Retries Exceeded| DLQ[Dead Letter Queue DLQ]
```

> **Hackathon:** Producers publish plain JSON directly to Kafka (no Schema Registry validation). In production, a Confluent Schema Registry step sits between producer and partition, enforcing backward/forward JSON Schema compatibility.

### 6.2 Standardized Event Naming
Naming consistency is strictly enforced across all domain boundaries using the `Noun.PastTenseVerb` convention:
*   `Case.Created`, `Case.Updated`, `Case.Assigned`, `Case.Closed`
*   `Evidence.Uploaded`, `Evidence.Deleted`
*   `Audio.Uploaded`, `Audio.Processed`
*   `Prediction.Requested`, `Prediction.Completed`, `Prediction.Failed`, `Prediction.Overridden`
*   `Entity.RelationshipDiscovered`
*   `CallSession.Initiated`, `CallSession.Flagged`
*   `Intervention.Requested`
*   `CounterfeitScan.Submitted`
*   `FraudRing.NodeIdentified`
*   `GeoLayer.Updated`
*   `Notification.Requested`, `Notification.Sent`, `Notification.Delivered`, `Notification.Failed`
*   `MHAAlert.Sent`
*   `IntelligencePackage.Generated`
*   `User.Registered`, `User.LoginFailed`
*   `Audit.Recorded`
*   `Report.Generated`

---

## 7. Request Flows & Architectural Patterns

### 7.1 API Lifecycle (Edge Routing)
```mermaid
flowchart LR
    Req[Incoming Request] --> Val[Request Validation]
    Val --> Auth[Authentication JWT]
    Auth --> RBAC[Authorization]
    RBAC --> Rate[Rate Limiting]
    Rate --> Corr[Generate Correlation ID]
    Corr --> Log[Request Logging]
    Log --> Route[Service Routing]
    Route --> Res[Response]
```

### 7.2 Failure Handling & Circuit Breaking
```mermaid
flowchart TD
    Req[AI Prediction Request] --> AI[AI Platform]
    AI -.->|Timeout / 503| Retry[Exponential Retry]
    Retry -.->|Failed Again| CB{Circuit Breaker Open?}
    CB -->|Yes| Fallback[Route to Manual Review Queue]
    CB -->|No| Retry
    Fallback --> Notify[Notify Investigator]
```

### 7.3 Sub-second Real-Time Scam Interdiction
To satisfy the < 300ms SLA for active scam intervention (before a financial transfer occurs), the platform provides a dedicated synchronous ingestion path that intentionally bypasses the async Kafka event bus. **Every interdiction decision is still written to the Audit Service asynchronously** (via Kafka's `Intervention.Requested` event) to satisfy the legal admissibility requirement.
```mermaid
flowchart LR
    Telco[Telecom Stream] -->|gRPC / WebSockets| Gateway[API Gateway]
    Gateway --> Interdict[Event Processing Service]
    Interdict --> Orch[Inference Orchestrator]
    Orch --> AI[AI Platform]
    AI --> Orch
    Orch --> Interdict
    Interdict -->|Immediate Block| Bank[Banking Core]
    Interdict -.->|Async: Intervention.Requested| Kafka{{Kafka}}
    Kafka -.->|Consume| Audit[Audit Service]
```

### 7.4 Edge Inference & Offline Sync Strategy
To support offline counterfeit detection on mobile devices and bank counting machines, the platform syncs quantized ML models directly to the edge. The system tolerates model version skew. Because offline scan logs are potentially evidentiary, **conflict resolution defaults to flagging near-duplicates for manual investigator review** rather than silently discarding one record (Last-Write-Wins is only used for non-evidentiary telemetry).
```mermaid
flowchart TD
    Cloud[Platform Core] -->|Periodic Model Sync| Edge[Edge Device / POS]
    Edge --> |Offline Scan| LocalDB[(Local SQLite)]
    Edge --> |Offline Inference| QuantizedAI[Quantized Edge Model]
    Edge -.->|Reconnection: Upload Logs| Cloud
    Cloud --> Conflict{Duplicate / Conflict?}
    Conflict -->|Evidentiary Scan| ManualReview[Flag for Investigator Review]
    Conflict -->|Non-Evidentiary Telemetry| LWW[Last-Write-Wins → PostgreSQL]
```

### 7.5 Human-in-the-Loop Override Flow
When the Inference Orchestrator generates a fused verdict below the configured confidence threshold, automated high-impact actions are suppressed and the case is routed to a manual review queue. All investigator override decisions are written to the Audit Service as immutable records.
```mermaid
flowchart TD
    FusedVerdict[Fused AI Verdict] --> ConfCheck{Confidence >= Threshold?}
    ConfCheck -->|Yes| AutoExec[Execute Automated Action]
    ConfCheck -->|No| ManualQ[Route to Manual Review Queue]
    ManualQ --> NotifyInv[Notify Investigator via SSE]
    NotifyInv --> InvDecision{Investigator Decision}
    InvDecision -->|Approve AI Verdict| AutoExec
    InvDecision -->|Override / Reject| OverrideRecord[Persist Immutable Override Record]
    AutoExec --> AuditKafka{{Publish to Audit Service via Kafka}}
    OverrideRecord --> AuditKafka
```

### 7.6 Multi-Source Inference Fusion Flow
The Inference Orchestrator dispatches parallel invocations to each applicable AI endpoint. A Fusion Layer aggregates results into a single composite verdict. Partial failures do not block persistence — they produce an `INCOMPLETE` verdict routed for manual review.
```mermaid
flowchart TD
    Trigger[Investigation Trigger] --> Orch[Inference Orchestrator]
    Orch -->|Fetch 2-Hop Anchor| Graph[Entity Graph Service]
    Graph -->|Return Sub-Graph| Orch
    Orch -->|Parallel| Vision[Vision AI Endpoint]
    Orch -->|Parallel| NLP_Audio[NLP / Audio AI Endpoint]
    Orch -->|Parallel| Graph_AI[Graph AI Endpoint]
    Vision & NLP_Audio & Graph_AI -->|Results + Confidence Scores| Fusion[Fusion Layer]
    Fusion --> Complete{All Models Responded?}
    Complete -->|Yes| FusedRecord[Persist Complete Fused Verdict]
    Complete -->|Partial Failure| IncRecord["Persist INCOMPLETE Verdict (flagged)"]
    FusedRecord --> KafkaComplete{{Prediction.Completed → Kafka}}
    IncRecord --> ManualQ[Manual Review Queue]
    IncRecord --> KafkaIncomplete{{Prediction.Completed INCOMPLETE → Kafka}}
```

---

## 8. State & Sequence Diagrams

### 8.1 Case State Machine
```mermaid
stateDiagram-v2
    [*] --> New
    New --> Assigned
    Assigned --> Investigating
    Investigating --> Pending_AI
    Pending_AI --> Investigating
    Investigating --> Action_Taken
    Action_Taken --> Closed
    Closed --> [*]
```

### 8.2 Sequence: Complaint Submission
```mermaid
sequenceDiagram
    actor Citizen
    participant API as API Gateway
    participant BFF as Citizen BFF
    participant Case as Case Service
    participant Outbox as DB + Outbox
    participant Kafka as Kafka Bus
    participant Audit as Audit Service

    Citizen->>API: POST /api/v1/complaints (JWT)
    API->>BFF: Route Request
    BFF->>Case: Create Case (HTTP/REST)
    Case->>Outbox: Persist Transaction + Event
    Outbox-->>Case: Success
    Case-->>BFF: Case ID
    BFF-->>Citizen: 201 Created
    
    Outbox-)Kafka: Publish Case.Created
    Kafka-)Audit: Consume & Append Log
```

### 8.3 Sequence: AI Prediction & Investigation
```mermaid
sequenceDiagram
    participant Case as Case Service
    participant Orch as AI Orchestrator
    participant Graph as Entity Graph Service
    participant Queue as Internal Durable Queue
    participant AI as AI Platform
    participant Kafka as Kafka Bus
    
    Case->>Orch: Request AI Analysis (Async)
    Orch->>Graph: GET /graph/linkages (Fetch Anchor Sub-Graph)
    Graph-->>Orch: Return 2-Hop JSON Neighborhood
    Orch->>Queue: Push Unified Payload (Not Kafka)
    Queue->>AI: Trigger Inference
    AI-->>Orch: Return Risk Score
    Orch->>Orch: Persist Prediction Details
    Orch-)Kafka: Publish Prediction.Completed
    Kafka-)Case: Update Case State (Action_Taken)
```

---

## 9. Cross-Cutting Concerns

*   **Authentication & Authorization:** JWT validation and initial RBAC evaluation are offloaded to the API Gateway. Services only perform fine-grained resource authorization.
*   **Caching:** Implemented via the **Cache-Aside Pattern** using Redis to reduce DB load. Eviction policies: TTL-based for sessions/OTPs; LRU/LFU for cached read models.
*   **Logging & Tracing:** Structured JSON logs are emitted by all services. OpenTelemetry automatically propagates `trace_id` headers.
*   **Rate Limiting:** Enforced globally at the API Gateway (IP + token-based per FR-2.5), and locally at the service mesh layer for inter-service RPCs.
*   **Feature Flags & Secrets:** Configuration Service manages feature flags and fusion weights via Redis keys (hot-reload, FR-14.4). Secrets are read from `.env` in the hackathon demo; production uses HashiCorp Vault with Vault Agent sidecar injection.

---

## 10. External Dependencies

```mermaid
flowchart TD
    subgraph Platform
        Notify[Notification Service]
        Ingest[Event Processing]
        AI_Orch[Inference Orchestrator]
        Geo_Svc[Geospatial Intelligence Service]
        Report[Reporting Service]
        Auth[Identity Service]
        Bot[Conversational Bot Service]
    end

    subgraph External Systems
        Notify --> SMS[SMS Provider]
        Notify --> Email[Email Provider]
        Notify --> Push[Push Notification APIs]
        Notify -->|MHA Alert| MHA[MHA / Law Enforcement Webhook]
        
        Telco[Telecom / ISP APIs] --> Ingest
        Banks[Banking Core APIs] <--> Ingest
        Gov[Government NCRB APIs] <--> Report
        GovIdP[Government KYC/IdP APIs] --> Auth
        Geo_Svc --> Mapping[Geospatial / Mapping APIs]
        WhatsApp[WhatsApp / Omnichannel APIs] <--> Bot
        
        AI_Orch <--> AI_Ext[External AI Platform]
    end
```

---

## 11. Observability Stack

All services emit **structured JSON logs** via `loguru` (Python). The OpenTelemetry SDK (`opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`) auto-instruments every FastAPI service — traces propagated via W3C Trace Context headers. Every service exposes:
- `GET /health` → `{status, version, uptime_s}` — polled by Kong upstream health checks and the Inference Orchestrator for ML service readiness.
- `GET /metrics` → Prometheus text format — auto-generated by `prometheus-fastapi-instrumentator`.

```mermaid
flowchart LR
    Services[Microservices] -->|OTLP traces direct| Tempo[Tempo]
    Services -->|Metrics /metrics| Prom[Prometheus]
    Services -->|Structured JSON logs| Loki[Loki]
    
    Tempo & Prom & Loki --> Grafana[Grafana Dashboards]
    Grafana --> Alert[SLI / SLO Alerts]
```

> **Hackathon simplification:** Services send OTLP traces directly to Tempo (port 4317) and push logs directly to Loki's HTTP API. In production, an OpenTelemetry Collector routes traces/logs from all services to the appropriate backends, and Promtail scrapes container logs. Both production components remain in the architecture diagram for judges.

---

## 12. Platform Operations

The platform requires robust DevOps practices to maintain the 99.99% availability SLA:
*   **Rolling Updates & Deployments:** Zero-downtime rolling updates. High-risk services utilize Canary or Blue-Green deployments.
*   **Kubernetes Constraints:** All workloads define strict Resource Requests/Limits, Pod Disruption Budgets (PDBs), and Affinity Rules to guarantee node distribution.
*   **Autoscaling:** Kubernetes HPA triggers dynamically based on Prometheus metrics.
*   **Backup & Restore:** Automated daily snapshots (Postgres/Neo4j) with strictly **intra-country** cross-region replication to comply with DPDP Act data residency requirements. Includes periodic restore verification drills and strict backup encryption.
*   **Certificate Rotation:** Automated via `cert-manager` within Kubernetes; `cert-manager` is a critical-path operational dependency (not optional tooling) given the mandatory mTLS enforcement.
*   **Chaos Testing:** Periodic failure injection (e.g., random pod termination, Kafka broker restart) is executed in staging environments to validate resilience patterns (circuit breakers, DLQs), satisfying the Reliability Acceptance Criterion (SRS §19).

---

## 13. Deployment View

The platform is designed to run on a container orchestration system (Kubernetes), organized into strict network layers. A **Mandatory Service Mesh (Istio 1.21 with sidecar injection)** enforces zero-trust mTLS between all services, handles traffic routing policies, circuit breaking, and retry logic.

*Note: mTLS handshake overhead is factored into the 1.5s API SLA. `cert-manager` is a critical-path operational dependency that automates certificate rotation for all Istio-managed services.*

**Local Docker Compose equivalent:** Kong handles TLS termination at the gateway layer. All inter-service communication is plain HTTP within the isolated Docker bridge network (`172.20.0.0/16`). Production Kubernetes uses Istio mTLS for full zero-trust enforcement.

```mermaid
flowchart TD
    Internet[Internet] --> WAF[Web Application Firewall]
    WAF --> ALB[Load Balancer]
    ALB --> Gateway[API Gateway]
    
    subgraph Kubernetes Cluster
        Gateway --> Ingress[K8s Ingress Controller]
        Ingress --> Mesh[Mandatory Service Mesh / Istio]
        
        subgraph K8s Control Plane
            API_Server[API Server]
            Scheduler[Scheduler]
            Controller[Controller Manager]
        end
        
        subgraph Worker Node 1
            Pod_Cit[Citizen BFF Deployment]
            Pod_Case[Case Service Deployment]
            Pod_Bot[Conversational Bot Deployment]
            Pod_Auth[Identity Service Deployment]
            Pod_Evidence[Evidence Service Deployment]
        end
        
        subgraph Worker Node 2
            Pod_Inv[Investigator BFF Deployment]
            Pod_Gov[Gov BFF Deployment]
            Pod_Orch[Inference Orch Deployment]
            Pod_Report[Reporting Service Deployment]
            Pod_Entity[Entity Graph Service Deployment]
            Pod_Geo[Geospatial Service Deployment]
        end
        
        subgraph Worker Node 3
            Pod_Search[Search Service Deployment]
            Pod_Event[Event Service Deployment]
            Pod_Bank[Bank BFF Deployment]
            Pod_Telco[Telecom BFF Deployment]
            Pod_Audit[Audit Service Deployment]
            Pod_Notify[Notification Service Deployment]
        end
        
        Mesh --> Pod_Cit & Pod_Inv & Pod_Search & Pod_Case & Pod_Orch & Pod_Event & Pod_Bot & Pod_Report & Pod_Gov & Pod_Bank & Pod_Telco & Pod_Auth & Pod_Evidence & Pod_Entity & Pod_Geo & Pod_Audit & Pod_Notify
    end

    subgraph Data Layer [Isolated Subnet]
        Postgres[(PostgreSQL StatefulSet)]
        PostGIS[(PostGIS StatefulSet)]
        Neo4j[(Neo4j StatefulSet)]
        OpenSearch[(OpenSearch StatefulSet)]
        Kafka{{Kafka StatefulSet}}
        Redis[(Redis StatefulSet)]
        MinIO[(MinIO / S3 StatefulSet)]
    end

    Worker Node 1 & Worker Node 2 & Worker Node 3 --> Data Layer
```
