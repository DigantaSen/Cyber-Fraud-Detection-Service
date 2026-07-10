# Execution Roadmap — AI for Digital Public Safety
**Team Size:** 4 | **Duration:** 12 Days (Sat, Jul 11 -> Wed, Jul 22, 2026)
**Scope:** Full System — 15 Services per HLD | Citizen Fraud Shield · Case Management · Inference Fusion · Geospatial · Graph Intelligence · Evidence · Reporting · HITL · Real-Time Interdiction

**Team Roles (fixed):**
- **Diganta — Infrastructure, Design & Platform Lead:** Repo/Docker/CI/deployment, LLD, all API contracts, DB schemas, sequence diagrams. Owns: Inference Orchestrator, Event Processing backbone, Audit Service, real-time interdiction path, all integration work. No feature UI coding.
- **Surjit — Citizen Vertical Slice:** Auth/Identity Service -> Case Service -> Conversational Bot Service -> Citizen UI + Bot interface, end to end.
- **Nilkanta — Investigator Vertical Slice:** Evidence Service -> Geospatial Intelligence Service -> Entity Graph Service -> Notification Service (with MHA) -> Reporting Service -> Investigator Dashboard UI, end to end.
- **Kushal — ML Pipeline (4 Models + Fusion + Edge):** Scam NLP classifier, Counterfeit CV detector, Fraud Graph analyzer, Audio voice analyzer, Explainability, Quantized edge model. No UI/backend/infra/design work.

**Design principle:** Diganta owns the two hardest cross-cutting concerns (infra + platform core) so Surjit and Nilkanta build against a solid, contract-driven foundation. Surjit and Nilkanta own full vertical slices so they never block each other. Kushal is fully decoupled until integration day; the only hard dependency is that all ML API stubs match the contract Diganta defines on Day 1.

---

## Tech Stack (Production Grade — Frozen at Day 1 Sign-off)

| Layer | Technology | Notes |
|---|---|---|
| **Backend framework (all services)** | **FastAPI (Python 3.12)** | Unified across all 4 members. Async-native, OpenAPI auto-generated, best ML ecosystem fit. |
| **ML services (Kushal)** | **FastAPI (Python 3.12)** | Same as system services — zero integration friction. |
| **Frontend** | **React 18 + Vite** | Fast build, React Query for data fetching, Zustand for state. |
| **Primary DB** | **PostgreSQL 16** | ACID, JSONB, `tsvector` full-text search, triggers for outbox automation. |
| **Geospatial DB** | **PostGIS 3.4** (separate container, `postgis/postgis:16-3.4`) | ST_Within, ST_MakeEnvelope, ST_AsGeoJSON for hotspot queries. |
| **Graph DB** | **Neo4j 5 Community** (APOC plugin) | Cypher queries, `shortestPath()`, Louvain community detection via APOC. |
| **Cache / sessions** | **Redis 7 Cluster** | Session store, OTP cache, JWT denylist, live fusion weight config keys. Cluster mode for 1M+ sessions. |
| **Connection pooling** | **PgBouncer 1.22** (transaction-mode) | Sits in front of PostgreSQL. Limits actual DB connections to 100 regardless of service replicas. Critical at 1M+ users. |
| **Search / read model** | **OpenSearch 2** | CQRS read model for case search + faceted filtering. Kafka consumer indexes Case/Evidence events. 3-shard, 1-replica index config for horizontal growth. |
| **Object storage** | **MinIO** (S3-compatible) | Presigned URLs for direct browser upload. Swap to S3 in cloud deploy. |
| **Event bus** | **Kafka 3.6 KRaft mode** | No Zookeeper. `confluentinc/confluent-local:7.6` image. **12 partitions per topic** for parallel consumer scaling to 12 pods. |
| **Schema Registry** | **Confluent Schema Registry 7.6** | JSON Schema validation for all Kafka events. Enforces backward/forward compatibility at publish time. |
| **API gateway** | **Kong 3 (DB-less mode)** | Declarative YAML config — no Kong database needed. Plugins: JWT validation, rate-limit, request-id, correlation-id, OpenTelemetry. **Rate limit:** 1000 req/min per token, 100 req/min per IP for unauthenticated routes. |
| **Service mesh** | **Istio 1.21 (sidecar injection)** | mTLS between all services in Kubernetes. Docker Compose local dev uses Kong + TLS certs via `mkcert` as equivalent. |
| **Observability — metrics** | **Prometheus 2 + Grafana 10** | `prometheus-fastapi-instrumentator` auto-instruments all FastAPI services. |
| **Observability — logs** | **Loki + Promtail (Grafana stack)** | Structured JSON logs via `loguru` collected by Promtail, queried in Grafana. |
| **Observability — traces** | **Tempo + OpenTelemetry Collector** | `opentelemetry-sdk` auto-instruments FastAPI. Traces viewable in Grafana (linked to logs via trace_id). |
| **Secrets** | **HashiCorp Vault (dev mode locally, prod mode on deploy)** | All service secrets injected at startup via Vault Agent. `.env` only used for Vault address + role. |
| **BFF layer** | **Thin FastAPI gateway per audience** | Citizen BFF (owned by Surjit) + Investigator BFF (owned by Nilkanta) aggregate downstream calls. Clients talk to one BFF, not individual microservices. |

> **Scalability contract:** All FastAPI services are **stateless** and scale horizontally. All state lives in PostgreSQL (via PgBouncer), Redis Cluster, Neo4j, PostGIS, OpenSearch, or Kafka. Adding pods never requires migration — only Kafka consumer group rebalancing, which Kafka handles automatically.

> **Why FastAPI for all services:** Single language across all 4 team members eliminates context-switching during T13 integration and T16 E2E debugging. Python's ML ecosystem (httpx, asyncio, SQLAlchemy 2, neo4j driver, asyncpg, minio-py) has first-class support for every data store in this stack. FastAPI generates OpenAPI specs automatically — those specs ARE the api-contract files in `/docs/`.

---

## 1. Complete Project Breakdown

### Phase A — Design & Foundation (Day 1, Diganta-led)
**Module A1:** Monorepo, production docker-compose with all data stores (PostgreSQL + PgBouncer, PostGIS, Neo4j, Redis Cluster, Kafka KRaft + Schema Registry, MinIO, OpenSearch, Kong, Vault, Prometheus + Grafana + Loki + Tempo + OTel Collector), environment config, CI skeleton
**Module A2:** API contracts for all 15 services (endpoint-by-endpoint spec), DB schemas (DDL-level for all stores), sequence diagrams for 6 core flows
**Module A3:** All 4 members review and approve before any feature coding begins

### Phase B — Core Build (Day 2-6)
**Module B1 (Surjit):** Auth -> Case Service -> Conversational Bot stub -> Citizen UI + Bot interface
**Module B2 (Nilkanta):** Evidence Service -> Geospatial Service -> Entity Graph Service -> Notification (with MHA) -> Reporting Service -> Investigator Dashboard
**Module B3 (Diganta):** Event Processing backbone -> Inference Orchestrator -> Audit Service
**Module B4 (Kushal):** Data prep -> 4 AI model stubs -> tuning -> explainability -> edge model

### Phase C — Integration (Day 6-8, Diganta-led)
**Module C1:** Multi-source ML fusion integration (Orchestrator <-> all 4 ML APIs)
**Module C2:** HITL override integration (low-confidence routing, approval gate)
**Module C3:** Real-time interdiction path (<300ms SLA, bypasses Kafka)
**Module C4:** MHA alert integration (dedicated webhook channel)
**Module C5:** Surjit<->Nilkanta cross-wiring + full E2E verification

### Phase D — Testing & Hardening (Day 9-10)
**Module D1:** Unit / API / Integration / System testing
**Module D2:** Bug fixing, polish, performance validation

### Phase E — Delivery (Day 10-12)
**Module E1:** Deployment (Diganta)
**Module E2:** Demo video, full-vision architecture diagram, pitch deck
**Module E3:** Rehearsal & final checklist

---

## 2. Dependency-Based Planning

> Format: Purpose | Depends On | Unlocks | Deliverable | Effort | Owner

---

### T1 — Repo & Production Docker Compose
- **Purpose:** Give every member a fully production-equivalent local environment from Day 1. No simplified substitutes.
- **Depends On:** Nothing. [CRITICAL PATH START]
- **Deliverable:** `docker-compose.yml` with the following production-grade services:
  - `postgres:16-alpine` — primary relational store. **Connection pooling via `pgbouncer` (transaction mode, max 100 PostgreSQL connections — absorbs horizontal service scaling without exhausting DB connection slots)**
  - `pgbouncer:1.22` — connection pooler in front of PostgreSQL. Services connect to PgBouncer on port 5432; PgBouncer talks to Postgres on 5433. Config: `pool_mode=transaction`, `max_client_conn=1000`, `default_pool_size=100`.
  - `postgis/postgis:16-3.4` — dedicated geospatial store (separate container, separate DB), `CREATE EXTENSION postgis` on init
  - `neo4j:5-community` with `NEO4JPLUGINS=apoc` — entity graph store
  - `redis:7-alpine` — session cache, OTP, JWT denylist, fusion weight config. **In production Kubernetes: Redis Cluster (3 primary + 3 replica shards) handles 1M+ sessions without single-point memory limit.**
  - `opensearch:2` + `opensearch-dashboards:2` — CQRS search read model, faceted case search. **Index config: 3 primary shards, 1 replica shard. Supports linear horizontal growth.**
  - `confluentinc/confluent-local:7.6` — Kafka 3.6 in KRaft mode (no Zookeeper). **All topics provisioned with 12 partitions — allows up to 12 parallel consumer pods per consumer group.**
  - `confluentinc/cp-schema-registry:7.6` — JSON Schema Registry, linked to Kafka
  - `minio/minio` — S3-compatible object store with `mc` init container to create buckets
  - `kong:3-alpine` in DB-less mode — API gateway with `kong.yml` declarative config
  - `vault:1.16` in dev mode — secrets store, all service secrets read from Vault at startup
  - `prom/prometheus:v2.52` — metrics scrape from all FastAPI services
  - `grafana/grafana:10.4` — dashboards (pre-seeded data sources: Prometheus, Loki, Tempo)
  - `grafana/loki:3.0` + `grafana/promtail:3.0` — log aggregation
  - `grafana/tempo:2.4` — distributed tracing backend
  - `otel/opentelemetry-collector-contrib:0.100.0` — receives OTLP from all services, routes to Tempo + Loki
  - `mkcert` init container — generates local TLS certs for Kong HTTPS and inter-service mTLS simulation
  - `clamav/clamav:1.3` — malware scanning for Evidence Service. `freshclam` runs on startup to update virus definitions. Evidence Service connects via TCP socket on port 3310.
  - Health checks on all containers. Startup order enforced via `depends_on: condition: service_healthy`.
  - Folder structure: `/backend/{auth,case,evidence,notification,reporting,geospatial,graph,bot,citizen-bff,investigator-bff,inference-orchestrator,audit,event-processing,search}`, `/frontend/{citizen,investigator}`, `/ml/{scam-nlp,counterfeit-cv,graph-analyzer,audio-analyzer,edge}`, `/infra/{docker,kong,vault,prometheus,grafana,loki,otel,pgbouncer}`, `/docs`. README with `make up` one-liner (Makefile wrapping compose commands).
- **Effort:** 7h | **Owner:** Diganta

### T2 — LLD: API Contracts (All 15+ Services)
- **Purpose:** Lets Surjit, Nilkanta, and Kushal build in parallel without guessing or conflicting.
- **Depends On:** T1. **Unlocks:** All Phase B tasks.
- **Deliverable:** Endpoint-by-endpoint spec: exact routes (versioned under `/api/v1/`), methods, request/response JSON (field names, types, required/optional, constraints), HTTP status codes, standard error envelope with `requestId/correlationId/errorCode/message/details`, idempotency key requirements on all mutating endpoints, rate-limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`).
  - **Cursor-based pagination on all list endpoints:** `?cursor=<opaque_base64>&limit=<n>` returning `{items[], nextCursor, hasMore, total}`. Cursor encodes `(created_at, id)` for stable ordering under concurrent inserts. Must include in: `/cases`, `/evidence`, `/audit/case/:id`, `/graph/linkages`, `/reports`.
  - **Health endpoints on every service:** `GET /health/live` (liveness — is the process running?), `GET /health/ready` (readiness — can it serve traffic? checks DB connection, Kafka connection, Redis connection), `GET /metrics` (Prometheus). Kubernetes probes use `/health/live` and `/health/ready` separately.
  - **Circuit breaker headers:** On 503, response includes `Retry-After: <seconds>` so callers back off correctly.
  - Files: auth.md, case.md, evidence.md, notification.md, reporting.md, geospatial.md, graph.md, bot.md, citizen-bff.md, investigator-bff.md, inference-orchestrator.md, search.md, audit.md, event-processing.md, ml-contract.md (all 4 AI model APIs + fusion contract).
- **Effort:** 7h | **Owner:** Diganta — [BLOCKING, must finish Day 1]

### T3 — LLD: DB Schema (All Data Stores)
- **Purpose:** DDL-precise enough that Surjit and Nilkanta write migrations without follow-up questions.
- **Depends On:** T1, T2. **Unlocks:** T4, T5a, T6a, T8, T8c, T8d.
- **Deliverable:** PostgreSQL DDL (User, Role, Session, Case, CaseTimeline, Evidence, EvidenceHash, Notification, MHAAlert, Prediction, FusedVerdict, OverrideRecord, Report, IntelligencePackage, AuditLog, Outbox). **Include `pg_bouncer` compatible DDL (no session-level variables, no advisory locks in hot paths).** Neo4j schema with property uniqueness constraints and indexes. PostGIS schema. Redis key conventions with TTL policies. **Kafka topic manifest: 12 partitions per topic, `replication.factor=3` (target prod), retention by topic type (Case topics: 7 days, Audit: 30 days, Prediction: 14 days).** OpenSearch index mappings: `case_index` (3 shards, 1 replica, dynamic=false, explicit types for all 20+ fields), `evidence_index`. ER diagram.
- **Effort:** 4h | **Owner:** Diganta

### T3b — LLD: Sequence Diagrams (6 Core Flows)
- **Purpose:** Remove who-calls-whom ambiguity before integration.
- **Depends On:** T2, T3. **Unlocks:** T13, T13b, T13c, T15, T16.
- **Deliverable:** (1) Citizen report -> multi-source ML fusion -> HITL gate -> case created. (2) Evidence upload -> hash verification -> intelligence package. (3) Telecom stream -> <300ms interdiction -> MHA alert. (4) Offline counterfeit scan -> sync -> conflict resolution. (5) Case created -> geospatial layer update -> dashboard push. (6) Investigator override -> immutable record -> audit trail.
- **Effort:** 3h | **Owner:** Diganta

### T3c — Design Sign-off
- **Purpose:** Catch disagreements before code exists. [SYNC POINT #0 — Day 1 EOD, all 4]
- **Depends On:** T2, T3, T3b. **Unlocks:** All Phase B tasks.
- **Deliverable:** Signed-off /docs/ — frozen. Post-freeze changes require team-wide flag.
- **Effort:** 1h | **Owner:** Diganta facilitates, all 4 attend

---

### T4 — Auth / Identity Service
- **Purpose:** User context needed by every feature. | **Depends On:** T3c. **Unlocks:** T4b, T5a, T6c.
- **Deliverable:** POST /auth/login, /auth/register, /auth/refresh, /auth/mfa/verify. JWT (RS256), RBAC claims in token (role, orgId, jurisdictionId). JWT denylist in Redis. TOTP MFA via `pyotp`. Reads secrets from Vault via `hvac`.
- **Effort:** 4h | **Owner:** Surjit

### T4b — Citizen BFF
- **Purpose:** Single entry point for the Citizen UI — aggregates Case Service + Bot + Orchestrator stub. Shields frontend from service topology changes. | **Depends On:** T4, T5a. **Unlocks:** T5c, T16.
- **Deliverable:** FastAPI gateway service at `/api/v1/citizen/`. Proxies and aggregates: `POST /citizen/report` → Case Service + queues Orchestrator call. `POST /citizen/bot/message` → Bot Service. `GET /citizen/cases/:id` → Case Service + Prediction status. Injects `correlationId` and `X-User-Context` into every downstream call. Rate limit: 60 req/min per user (configured in Kong). **Stateless — scales independently from all downstream services.**
- **Effort:** 4h | **Owner:** Surjit

### T5a — Case Service
- **Purpose:** Core domain — every flow anchors to a Case. | **Depends On:** T4, T3c. **Unlocks:** T5c, T13, T13b.
- **Deliverable:** POST /cases, GET /cases/:id, PATCH /cases/:id/state, PATCH /cases/:id/verdict/override, GET /cases/:id/timeline (cursor-paginated). State machine enforced: `New→Assigned→Investigating→Pending_AI→Action_Taken→Closed`. **Additional valid transition: `Pending_AI→Investigating` — triggered by the Orchestrator calling PATCH /cases/:id/state with `{state: 'Investigating', reason: 'AI_TIMEOUT'}` when a prediction returns INCOMPLETE status (FR-7.1).** Outbox pattern for Case.Created, Case.Updated. Mocks ML verdict until T13. **asyncpg connection pool size: min=5, max=20 per pod replica.**
- **Effort:** 2 days | **Owner:** Surjit — [CRITICAL PATH]

### T5b — Conversational Bot Service
- **Purpose:** Multi-channel citizen risk assessment. | **Depends On:** T5a, T3c. **Unlocks:** T5c.
- **Deliverable:** POST /bot/message, GET /bot/session/:id. Multi-turn session state in Redis (TTL 30m). Proxies NLP through Inference Orchestrator (stub until T13). **Supports 12 Indian regional languages (language detection via `langdetect`; language tag forwarded in the Orchestrator request so Kushal's NLP model returns language-appropriate response — FR-11.1).** Session key pattern: `bot:session:{sessionId}:lang={lang_code}`.
- **Effort:** 1.5 days | **Owner:** Surjit

### T5c — Citizen UI + Bot Interface
- **Purpose:** Citizen-facing frontend. | **Depends On:** T5a, T5b. **Unlocks:** T16.
- **Deliverable:** Report submission form (POST /cases), risk verdict display with confidence + explanation + HITL status, bot chat widget (POST /bot/message).
- **Effort:** 2 days | **Owner:** Surjit

---

### T6a — Evidence Service
- **Purpose:** Secure upload with cryptographic integrity. | **Depends On:** T3c. **Unlocks:** T6b, T16.
- **Deliverable:** POST /cases/:id/evidence (returns MinIO presigned PUT URL — client uploads directly, bypassing the API server), POST /evidence/:id/confirm (client confirms upload; service validates MIME, runs SHA-256), GET /evidence/:id, GET /evidence/:id/hash. SHA-256 hash stored (FR-8.3). MIME validation: image/png, image/jpeg, application/pdf, audio/wav, audio/mpeg, audio/m4a (FR-3.5). **Malware scanning (FR-3.4): after MinIO upload confirmed, stream file bytes through ClamAV (`python-clamd` via TCP socket to `clamav` Docker container) — reject evidence with 422 + `{errorCode: MALWARE_DETECTED}` if scan fails.** Publishes Evidence.Uploaded via outbox.
- **Effort:** 2 days | **Owner:** Nilkanta

### T6b — Reporting Service + Intelligence Package
- **Purpose:** NCRB reports and court-admissible intelligence packages. | **Depends On:** T6a, T3c. **Unlocks:** T16.
- **Deliverable:** POST /reports/ncrb, POST /reports/intelligence-package, GET /reports/:id. Intelligence package is a cryptographically signed bundle: case record + evidence hashes + Neo4j graph export + AI audit trail + chain-of-custody log. **Signing mechanism (FR-8.5): compute SHA-256 of the canonical JSON bundle, then sign the digest using the RS256 private key from Vault (`hvac` client). Return `{packageId, signatureAlgorithm: 'RS256', signature: base64, publicKeyFingerprint}` so any recipient can independently verify integrity with the platform's public key.** Publishes Report.Generated, IntelligencePackage.Generated.
- **Effort:** 1.5 days | **Owner:** Nilkanta

### T6c — Investigator Dashboard UI
- **Purpose:** Full investigator interface — case queue, graph viz, geo heatmap, HITL panel. | **Depends On:** T6a, T6b, T8c, T8d, T3c. **Unlocks:** T16.
- **Deliverable:** Case list (SSE real-time updates), case detail (AI verdict, confidence, model breakdown, HITL panel with approve/reject + mandatory justification), entity graph visualization, geospatial heatmap, intelligence package button.
- **Effort:** 2.5 days | **Owner:** Nilkanta

### T6d — Investigator BFF
- **Purpose:** Single entry point for the Investigator UI — aggregates Case, Evidence, Graph, Geo, Search, Reporting. | **Depends On:** T4, T6a, T8c, T8d. **Unlocks:** T6c, T16.
- **Deliverable:** FastAPI gateway at `/api/v1/investigator/`. Aggregates: `GET /investigator/cases` → Search Service (OpenSearch). `GET /investigator/cases/:id` → Case + FusedVerdict + Evidence list + Graph linkages (parallel with `asyncio.gather`). `POST /investigator/cases/:id/override` → Case Service. `GET /investigator/cases/:id/geo` → Geospatial Service. Injects `correlationId` + RBAC `jurisdictionId` scope into every downstream call. **Stateless — the aggregation fan-out using `asyncio.gather` ensures that adding more data sources only adds parallelism, not latency.**
- **Effort:** 4h | **Owner:** Nilkanta

---

### T7 — Audit Service
- **Purpose:** Immutable ledger — legal admissibility (NFR-6.1). | **Depends On:** T3c, T8b. **Unlocks:** T16, T6b.
- **Deliverable:** Kafka consumer on all state-change events. Append-only PostgreSQL audit_log (no UPDATE/DELETE). GET /audit/case/:id.
- **Effort:** 1 day | **Owner:** Diganta

### T8 — Inference Orchestrator Service
- **Purpose:** Parallel multi-source AI dispatch, fusion, HITL routing. Most architecturally complex service.
- **Depends On:** T3c, T8b. **Unlocks:** T13, T5b, T13b.
- **Deliverable:** POST /inference/analyze — parallel fan-out to all enabled ML APIs (configurable via feature flags), applies fusion weights, returns {fusedScore, riskTier, confidence, modelBreakdown[], explanation, status: COMPLETE|INCOMPLETE|PENDING_REVIEW}. Per-model timeout 2s. Low-confidence -> suppresses automated actions. Partial failure -> INCOMPLETE verdict. Persists explainability metadata. Publishes Prediction.Requested, Prediction.Completed, Prediction.Failed.
- **Effort:** 2 days | **Owner:** Diganta — [CRITICAL PATH]

### T8b — Event Processing Service + Kafka Backbone
- **Purpose:** Async nervous system. Must be live before any service publishes events.
- **Depends On:** T1, T3c. **Unlocks:** T7, T8, T8c, T8d, T8e, T8f.
- **Deliverable:**
  - **Kafka topics provisioned:** All topics from T3 schema — **12 partitions per topic**, retention by type. Script in `/infra/kafka/provision-topics.sh`.
  - **Schema Registry:** All Kafka event schemas registered as JSON Schema. Each service's Kafka producer validates against the schema before publishing — schema-invalid messages rejected at publish time, not silently corrupted downstream.
  - **Transactional Outbox Publisher:** PostgreSQL `LISTEN/NOTIFY` trigger for low-latency outbox signaling. Publisher uses `kafka-python` with idempotent producer (`enable.idempotence=true`, `acks=all`). **Scalability note: publisher is a dedicated pod — does not share thread pool with API serving.**
  - **DLQ consumer:** 3-retry with exponential backoff (1s, 5s, 30s); after max retries routes to `<topic>.DLQ`. Prometheus counter `kafka_dlq_depth` per topic.
  - **Webhook endpoint:** `POST /events/telecom-stream` — validates against JSON Schema, publishes `CallSession.Initiated` to Kafka.
  - **Synchronous interdiction pass-through:** HTTP endpoint that bypasses Kafka entirely for the <300ms path (T15).
- **Effort:** 1.5 days | **Owner:** Diganta

### T8c — Entity Graph Service
- **Purpose:** Map fraud rings via linked entities. | **Depends On:** T3c, T8b. **Unlocks:** T6c, T16.
- **Deliverable:** GET /graph/linkages?entityId=, GET /graph/shortest-path?from=&to=. Kafka consumer builds Neo4j graph from Case.Created + Prediction.Completed. Publishes Entity.RelationshipDiscovered, FraudRing.NodeIdentified.
- **Effort:** 1.5 days | **Owner:** Nilkanta

### T8d — Geospatial Intelligence Service
- **Purpose:** Crime hotspot mapping, patrol APIs. | **Depends On:** T3c, T8b. **Unlocks:** T6c, T16.
- **Deliverable:** GET /geo/hotspots?bbox= (PostGIS bounding box, GeoJSON), GET /geo/patrol-zones?district=, POST /geo/export. Kafka consumer updates PostGIS within 60s of Case.Created or CounterfeitScan.Submitted. RBAC-scoped by jurisdictionId.
- **Effort:** 1.5 days | **Owner:** Nilkanta

### T8e — Notification Service (with MHA Alert)
- **Purpose:** Omnichannel alerting with dedicated MHA webhook (<5s SLO). | **Depends On:** T3c, T8b. **Unlocks:** T13c, T15, T16.
- **Deliverable:** POST /notify/send (SMS/Email/Push — stubbed initially), POST /notify/mha-alert (high-priority queue, <5s SLO), GET /notify/preferences/:userId. SSE for real-time push. Publishes MHAAlert.Sent. **MHA channel uses a dedicated Kafka consumer group with highest priority — separate from standard citizen notification consumer to prevent head-of-line blocking.**
- **Effort:** 1.5 days | **Owner:** Nilkanta

### T8f — Search Service (OpenSearch Kafka Consumer)
- **Purpose:** CQRS read model for case + evidence search (FR-9). Indexes events into OpenSearch asynchronously — services query this instead of heavy PostgreSQL LIKE queries. | **Depends On:** T8b, T3c. **Unlocks:** T6c, T16.
- **Deliverable:**
  - FastAPI service with `GET /search/cases?q=&status=&riskTier=&from=&cursor=&limit=` — delegates to OpenSearch. Returns cursor-paginated results with facets (`{items[], nextCursor, facets: {status: {}, riskTier: {}}}`).
  - Kafka consumer on `Case.Created`, `Case.Updated`, `Evidence.Uploaded`, `Prediction.Completed` — upserts documents into `case_index` and `evidence_index` (OpenSearch `_index` with `_id=caseId`).
  - Full-text search (`match` on description, notes), structured filter (`term` on status, riskTier, jurisdictionId), fuzzy search (`fuzzy` query on entity names — FR-9.3), geospatial search (`geo_bounding_box` on complaint_location — FR-9.4), faceted aggregations (FR-9.5).
  - **Scalability:** OpenSearch horizontal scaling via shard routing. Consumer group allows up to 12 pods to index in parallel (one per partition).
- **Effort:** 1 day | **Owner:** Diganta

---

### T9 — ML: Data Preparation (All 4 Model Types)
- **Purpose:** Ground truth datasets and prompt/feature designs before writing stub code.
- **Depends On:** T2 (needs ml-contract.md). Starts Day 1 independently of sign-off.
- **Deliverable:** (1) Scam NLP: 50+ labeled complaint texts across 5 categories + prompt template + few-shot examples. (2) Counterfeit CV: currency security feature descriptions + image samples. (3) Graph Fraud: 3 synthetic fraud ring adjacency graphs with labeled fraud nodes. (4) Audio spoof: acoustic feature descriptions + sample clips.
- **Effort:** 1 day | **Owner:** Kushal

### T10a — Scam NLP Classifier API
- **Purpose:** Core scam classification. Stub must be live Day 2. | **Depends On:** T9, T2. **Unlocks:** T13.
- **Deliverable:** POST /ml/scam-classify -> {score:0-100, riskTier, category, confidence, signals[], explanation}.
- **Effort:** 1.5 days | **Owner:** Kushal — [CRITICAL PATH — stub Day 2 EOD]

### T10b — Counterfeit CV Classifier API
- **Purpose:** Currency image -> authenticity score. Basis for edge model. | **Depends On:** T9, T2. Stub Day 3.
- **Deliverable:** POST /ml/counterfeit-detect (image/base64) -> {score, isAuthentic, confidence, detectedFeatures[], explanation}.
- **Effort:** 2 days | **Owner:** Kushal

### T10c — Fraud Graph Analyzer API
- **Purpose:** Entity graph -> fraud ring probability. | **Depends On:** T9, T2. Stub Day 3.
- **Deliverable:** POST /ml/graph-analyze (adjacency JSON) -> {score, fraudRingProbability, suspiciousNodes[], explanation}.
- **Effort:** 1.5 days | **Owner:** Kushal

### T10d — Audio Voice Analyzer API
- **Purpose:** Detect AI-generated/spoofed voices. | **Depends On:** T9, T2. Stub Day 3.
- **Deliverable:** POST /ml/audio-analyze (audio file) -> {score, isAISpoofed, confidence, voiceFeatures{pitchVariance, spectralEntropy}, explanation}.
- **Effort:** 2 days | **Owner:** Kushal

### T11 — ML: Evaluation & Tuning (All Models)
- **Purpose:** Hit acceptable precision/recall before integration freeze. | **Depends On:** T10a, T10b, T10c, T10d.
- **Deliverable:** Evaluation report per model (precision, recall, F1 per category), refined prompts/features, threshold values for Orchestrator fusion config.
- **Effort:** 2 days | **Owner:** Kushal

### T12 — ML: Explainability (All Models)
- **Purpose:** Every verdict ships Surjit human-readable reason (NFR-8.2). | **Depends On:** T10a-T10d.
- **Deliverable:** signals[] array + explanation string populated in all 4 APIs. 2-3 plain-English signal strings naming specific detected features.
- **Effort:** 0.5 day | **Owner:** Kushal

### T12b — Quantized Edge Model (Offline Counterfeit Detection)
- **Purpose:** TFLite/ONNX model for offline use on mobile and POS terminals (FR-12). | **Depends On:** T10b, T11. [Cut first if behind by Day 7]
- **Deliverable:** counterfeit_detector.tflite or .onnx (<=10MB, INT8 quantized). Python inference wrapper.
- **Effort:** 1 day | **Owner:** Kushal

---

### T13 — Multi-Source ML Fusion Integration
- **Purpose:** Wire all 4 ML APIs into the Inference Orchestrator. Most architecturally significant integration.
- **Depends On:** T8, T10a (minimum scam NLP stub), T5a, T3b. **Unlocks:** T13b, T13c, T16.
- **Deliverable:** Case creation triggers POST /inference/analyze; Orchestrator fans out to all 4 in parallel; fused verdict stored; Prediction.Completed published; INCOMPLETE + PENDING_REVIEW flows working; timeout/fallback working.
- **Effort:** 1 day | **Owner:** Diganta leads, Surjit pairs — [SYNC POINT #1 — Day 6]

### T13b — HITL Override Integration
- **Purpose:** Low-confidence verdicts block automated actions and route to investigator (NFR-8.1/NFR-8.3).
- **Depends On:** T13, T6c (HITL panel exists), T8e.
- **Deliverable:** Orchestrator emits PENDING_REVIEW -> Case enters Pending_AI -> notifications suppressed. PATCH /cases/:id/verdict/override: APPROVE resumes actions; REJECT archives case. Immutable OverrideRecord persisted. Prediction.Overridden -> Audit.
- **Effort:** 4h | **Owner:** Diganta leads, Surjit (Case side), Nilkanta (dashboard panel)

### T13c — MHA Alert Integration
- **Purpose:** HIGH-risk scam session -> MHA webhook within 5 seconds (FR-10.7). | **Depends On:** T13, T8e.
- **Deliverable:** Orchestrator on HIGH verdict for CallSession.Flagged calls POST /notify/mha-alert directly (bypasses standard queue). MHAAlert.Sent -> Audit. 5s SLO verified.
- **Effort:** 3h | **Owner:** Diganta leads, Nilkanta (Notification side)

### T14 — Surjit<->Nilkanta Slice Cross-Wiring
- **Purpose:** Cases from Surjit appear on Nilkanta dashboard with real data. | **Depends On:** T5a, T5c, T6a, T6c. **Unlocks:** T16.
- **Deliverable:** Evidence from Nilkanta links to cases from Surjit. Dashboard shows real case records, AI verdicts, evidence metadata, graph and geo data.
- **Effort:** 1 day | **Owner:** Surjit + Nilkanta jointly, Diganta facilitates

### T15 — Real-Time Interdiction Path (<300ms SLA)
- **Purpose:** Block financial transfer before it executes (QAS-5). | **Depends On:** T8, T8b, T8e, T3b.
- **Deliverable:** Synchronous path bypassing Kafka: telecom event -> Event Processing -> Orchestrator -> ML (scam-nlp + audio) -> bank block stub -> MHA alert. P99 <300ms locally. Audit event published asynchronously after response returns. Demo-able with simulated payload.
- **Effort:** 1 day | **Owner:** Diganta — [High complexity; schedule buffer here]

### T16 — End-to-End Integration & Smoke Test
- **Purpose:** Verify the full system works as one. | **Depends On:** T13, T13b, T13c, T14, T15.
- [SYNC POINT #2 — Day 8, all 4]
- **Deliverable:** Documented E2E run: (1) Citizen report -> HIGH verdict -> HITL gate -> approve -> MHA alert fires. (2) Evidence upload -> hash verified -> linked to case. (3) Dashboard shows graph linkages + geo hotspot. (4) Intelligence package generated with full audit trail.
- **Effort:** 4h | **Owner:** Diganta leads, all 4 attend

### T17 — Testing Pass
- **Depends On:** T16. | **Effort:** 1.5 days | **Owner:** Surjit (citizen slice), Nilkanta (investigator slice), Kushal (ML validation), Diganta (integration/system/contract tests)

### T18 — Bug Fixing & Polish
- **Depends On:** T17. | **Effort:** 1 day | **Owner:** Surjit+Nilkanta fix own slices, Diganta fixes cross-cutting bugs.

### T19 — Deployment
- **Depends On:** T18. [MILESTONE — Demo-Ready Build] | **Effort:** 4h | **Owner:** Diganta

### T20 — Demo Video + Architecture Diagram + Deck
- **Depends On:** T16. Runs parallel to T17/T18. | **Effort:** 1.5 days
- **Owner:** Diganta (diagram), Surjit+Nilkanta (deck + video), Kushal (ML accuracy slides)

### T21 — Rehearsal & Final Checklist
- **Depends On:** T19, T20. | **Effort:** 3h | **Owner:** All 4

---

### Critical Path
T1 -> T2 -> T3c -> T5a -> T13 -> T16 -> T17 -> T18 -> T19 -> T21
Parallel must-not-slip: T8 (Orchestrator) complete Day 5. T10a stub live Day 2. All 4 ML stubs live Day 3.

---

## 3. Team Assignment Rationale

| Member | Tasks | Rationale |
|---|---|---|
| Diganta | T1,T2,T3,T3b,T3c,T7,T8,T8b,T13,T13b,T13c,T15,T16,T18,T19,T20 | Owns infra, all API contracts, Inference Orchestrator, real-time interdiction, integration lead. |
| Surjit | T4,T5a,T5b,T5c,T13(pair),T13b(Case side),T14,T17/T18 | Owns citizen vertical slice. Provides Case Service integration hook for ML. |
| Nilkanta | T6a,T6b,T6c,T8c,T8d,T8e,T13b(dashboard),T13c(Notification),T14,T17/T18 | Owns investigator slice + all data intelligence services (Geo, Graph, Reporting). |
| Kushal | T9,T10a,T10b,T10c,T10d,T11,T12,T12b | Fully decoupled. Only sync point is T2 (contract Day 1). All 4 stubs live by Day 3. |


## 4. Execution Timeline

| Day | Date | Diganta | Surjit | Nilkanta | Kushal | Sync / Milestone |
|---|---|---|---|---|---|---|
| 1 | Sat Jul 11 | T1,T2,T3,T3b | Env setup, read all docs, ask clarifying Qs | Env setup, read all docs | T9: data prep all 4 models | EOD: T3c Design sign-off, all 4 |
| 2 | Sun Jul 12 | T8b: Kafka backbone | T4: Auth/Identity | T6a: Evidence start | T10a: Scam NLP stub | EOD: T10a stub live |
| 3 | Mon Jul 13 | T8: Orchestrator start | T5a: Case Service start | T6a: Evidence finish, T8d: Geospatial start | T10b: CV stub, T10c: Graph stub | — |
| 4 | Tue Jul 14 | T8: Orchestrator finish | T5a: Case Service finish | T8d: Geo finish, T8c: Entity Graph | T10d: Audio stub, T11: tuning starts | All 4 ML stubs live |
| 5 | Wed Jul 15 | T7: Audit Service | T5b: Bot stub, T5c: Citizen UI start | T8e: Notification+MHA, T6b: Reporting start | T11: tuning, T12: explainability | Platform services complete |
| 6 | Thu Jul 16 | T13 lead, T13c: MHA alert | T5c: Citizen UI + Bot UI finish | T6b: Reporting finish, T6c: Dashboard start | T11 finalize, T12 all models | SYNC #1: Multi-source ML integration |
| 7 | Fri Jul 17 | T13b: HITL, T15: interdiction path | T13b (Case side), T14 start | T6c: Dashboard finish (HITL+graph+geo), T14 start | T12b: edge model start | — |
| 8 | Sat Jul 18 | T16 lead: E2E smoke test | T14 finish, T16 | T14 finish, T16 | Support T16, T12b finish | SYNC #2: Full E2E verified, all 4 |
| 9 | Sun Jul 19 | T17: contract/integration/system tests | T17: citizen slice tests | T17: investigator slice tests | T17: ML validation (precision/recall) | — |
| 10 | Mon Jul 20 | T18 coord, T19 deployment | T18: bug fixes | T18: bug fixes | Deck ML content | MILESTONE: Demo-ready deployed |
| 11 | Tue Jul 21 | T20: full architecture diagram | T20: deck + video | T20: deck + video | T20: ML accuracy slides | — |
| 12 | Wed Jul 22 | T21 rehearsal | T21 | T21 | T21 | FINAL: Rehearsal, v1.0.0, submission |

**Standing syncs:** 15-min daily standup + mandatory full syncs Day 1 EOD (design sign-off), Day 6 (ML integration), Day 8 (E2E), Day 10 (go/no-go).

---

## 5. GitHub Workflow

### Repository Structure
```
/backend/
  auth/                    (Surjit)
  case/                    (Surjit)
  bot/                     (Surjit)
  evidence/                (Nilkanta)
  notification/            (Nilkanta)
  reporting/               (Nilkanta)
  geospatial/              (Nilkanta)
  graph/                   (Nilkanta)
  inference-orchestrator/  (Diganta)
  event-processing/        (Diganta)
  audit/                   (Diganta)
  ml-client/               (Diganta - integration glue calling Kushal ML APIs)
/frontend/
  citizen/                 (Surjit)
  investigator/            (Nilkanta)
/ml/
  scam-nlp/                (Kushal)
  counterfeit-cv/          (Kushal)
  graph-analyzer/          (Kushal)
  audio-analyzer/          (Kushal)
  edge/                    (Kushal - TFLite/ONNX edge model)
/infra/                    (Diganta - docker-compose, CI, deployment)
/docs/                     (Diganta - LLD, API contracts, schema, sequence diagrams)
```

### Branching Strategy
- `main` — protected, always demo-ready.
- `develop` — protected integration branch.
- `design/<desc>` — Diganta only. **Merged before any feature branch is created.**
- `feature/infra-<desc>` — Diganta platform services.
- `feature/Surjit-<desc>` — Surjit: feature/Surjit-auth, feature/Surjit-case, feature/Surjit-bot, feature/Surjit-citizen-ui.
- `feature/Nilkanta-<desc>` — Nilkanta: feature/Nilkanta-evidence, feature/Nilkanta-geo, feature/Nilkanta-graph, feature/Nilkanta-notification, feature/Nilkanta-reporting, feature/Nilkanta-dashboard.
- `ml/<desc>` — Kushal: ml/scam-nlp, ml/counterfeit-cv, ml/graph-analyzer, ml/audio-analyzer, ml/edge-model.
- `fix/<desc>` — post-integration bug fixes.

### Branch Merge Order

| Branch | Owner | Merged to develop |
|---|---|---|
| design/api-contracts-v1 | Diganta | Day 1 EOD (before ALL feature branches) |
| design/db-schema | Diganta | Day 1 EOD |
| design/sequence-diagrams | Diganta | Day 1 EOD |
| feature/infra-docker-compose | Diganta | Day 1 EOD |
| feature/Surjit-auth | Surjit | Day 2 EOD |
| ml/scam-nlp | Kushal | Day 2 (stub), Day 5 (real) |
| feature/infra-event-processing | Diganta | Day 2 EOD |
| ml/counterfeit-cv | Kushal | Day 3 (stub), Day 5 (real) |
| ml/graph-analyzer | Kushal | Day 3 (stub), Day 6 (real) |
| ml/audio-analyzer | Kushal | Day 3 (stub), Day 6 (real) |
| feature/Nilkanta-evidence | Nilkanta | Day 3 EOD |
| feature/Surjit-case | Surjit | Day 5 EOD |
| feature/Nilkanta-geo | Nilkanta | Day 4 EOD |
| feature/Nilkanta-graph | Nilkanta | Day 4 EOD |
| feature/infra-orchestrator | Diganta | Day 5 EOD |
| feature/infra-audit | Diganta | Day 5 EOD |
| feature/Nilkanta-notification | Nilkanta | Day 5 EOD |
| feature/Nilkanta-reporting | Nilkanta | Day 6 EOD |
| feature/Surjit-bot | Surjit | Day 6 EOD |
| feature/Surjit-citizen-ui | Surjit | Day 6 EOD |
| feature/Nilkanta-dashboard | Nilkanta | Day 7 EOD |
| feature/infra-ml-integration | Diganta | Day 6 EOD |
| feature/infra-hitl | Diganta | Day 7 EOD |
| feature/infra-interdiction | Diganta | Day 7 EOD |
| feature/cross-wiring-ab | Surjit + Nilkanta | Day 8 EOD |
| ml/edge-model | Kushal | Day 8 EOD |
| fix/* | Surjit, Nilkanta, Diganta | Same day (Day 9-10) |

**Conflict prevention:** Surjit and Nilkanta never touch the same folders by design. Diganta platform services are distinct folders from both. Kushal only touches /ml/*.

### PR Rules
- `design/*`: **All 4 approvals** required — everyone builds against these.
- Feature/ML branches: **1 reviewer** (Surjit reviews Nilkanta, Nilkanta reviews Surjit; Diganta reviews infra/ML-integration PRs).
- CI (lint + unit tests) must pass before any merge. Squash-merge into develop.
- develop -> main: Day 8 only (tag v0.5.0-beta) and Day 10 (tag v0.9.0-rc).

### Version Tags

| Tag | Day | Condition |
|---|---|---|
| v0.1.0-alpha | Day 2 | Infra + design + auth + ML scam stub |
| v0.3.0-alpha | Day 5 | All platform services + slices feature-complete (mocked) |
| v0.5.0-beta | Day 8 | Full E2E smoke test passes |
| v0.9.0-rc | Day 10 | Testing pass, deployed and reachable |
| v1.0.0 | Day 12 | Final submission tag on main |

---

## 6. Commit Strategy

**Never commit:** .env with real secrets, raw datasets, model weights, uploaded evidence files, node_modules/, __pycache__/, build artifacts, DB dumps. .gitignore committed by Diganta on Day 1 before anyone else pushes.

**Format:** `<type>(<scope>): <description>` — types: feat, fix, docs, refactor, chore, test, ci, perf

**Key commits:**
```
chore(infra): initialize monorepo and docker-compose with all 15 service data stores
docs(design): finalize API contracts for all 15 services (v1)
docs(design): finalize DB schema DDL - PostgreSQL, Neo4j, PostGIS, Redis, Kafka topics
docs(design): add 6 sequence diagrams (fusion, HITL, interdiction, edge-sync, geo, override)
feat(auth): implement JWT login, register, MFA verify, RBAC claims
feat(infra): add Kafka backbone, Outbox publisher, DLQ consumer
feat(orchestrator): implement parallel AI dispatch, fusion weights, HITL routing
feat(audit): add immutable Kafka-driven audit log consumer
feat(case): implement case CRUD, state machine, Outbox publishing, verdict override
feat(bot): add multi-turn session bot with Orchestrator proxy
feat(citizen-ui): build report form, risk verdict display, bot chat widget
feat(evidence): implement file upload, SHA-256 hash, MIME validation, MinIO
feat(geo): add PostGIS hotspot layer, patrol zone API, Kafka consumer
feat(graph): add Neo4j entity linkage and shortest-path APIs
feat(notification): add MHA alert channel, SSE push, omnichannel stub
feat(reporting): add NCRB report and intelligence package endpoint
feat(dashboard): build investigator UI - cases, HITL panel, graph viz, geo heatmap
feat(ml-scam): add NLP scam classifier stub matching ml-contract.md
feat(ml-cv): add counterfeit CV detector stub
feat(ml-graph): add graph fraud analyzer stub
feat(ml-audio): add audio voice spoof analyzer stub
feat(infra-ml): wire Orchestrator to all 4 ML APIs with parallel dispatch and fusion
feat(infra-hitl): implement HITL override - suppression, approval gate, audit record
feat(infra-interdiction): add 300ms interdiction path with bank stub
feat(ml-cv): quantize counterfeit model to TFLite for edge deployment
test(integration): E2E smoke test - report to fusion to HITL to MHA alert to dashboard
chore(release): tag v1.0.0 for final submission
```

---

## 7. Integration Order

1. Design docs frozen (Day 1 EOD) — nothing built before this.
2. Kafka backbone live (Day 2) — every service publishing/consuming events needs this first.
3. Auth complete (Day 2) — all downstream services need user context.
4. ML stubs live: T10a Day 2; T10b/c/d Day 3. Orchestrator integration (T13) needs at least stub endpoints to call.
5. Surjit and Nilkanta build independently (Day 2-6) against frozen contract. No cross-dependency until T14.
6. Inference Orchestrator complete (Day 5) — must be live before T13.
7. Multi-source ML fusion integrated (T13, Day 6) — first real cross-boundary integration.
8. HITL + MHA alert wired (T13b/T13c, Day 7).
9. Real-time interdiction path (T15, Day 7) — Diganta owns solo.
10. Surjit<->Nilkanta cross-wiring (T14, Day 7-8) — pair-owned, one point slices meet.
11. Full E2E smoke test (T16, Day 8) — only after T13/T13b/T13c/T14/T15 all stable.
12. DB migrations: Only Day 1 design phase. Post-Day 5 schema change requires team-wide flag + coordinated migration file.
13. Final deployment (Day 10) — only after Day 9 testing pass.

---

## 8. Testing Strategy

| Stage | Performed By | When | Scope |
|---|---|---|---|
| Unit Testing | Surjit, Nilkanta, Diganta, Kushal | Continuously | Functions, state machine, hash logic, fusion weights |
| ML Model Validation | Kushal | Day 5 (initial), Day 9 (final) | Precision/recall/F1 per model per category. Target: >=80% recall on HIGH-risk |
| API Contract Testing | Diganta | Day 5 onward | Newman/Postman against every service endpoint per api-contracts.md |
| Kafka Event Flow Testing | Diganta | Day 5 onward | Publish test event -> verify all downstream consumers react |
| Backend Testing | Surjit (own), Nilkanta (own) | Continuous, formal pass Day 9 | Endpoint correctness, DB persistence, error handling |
| Integration Testing | Diganta leads, Surjit+Nilkanta | Day 8, Day 9 | Full cross-service: Case.Created -> ML -> Audit + Geo + Notification |
| HITL Path Testing | Diganta + Surjit | Day 8-9 | Low-confidence verdict -> PENDING_REVIEW -> override panel -> approve/reject -> audit |
| Interdiction Path Testing | Diganta | Day 8-9 | Simulated telecom payload -> <300ms P99 measured -> MHA alert -> audit logged |
| System Testing | All 4 | Day 9 | Full app under multi-case, multi-user scenario |
| UAT | All 4 role-play | Day 9-10 | Does the flow make sense to Surjit first-time user |
| Frontend Testing | Surjit, Nilkanta | Day 6-8, Day 9 | Form validation, HITL panel, graph rendering, geo heatmap |

---

## 9. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Diganta is Surjit bottleneck | Medium | High | Design (Day 1) front-loaded before integration load (Day 6-7). Two hardest jobs sequenced, not simultaneous. |
| ML stubs late | Medium | High | Surjit, Nilkanta, Diganta build against hardcoded mocks from Day 2. T13 (Day 6) is only task requiring live ML endpoints. |
| Inference Orchestrator (T8) slips | Medium | Critical | T8 gets 100% of Diganta's focus Days 3-4. Starts Day 3, must finish Day 5. |
| Surjit's Case Service runs long | Medium | High | Nilkanta is fully independent. If Surjit slips, Diganta or Nilkanta can help after Nilkanta's Day 4 work is stable. |
| Nilkanta's slice is wide (6 services) | High | Medium | Each service is smaller than Surjit's Case Service. Geo+Graph are event-driven consumers (simpler plumbing). Dashboard builds against mocks until T14. Worst case: cut intelligence package to plain NCRB report. |
| T15 misses <300ms locally | Medium | Low | Prototype demo - architecture is correct, document gap honestly. Demo shows the path, not production latency. |
| Cross-wiring (T14) surfaces mismatches | Medium | Medium | 1-day dedicated slot. Surjit and Nilkanta built against same frozen contract so mismatches should be type/field issues, not structural. |
| Contract drift after freeze | Medium | High | Post-Day 5 change requires same-day team notification, new version file (api-contract-v2.md), explicit agreement. |
| Deployment issues Day 10 | Medium | Medium | Diganta test-deploys docker-compose skeleton Days 2-4, not for first time on Day 10. |
| Live demo fails | Medium | High | Backup recorded video ready by Day 11 covering all 5 PS modules. |
| Over-scoping | High | High | Cut order: (1) Edge model (T12b) first - stub only. (2) Intelligence package -> plain NCRB report. (3) Interdiction demo -> walkthrough slide. (4) Geo -> static sample data. Never cut ML fusion or HITL. |

---

## 10. Final Master Roadmap

### Priority Tiers

| Tier | Features | Why |
|---|---|---|
| P0 - Must demo perfectly | Auth, Case, Inference Orchestrator (multi-source fusion), Evidence, Notification (MHA), HITL override, Citizen UI, Investigator Dashboard | Core evaluation criteria |
| P1 - Strong differentiators | Entity Graph, Geospatial, Reporting (NCRB), Audit, real-time interdiction, Conversational Bot | Makes system visually compelling and complete |
| P2 - If time permits | Intelligence package, quantized edge model, 12-language bot, full SSE push | Demo as architecture slides if not fully built |

### Gantt-Style Schedule
```
Day:                      1  2  3  4  5  6  7  8  9  10 11 12
T1 Infra+docker-compose   XX
T2 All contracts          XX
T3 All schemas            XX
T3b Sequence diagrams     XX
T3c Sign-off              x(EOD)
T4 Auth (Surjit)                  XX
T8b Kafka backbone (Diganta)       XX
T6a Evidence (Nilkanta)             xx xx
T10a Scam NLP stub (Kushal)      XX
T10b CV stub (Kushal)               XX
T10c Graph stub (Kushal)            XX
T10d Audio stub (Kushal)            XX
T5a Case Service (Surjit)            xx xx xx xx
T8 Orchestrator (Diganta)             xx xx xx xx
T8d Geospatial (Nilkanta)                 xx xx xx
T8c Graph Service (Nilkanta)              xx xx
T7 Audit Service (Diganta)                  XX
T5b Bot Service (Surjit)                   xx xx
T8e Notification+MHA (Nilkanta)              xx xx
T6b Reporting (Nilkanta)                     xx xx xx
T11 ML Tuning (Kushal)                    xx xx xx xx
T12 Explainability (Kushal)               xx xx
T5c Citizen UI (Surjit)                    xx xx xx xx
T6c Dashboard UI (Nilkanta)                  xx xx xx xx xx
T13 ML Integration (Diganta+Surjit)                    XX
T13c MHA alert (Diganta+Nilkanta)                        XX
T13b HITL override (Diganta+Surjit+Nilkanta)                     XX
T15 Interdiction path (Diganta)                      XX
T12b Edge model (Kushal)                        xx xx xx
T14 Cross-wire Surjit+Nilkanta                             xx xx
T16 E2E smoke test (Diganta)                            XX
T17 Testing                                          xx xx xx
T18 Bug fixes                                              xx xx
T19 Deployment (Diganta)                                         x
T20 Demo+Deck+Diagram                                xx xx xx xx xx
T21 Rehearsal                                                        XX
```

### Final Deployment Checklist
- [ ] Day 9 tests passing on develop
- [ ] All 15 services start cleanly with docker compose up
- [ ] No secrets in repo history
- [ ] .env.example current and complete
- [ ] Deployment target provisioned and reachable
- [ ] DB migrations run cleanly on a fresh instance (PostgreSQL, Neo4j, PostGIS, OpenSearch index mappings)
- [ ] Kafka topics and Schema Registry schemas configured on deploy target
- [ ] Vault running in production mode with all secrets populated
- [ ] Prometheus scraping all 15 services, Grafana dashboards green
- [ ] Kong upstream health checks passing for all backend services
- [ ] All 4 ML models deployed alongside ML services
- [ ] Full E2E flow verified on deployed instance (not just local)
- [ ] HITL override flow verified on deployed instance
- [ ] MHA alert webhook fires on HIGH verdict (verified with webhook tester)
- [ ] Demo video recorded as backup (HITL, graph viz, geo heatmap, bot, interdiction)
- [ ] Architecture diagram (full target-state) finalized in deck
- [ ] Deck reviewed and timing confirmed by all 4
- [ ] Final tag v1.0.0 pushed to main
- [ ] Rehearsal completed with timing check

---

## 11. AI-Assisted Implementation Guide

### 11.1 Tools by Role

| Tool | Best For | Who |
|---|---|---|
| Claude Code (terminal) | Multi-file scaffolding, debugging with real context, running commands | Diganta, Surjit, Nilkanta, Kushal |
| Claude.ai / ChatGPT | Contract design, schema review, architecture decisions, prompt engineering | Everyone |
| Cursor / Copilot | In-editor autocomplete once files have structure | Surjit, Nilkanta |

Golden rule: Always paste real context - the contract file, the exact error, the current code. Vague prompts produce generic code that wont match your schema.

### 11.2 Day 1 — Design Sprint (Diganta)

**T1 — Production Docker Compose**
> *"Set up a production-grade monorepo. Folders: /backend/{auth,case,evidence,notification,reporting,geospatial,graph,bot,inference-orchestrator,event-processing,audit}, /frontend/{citizen,investigator}, /ml/{scam-nlp,counterfeit-cv,graph-analyzer,audio-analyzer,edge}, /infra/{docker,kong,vault,prometheus,grafana,loki,otel}, /docs. Write a docker-compose.yml with all of: (1) postgres:16-alpine with an init.sql that creates per-domain schemas and runs migrations. (2) postgis/postgis:16-3.4 dedicated container for geospatial domain. (3) neo4j:5-community with NEO4JPLUGINS=apoc. (4) redis:7-alpine. (5) opensearch:2 node in single-node mode + opensearch-dashboards:2. (6) confluentinc/confluent-local:7.6 for Kafka KRaft. (7) confluentinc/cp-schema-registry:7.6 linked to Kafka. (8) minio/minio with an mc init container that creates evidence, reports, and edge-model buckets on startup. (9) kong:3-alpine in DB-less mode with KONG_DATABASE=off and KONG_DECLARATIVE_CONFIG=/etc/kong/kong.yml — mount /infra/kong/kong.yml. (10) vault:1.16 in dev mode. (11) prom/prometheus:v2.52, grafana/grafana:10.4, grafana/loki:3.0, grafana/promtail:3.0, grafana/tempo:2.4, otel/opentelemetry-collector-contrib:0.100.0. Add health checks with depends_on conditions so Kafka is healthy before Schema Registry, Schema Registry before any backend service. Write a Makefile with: make up, make down, make logs, make migrate, make seed-vault. Include a .env.example with all variable names but no values."*

**T2 — All API Contracts**
> *"We are building a production-grade AI fraud detection platform with 15 microservices backed by FastAPI [paste SRS FRs 1-14]. Write a complete API contract for each service. All contracts must include: exact routes (versioned under /api/v1/), methods, request/response JSON schemas (field names, types, required/optional, constraints), HTTP status codes, standard error envelope with requestId/correlationId/errorCode/message/details, idempotency key requirements on mutating endpoints, and rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining). Also include ml-contract.md covering 4 AI model endpoints each returning {score, riskTier, confidence, signals[], explanation, processingMs, modelVersion}. Note: FastAPI will auto-generate OpenAPI specs from these — the contract files ARE the OpenAPI spec comments."*

**T3 — All DB Schemas**
> *"Given this API contract [paste all contracts], write: (1) PostgreSQL 16 DDL for all tables — per-domain schemas (identity, investigation, evidence, reporting, audit, predictions, outbox), FKs, indexes (including GIN index on tsvector columns for full-text search, BRIN index on created_at, B-tree on status), CHECK constraints, triggers for outbox NOTIFY signaling. (2) Neo4j 5 schema: Node labels (Entity, Account, Device, PhoneNumber, BankAccount) and Relationship types (LINKED_TO, TRANSACTED_WITH, OWNS, CALLED, REPORTED_BY) with property constraints and indexes. (3) PostGIS DDL for dedicated geospatial database: FraudHotspot, PatrolZone, CounterfeitSeizurePoint with GEOMETRY(Point, 4326) and GEOMETRY(Polygon, 4326) columns, spatial indexes (GIST). (4) Redis key convention documentation with TTL policies per key type. (5) Kafka topic list with partition counts, replication factor, retention.ms, cleanup.policy. (6) OpenSearch index mapping for Case and Evidence documents (dynamic mapping disabled, explicit field types for all searchable fields, nested objects for AI verdict breakdown)."*

**T3b — Sequence Diagrams**
> *"Write Mermaid sequence diagrams for: (1) Citizen report -> Kong JWT validation -> Citizen BFF -> Case Service (Outbox write) -> Orchestrator calls all 4 ML models in parallel -> fused verdict -> HITL gate if low-confidence -> case created, Prediction.Completed to Kafka -> OpenSearch indexed. (2) Evidence upload -> presigned URL from MinIO -> hash computed -> Evidence.Uploaded outbox -> IntelligencePackage triggered. (3) Telecom stream event -> <300ms interdiction synchronous path -> bank block + MHA alert + async Kafka publish. (4) Offline counterfeit scan syncs -> conflict resolution logic. (5) Case created -> Geospatial Kafka consumer upserts PostGIS -> OpenSearch indexes -> SSE push to dashboard. (6) Investigator overrides verdict -> immutable override record -> Prediction.Overridden -> Audit.Recorded."*

### 11.3 Surjit's Citizen Slice

**T4 — Auth**
> *"Using [paste auth.md] and [paste User/Role DDL], implement JWT login/register/refresh/MFA-verify with FastAPI. RS256 tokens using python-jose, RBAC claims in JWT (role, orgId, jurisdictionId). JWT middleware as a FastAPI Depends() that validates the token signature + expiry + revocation check against Redis (JWT denylist). Passlib with bcrypt for password hashing. MFA: TOTP via pyotp, QR code endpoint for authenticator app enrollment. On login, read DB password from Vault using hvac Python client — do NOT read secrets from env vars directly. Add prometheus-fastapi-instrumentator and opentelemetry-instrumentation-fastapi at app startup."*

**T5a — Case Service**
> *"Implement Case Service with FastAPI per [paste case.md] and [paste Case/CaseTimeline/OverrideRecord DDL]. State machine: New->Assigned->Investigating->Pending_AI->Action_Taken->Closed. PATCH /cases/:id/state validates transitions (409 on invalid). PATCH /cases/:id/verdict/override: validate justification min 10 chars (422 otherwise), INSERT immutable OverrideRecord (no UPDATE/DELETE ever on this table — add a PostgreSQL trigger that raises an exception on UPDATE/DELETE). On POST /cases: use SQLAlchemy async session to write the Case row AND the outbox row in a single transaction (unit of work pattern). The outbox row triggers a NOTIFY to the outbox publisher. Use asyncpg for connection. Stub ML call — return a hardcoded verdict object matching the Orchestrator response contract exactly."*

**T5b — Conversational Bot**
> *"Implement POST /bot/message and GET /bot/session/:id with FastAPI per [paste bot.md]. Store multi-turn session state as a JSON array in Redis under key bot:session:{sessionId} with 30-min TTL (redis-py async). For each message, call POST /inference/analyze on the Orchestrator using httpx.AsyncClient with a 5-second timeout. Include the correlation_id from the request header in all downstream calls. Stub the orchestrator call — return a canned HIGH-risk verdict response."*

**T5c — Citizen UI**
> *"Build a React 18 + Vite citizen portal: (1) Report submission form with description textarea, phone number (E.164 validated), optional file upload (drag-and-drop for image/audio), calls POST /api/v1/cases via React Query mutation. On success, display the returned risk verdict: 0-100 gauge chart (recharts), confidence percentage, color-coded risk tier badge (RED=HIGH using red-500, AMBER=MEDIUM using amber-500, GREEN=LOW using green-500), explanation text in a card. Show a yellow Awaiting investigator review banner with pulse animation when status=PENDING_REVIEW. (2) Bot chat widget in the bottom-right corner: calls POST /api/v1/bot/message, renders multi-turn conversation with a typing indicator (three dots animation) and per-message AI risk assessment cards. Use Zustand for chat session state. Style with Tailwind CSS."*

### 11.4 Nilkanta's Investigator Slice

**T6a — Evidence Service**
> *"Implement POST /cases/:id/evidence (multipart) with FastAPI per [paste evidence.md]. (1) Generate a MinIO presigned PUT URL using minio-py SDK, return it to the client for direct browser upload — do not proxy the file bytes through the API server. (2) After the client confirms upload via POST /evidence/:id/confirm, download only the file header bytes, validate MIME type (image/png, image/jpeg, application/pdf, audio/wav, audio/mpeg, audio/mp4 — return 415 otherwise), compute SHA-256 hash using hashlib on the streamed bytes and store in evidence_hash table alongside evidenceId, caseId, fileSize, mimeType. (3) Write Evidence.Uploaded to outbox table in the same transaction as the DB insert. (4) Read MinIO credentials from Vault using hvac client, not env vars."*

**T8d — Geospatial Service**
> *"Implement GET /geo/hotspots, GET /geo/patrol-zones, POST /geo/export with FastAPI per [paste geo contract]. Connect to the dedicated PostGIS container (not the primary Postgres) using asyncpg. Hotspot query: SELECT ST_AsGeoJSON(geom)::json as geometry, incident_count, risk_tier FROM fraud_hotspot WHERE ST_Within(geom, ST_MakeEnvelope($1, $2, $3, $4, 4326)) ORDER BY incident_count DESC LIMIT 500 — return as RFC 7946 GeoJSON FeatureCollection. Write a confluent-kafka-python consumer on Case.Created: extract complaint_lat, complaint_lon, risk_tier, case_id — INSERT into fraud_hotspot with ON CONFLICT (geom_hash) DO UPDATE SET incident_count = incident_count + 1. Apply RBAC: add WHERE jurisdiction_id = $jurisdictionId from JWT claim. Register the geospatial JSON schema in Schema Registry before the consumer starts."*

**T8c — Entity Graph Service**
> *"Implement GET /graph/linkages and GET /graph/shortest-path with FastAPI per [paste graph contract] using the official neo4j Python async driver. Linkages: MATCH (e:Entity {id: $id})-[r*1..2]-(linked) RETURN e, r, linked, labels(linked) as types LIMIT 100. Shortest path: MATCH p=shortestPath((a:Entity {id: $from})-[*..6]-(b:Entity {id: $to})) RETURN [n in nodes(p) | {id: n.id, type: labels(n)[0], score: n.fraud_score}] as path. Write a confluent-kafka-python consumer on Case.Created + Prediction.Completed: MERGE (e:Entity {id: $phoneNumber, type: 'PhoneNumber', fraud_score: $fusedScore}) — update fraud_score on Prediction.Completed. Register JSON schemas in Schema Registry."*

**T6c — Investigator Dashboard**
> *"Build a React 18 + Vite investigator dashboard with React Query, Zustand, and Tailwind CSS: (1) Case list page: EventSource connection to GET /api/v1/notify/sse for real-time push updates — new Case.Created events prepend to the list with a slide-in animation. Table columns: ID (copyable), status badge (colored pill), risk tier badge, confidence % (colored number), created_at (relative time). Client-side full-text search against the OpenSearch-backed GET /api/v1/cases/search. (2) Case detail page: AI verdict card with a 0-100 arc gauge (victory-native or recharts RadialBar), confidence percentage, per-model breakdown table (Scam NLP / Counterfeit CV / Graph / Audio — individual scores or UNAVAILABLE badge if model not applicable), explanation text in a styled alert box. HITL override panel, visible only when status=PENDING_REVIEW: Approve button (green), Reject button (red), mandatory justification textarea (min 10 chars with live char counter, submit disabled until threshold met), calls PATCH /cases/:id/verdict/override. (3) Entity graph panel: react-force-graph-2d, nodes colored by fraud_score (red gradient), node click shows entity detail drawer. (4) Geospatial heatmap: Leaflet.js with Leaflet.heat plugin, GeoJSON loaded from GET /geo/hotspots?bbox={map bounds}, heatmap intensity driven by incident_count."*

### 11.5 Kushal — ML Pipeline

Kushal owns the ML pipeline end-to-end. The only platform-facing obligations are documented in **Section 12** (ML Integration Guide): the 4 API contracts, stub deadlines, explainability format, health endpoints, and edge model spec. How Kushal builds each model internally is Kushal's decision.

### 11.6 Integration (Diganta leads)

**T13 — Multi-Source Fusion**
> *"In the Inference Orchestrator [paste T8 code], implement parallel dispatch using asyncio.gather with per-model timeouts via asyncio.wait_for(timeout=2.0). Fan out to all enabled ML APIs (list from Redis key `fusion:enabled_models`). **Before marking a model UNAVAILABLE: retry once with 500ms backoff on 5xx or network error (`httpx.RequestError`) — only after the retry fails should the model be marked UNAVAILABLE.** Use a shared `httpx.AsyncClient` with connection pool (`limits=httpx.Limits(max_connections=50, max_keepalive_connections=20)`) — do NOT create a new client per request. Apply fusion weights read from Redis key `fusion:weights` (default: scam-nlp: 0.40, cv: 0.20, graph: 0.25, audio: 0.15 — live-configurable enables weight tuning during demo). Composite score = weighted average of individual scores weighted by confidence. If any model is UNAVAILABLE after retry, renormalize remaining weights so they still sum to 1.0. If overall confidence < 0.60, set status=PENDING_REVIEW and skip the Notification Service call entirely. Persist the complete FusedVerdict row. Publish Prediction.Completed to Kafka via outbox."*

**T13b — HITL Override**
> *"In Case Service [paste T5a code], the PATCH /cases/:id/verdict/override endpoint: validate justification is non-empty and at least 10 chars (return 422 otherwise). On APPROVE: transition case from Pending_AI to Investigating, make an HTTP call to Notification Service to resume the suppressed alert. On REJECT: transition to Action_Taken with rejection_reason populated. In both cases: INSERT an immutable OverrideRecord row — never UPDATE or DELETE this table. Publish Prediction.Overridden to Kafka outbox → Audit Service logs it. In the Orchestrator: when setting PENDING_REVIEW status, do NOT call Notification Service — store a pending_notification flag on the FusedVerdict row and resume only when an APPROVE override comes in."*

**T15 — Real-Time Interdiction**
> *"Implement the <300ms synchronous path in Event Processing Service [paste T8b code]. Add POST /events/telecom-stream that accepts call session metadata and processes it synchronously (not via Kafka). Immediately make an HTTP POST to /inference/analyze on the Orchestrator with onlyModels: [scam-nlp, audio-analyzer] and a 1500ms total timeout. On HIGH verdict: concurrently call POST http://bank-stub/block-transfer (mock) and POST /notify/mha-alert using asyncio.gather. Return the interdiction verdict to the caller. After the response has been sent, publish Intervention.Requested to Kafka asynchronously (fire-and-forget). Add middleware using time.perf_counter to log P50 and P99 latency per request. Target: full synchronous path under 300ms locally."*

### 11.7 Testing, Deploy, Delivery

**T17 — Integration Tests**
> *"Write pytest integration tests for the full integration stack verifying: (1) T13 fusion: all 4 ML models called concurrently — assert total time ≈ max single model latency, not sum. (2) One model returning 504 triggers one retry at 500ms, then UNAVAILABLE — assert exactly 2 httpx calls were made to that model. (3) All models UNAVAILABLE — assert verdict status=INCOMPLETE and case transitions to Investigating (AI_TIMEOUT re-entry). (4) confidence < 0.6 — assert PENDING_REVIEW and Notification Service mock is NOT called. (5) HIGH confidence — assert Prediction.Completed written to Kafka outbox. (6) Evidence upload: assert ClamAV is called for every confirmed upload; mock ClamAV returning FOUND — assert 422 MALWARE_DETECTED. (7) PgBouncer: assert services connect to PgBouncer port, not Postgres directly. Use httpx.AsyncClient, mock Kafka producer, mock ClamAV TCP socket."*

**T19 — Deployment**
> *"I have a production docker-compose.yml with 17+ services: PostgreSQL, PgBouncer, PostGIS, Neo4j, Redis, OpenSearch, Kafka KRaft, Schema Registry, MinIO, ClamAV, Kong, Vault, Prometheus, Grafana, Loki, Tempo, OTel Collector, plus 15 backend services [paste file]. Walk me through deploying to [Railway/Render/DigitalOcean App Platform / Fly.io]: (1) Vault: switch from dev mode to production mode — initialize, unseal, store all service secrets (DB passwords, MinIO access key, ML API keys, JWT RS256 private key). (2) PgBouncer: set `DATABASE_URL` for all services to point to PgBouncer, not Postgres directly — verify pool stats endpoint. (3) Redis: if provider supports Redis Cluster, configure 3 primary + 3 replica shards; otherwise use Redis Sentinel. (4) Persistent volumes for PostgreSQL, PostGIS, Neo4j, MinIO, OpenSearch, Redis. (5) Kafka KRaft: set KAFKA_NODE_ID, KAFKA_PROCESS_ROLES, KAFKA_CONTROLLER_QUORUM_VOTERS. Run topic provisioning script. Run Schema Registry schema registration script. (6) ClamAV: verify freshclam database is updated before Evidence Service starts. (7) Kong: mount kong.yml, verify all upstream service URLs resolve, test JWT validation. (8) OpenSearch: verify case_index and evidence_index mappings created (3 shards). (9) Search Service: verify Kafka consumer group is assigned partitions. (10) Health sweep: all services return 200 on GET /health/ready. Explain every command."*

**T20 — Architecture Description**
> *"Generate a detailed description for a production-grade architecture diagram of our AI fraud detection platform. 17 microservices organized into: Control Plane (Kong API Gateway, Identity Service, Configuration Service — backed by Redis + Vault, Audit Service) and Data Plane (Case Management, Evidence Management, Search Service, Inference Orchestrator, Event Processing, Entity Graph, Geospatial Intelligence, Notification, Reporting, Conversational Bot, Citizen BFF, Investigator BFF). External: 4 AI ML services (Scam NLP, Counterfeit CV, Graph Analyzer, Audio Analyzer), Telecom APIs, Banking Core, MHA webhook, NCRB portal, ClamAV, Mapping APIs. Data stores: PostgreSQL 16 + PgBouncer, PostGIS 3.4, Neo4j 5, Redis 7 Cluster, Kafka 3.6 KRaft + Schema Registry, MinIO, OpenSearch 2. Observability: Prometheus + Grafana + Loki + Tempo + OTel Collector. Secrets: HashiCorp Vault. Show horizontal scaling boundaries (which services scale independently), the synchronous interdiction path (<300ms), the async Kafka event fan-out, and the HITL gate."*

---

## 12. ML Integration Guide (For Kushal)

### 12.1 Standard API Contract (All 4 Models)

Every ML service must match ml-contract.md exactly. Any deviation silently breaks the Orchestrator fusion logic.

**Standard Request (all 4):**
```json
{
  "caseId": "uuid",
  "correlationId": "uuid",
  "modelVersion": "1.0.0"
}
```

**Standard Response (all 4):**
```json
{
  "caseId": "uuid",
  "correlationId": "uuid",
  "modelVersion": "1.0.0",
  "score": 75,
  "riskTier": "HIGH",
  "confidence": 0.87,
  "signals": ["Signal 1 naming specific feature", "Signal 2", "Signal 3"],
  "explanation": "One plain-English sentence naming top contributing signals.",
  "processingMs": 342
}
```

**Endpoint Inputs:**

| Endpoint | URL | Input |
|---|---|---|
| Scam NLP | POST /ml/scam-classify | { "text": "string" } - complaint or call transcript |
| Counterfeit CV | POST /ml/counterfeit-detect | multipart file OR { "imageBase64": "string" } |
| Graph Analyzer | POST /ml/graph-analyze | { "entities": [{id,type,attrs}], "edges": [{from,to,type,weight}] } |
| Audio Analyzer | POST /ml/audio-analyze | multipart audioFile (.wav/.mp3/.m4a) |

### 12.2 Fusion Architecture (Orchestrator Responsibility - NOT Kushal)

The Inference Orchestrator handles fusion. Kushal returns individual model scores only.

```
fusionWeights:
  scam-nlp:       0.40
  counterfeit-cv: 0.20
  graph-analyzer: 0.25
  audio-analyzer: 0.15

compositeScore = SUM(weight_i * score_i) where unavailable models excluded and remaining weights renormalized
confidenceThreshold: 0.60
timeoutMs: 2000
```

### 12.3 Stub -> Real Swap Deadlines

| Model | Stub Deadline | Real Model Deadline | Accuracy Target |
|---|---|---|---|
| Scam NLP | Day 2 EOD (CRITICAL PATH) | Day 5 EOD | Recall >= 85% on HIGH-risk |
| Counterfeit CV | Day 3 EOD | Day 5 EOD | Accuracy >= 80% overall |
| Graph Analyzer | Day 3 EOD | Day 6 EOD | Fraud ring precision >= 75% |
| Audio Analyzer | Day 3 EOD | Day 6 EOD | Spoof detection recall >= 80% |

CRITICAL: A stub must return a valid JSON response matching the standard contract. HTTP 200 with wrong field names breaks the Orchestrator immediately and blocks T13.

### 12.4 Required Health Endpoints

Every ML service must expose:
```
GET /health -> { "status": "ok", "modelLoaded": true, "modelVersion": "1.0.0" }
```
The Orchestrator polls this before dispatching inference calls.

### 12.5 Explainability Format Requirements (NFR-8.2)

The signals array must contain 2-5 strings naming specific detected features:
```json
{
  "signals": [
    "Scripted hostage narrative pattern detected",
    "Caller identity claim matches known CBI impersonation template",
    "Threatening urgency language density: 82%"
  ],
  "explanation": "High-confidence digital arrest scam: scripted CBI impersonation with coercive urgency markers detected."
}
```
This text is displayed verbatim in the investigator HITL panel and stored in the intelligence package. Low-quality explanations directly degrade the demo and the legal admissibility argument.

### 12.6 Edge Model Requirements (T12b)

Quantized counterfeit detection model:
- Input: single currency note image (JPEG/PNG <=2MB)
- Output: { "isAuthentic": bool, "confidence": float, "detectedFeatures": ["string"] }
- File size: <=10MB (INT8 quantization target)
- Inference time: <=200ms on mid-range Android
- Integration: Diganta adds GET /edge/model/counterfeit to Event Processing Service returning model file for download

### 12.7 ML Evaluation Report (Required - Due Day 10, feeds directly into deck)

Produce docs/ml-evaluation-report.md containing:
- Precision, Recall, F1 per model per risk category
- Confusion matrices (at minimum scam NLP: HIGH/MEDIUM/LOW)
- Fusion improvement: show that multi-source composite score outperforms best single model. This is a direct evaluation criterion under Innovation (25%) and Technical Excellence (20%).
- Latency benchmarks: P50 and P99 per model
- Known failure modes and mitigations

This report feeds directly into the presentation deck. Judges evaluate this under Technical Excellence and Innovation.
