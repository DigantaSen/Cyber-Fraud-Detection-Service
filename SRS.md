# Distributed Platform Software Requirements Specification (SRS)
**Project Name:** AI for Digital Public Safety (Distributed Platform)

*Note: This document strictly defines the distributed platform requirements. Machine Learning (ML) internals (model architectures, training, feature extraction) are abstracted away and managed by the independent AI Platform, communicating with this system via standardized API contracts.*

## Document Versioning
| Version | Author | Review Date | Approval Status | Change Log |
| :--- | :--- | :--- | :--- | :--- |
| 1.0 | Platform Engineering Team | 2026-07-09 | Approved | Initial baseline of distributed platform requirements. |
| 1.1 | Platform Engineering Team | 2026-07-09 | Approved | Added Edge Inference, Conversational IVR, and Real-Time Interdiction constraints. |
| 1.2 | Platform Engineering Team | 2026-07-11 | Approved | Hackathon scope adjustment: ClamAV scanning stubbed, Vault replaced by .env, PgBouncer/Schema Registry/Promtail/OTel Collector deferred to production deployment. Core FRs unchanged. |

---

## 1. Introduction
This Software Requirements Specification (SRS) documents the requirements for the distributed platform component of the AI for Digital Public Safety system.

## 2. Definitions & Acronyms
| Term | Definition |
| :--- | :--- |
| AI Platform | External ML subsystem responsible for inference (vision, graph, NLP). |
| Entity | A distinct node in the system (e.g., User, device, account, phone number). |
| Evidence | Uploaded digital artifacts (images, video, audio, PDFs). |
| Case | A formal investigation record tracked by law enforcement. |
| Prediction | An AI-generated risk assessment or classification verdict. |
| Event | An immutable business occurrence used to trigger asynchronous workflows. |
| DLQ | Dead Letter Queue, a holding queue for messages that could not be processed. |

## 3. References
The platform design and requirements are grounded in the following standards and frameworks:
*   **IEEE 29148:** Systems and software engineering — Life cycle processes — Requirements engineering.
*   **OWASP ASVS:** Application Security Verification Standard (v4.0).
*   **OAuth 2.0 / OpenID Connect:** Identity and access management protocols.
*   **RFC 9110:** HTTP Semantics.
*   **DPDP Act (India):** Digital Personal Data Protection Act, 2023.
*   **RBI Cyber Security Guidelines:** For banking integrations and fraud reporting.

## 4. Purpose
The purpose of this document is to define the functional, non-functional, and operational requirements of the highly scalable, event-driven distributed platform that orchestrates real-time fraud detection, evidence management, and law enforcement intelligence workflows.

## 5. Scope
The scope includes user management, API gateways, event processing, entity relationship management, digital evidence storage, notification routing, and orchestration of external AI platform calls. 

**Architectural Boundary:** The AI Platform is treated as an external dependency. The Distributed Platform is responsible only for orchestration, persistence, and workflow management. Model training, inference implementation, feature engineering, and explainability algorithms are strictly outside the scope of this document.

## 6. Stakeholders & Goals
| Stakeholder | Primary Goal |
| :--- | :--- |
| **Citizen** | Report fraud and verify suspicious requests quickly and easily. |
| **Investigator** | Analyze linkages and resolve cybercrime cases efficiently. |
| **Bank Official** | Reduce fraudulent transactions by acting on real-time risk scores via the Bank Portal. |
| **Telecom Administrator** | Monitor dropped calls and active interdictions via the Telecom Portal. |
| **Gov/MHA Official** | Monitor high-priority national security alerts and download intelligence packages. |
| **Platform Admin** | Maintain high availability, security, and overall platform health. |

## 7. Assumptions
*   The external AI Inference Platform is highly available and returns predictions within established latency budgets.
*   External banking core APIs and Telecom APIs are accessible and properly authenticated.
*   Government identity providers (for KYC/officer auth) are reachable.
*   Sufficient Internet connectivity is available for citizens to report incidents.

## 8. Constraints
*   **Data Residency:** All data must be physically stored within the deployment country's borders.
*   **Regulatory Compliance:** Must adhere to national data protection and banking secrecy laws.
*   **External Rate Limits:** Platform throughput is partially constrained by third-party telecom and banking API rate limits.
*   **Network Latency:** Variable network latency between telecom providers and the platform ingress gateways must be accounted for in processing timeouts.

## 9. System Context
### 9.1 Primary Actors
*   **Citizens:** Interact via mobile applications, web portals, and omnichannel bots (e.g., WhatsApp).
*   **Law Enforcement Officers:** Use the command center dashboard for case management and geospatial tracking.
*   **Bank Officials:** Use the dedicated Bank Portal (3-tab workflow: Pending Review, Blocked, Dismissed) to monitor flagged high-risk cases sorted newest-first, confirm transaction blocks with mandatory reasons, or mark No Action (Dismiss). Blocking automatically triggers real-time citizen & investigator notifications and updates case audit logs.
*   **Telecom Administrators:** Use the dedicated Telecom Portal to monitor dropped calls and active scam interdictions.
*   **Government/MHA Officials:** Use the Gov Portal to monitor high-priority alerts and NCRB reports.
*   **System Administrators:** Manage RBAC, audit logs, and platform configurations.

### 9.2 External Systems
*   **AI Inference Platform:** The subsystem executing ML models (vision, audio, graph embeddings).
*   **Telecom Provider Core:** Provide real-time call metadata streams and receive drop-call webhooks via API.
*   **Banking Core Systems:** Provide transaction logs and receive account lock commands via API.
*   **Omnichannel Gateways:** External providers (e.g., Twilio, WhatsApp Business API) for sending alerts.

## 10. Capacity Estimation & Growth
*   **Expected User Base:** 50 million registered citizens; 100,000 law enforcement personnel; 50,000 bank officials.
*   **Daily API Requests:** 10+ million synchronous requests.
*   **Peak Request Throughput:** 5,000 Requests Per Second (RPS) during peak hours (assumes 3x average load multiplier).
*   **Streaming Throughput:** 50,000 concurrent streaming events per second.
*   **Concurrent Connections:** 20,000 concurrent WebSocket/SSE connections for active dashboards.
*   **Graph Queries:** 1,000 graph traversal queries per second.
*   **Notification Volume:** 2 million SMS/Email notifications daily.
*   **Storage Growth:** ~50 TB per month (primarily Digital Evidence).
*   **Annual Data Growth:** Estimated at 20–30% year-over-year.
*   **Storage Retention:** 5–7 years for legal evidence and audit logs.
*   **Database Sizing:** Graph Database supporting 10+ billion nodes/edges.

## 11. Business Rules
*   **BR-1:** One investigation case can own multiple evidence items, but an evidence item belongs to exactly one case.
*   **BR-2:** Digital evidence cannot be mutated or hard-deleted while under active legal hold.
*   **BR-3:** Only formally assigned investigators or supervisory roles can modify the state of a case.
*   **BR-4:** AI predictions and associated confidence scores are strictly immutable after persistence.
*   **BR-5:** Every state-mutating action on a case must automatically generate a corresponding audit trail entry.
*   **BR-6:** Generated NCRB and legal reports are strictly evidentiary; once submitted externally, a report inherits immutability and cannot be silently regenerated or overwritten without explicit versioning.

## 12. Functional Requirements (FRs)

### FR-1 Identity & Access Management (IAM)
*   **FR-1.1 Authentication:** The platform shall support secure login via standard identity protocols (e.g., OAuth2/OIDC). `[Must Have]`
*   **FR-1.2 Multi-Factor Authentication:** The platform shall enforce MFA for law enforcement and bank officials. `[Must Have]`
*   **FR-1.3 Role-Based Access Control:** The platform shall enforce multi-tenancy and RBAC with strictly scoped data boundaries. `[Must Have]`
*   **FR-1.4 Organization Management:** The platform shall support hierarchical organization structures. `[Should Have]`
*   **FR-1.5 Session Management:** The platform shall manage stateless sessions with automatic expiration and concurrent device revocation. `[Must Have]`
*   **FR-1.6 Authentication Audit Logging:** The platform shall log all successful and failed authentication attempts. `[Must Have]`

### FR-2 API Gateway Management
*   **FR-2.1 Standards:** The platform shall expose RESTful APIs following standard specifications. `[Must Have]`
*   **FR-2.2 Pagination & Filtering:** List endpoints must support cursor-based pagination and dynamic filtering. `[Must Have]`
*   **FR-2.3 Idempotency:** State-mutating APIs must support idempotency keys. `[Must Have]`
*   **FR-2.4 Versioning:** APIs must be versioned to support backward compatibility. `[Must Have]`
*   **FR-2.5 Rate Limiting:** The platform shall implement IP and token-based rate limiting. `[Must Have]`
*   **FR-2.6 Standardized Responses:** Every API response shall include `requestId`, `correlationId`, `timestamp`, `status`, and `errorCode` for tracing. `[Must Have]`
*   **FR-2.7 API Design Principles:** Every API shall be stateless, validate all inputs, support versioning, and follow least-privilege authorization. `[Must Have]`

### FR-3 Data Validation
*   **FR-3.1 Schema Validation:** The platform shall validate all incoming payloads against defined JSON schemas. `[Must Have]`
*   **FR-3.2 Business Validation:** The platform shall enforce domain-specific business rules before state mutations. `[Must Have]`
*   **FR-3.3 Duplicate Detection:** The platform shall detect and reject duplicate submissions. `[Must Have]`
*   **FR-3.4 Malware Scanning:** The platform shall scan all uploaded files and evidence for malicious payloads. `[Should Have]` *Hackathon note: ClamAV container removed for startup speed. Evidence Service code path is implemented with a mock/stub response. Architecture diagram and slides show ClamAV as a production component.*
*   **FR-3.5 Content Validation:** The platform shall strictly validate MIME types and file extensions, explicitly including audio evidence formats (`.wav`, `.mp3`, `.m4a`, `.ogg`) required for voice-based scam records and call session evidence. `[Must Have]`
*   **FR-3.6 Size Validation:** The platform shall enforce maximum payload and file size limits. `[Must Have]`

### FR-4 AI Inference Orchestration
*   **FR-4.1 Request Preparation:** The platform shall aggregate user data and format it per the AI Platform contract. `[Must Have]`
*   **FR-4.2 AI Invocation:** The platform shall securely invoke external AI Platform APIs. `[Must Have]`
*   **FR-4.3 Timeout Handling:** The platform must implement strict timeouts for external AI invocations. `[Must Have]`
*   **FR-4.4 Retry Policy:** The platform shall implement exponential backoff retries for transient failures. `[Must Have]`
*   **FR-4.5 Prediction Persistence:** The platform shall normalize and persist prediction results and confidence scores. `[Must Have]`
*   **FR-4.6 AI Failure Recovery:** The platform must define fallback behaviors (e.g., manual review queues) if AI is unreachable. `[Must Have]`
*   **FR-4.7 Model Version Metadata:** The platform shall log the version of the ML model that generated the prediction. `[Should Have]`

### FR-5 Event Processing & Streaming
*   **FR-5.1 Ingestion:** The platform shall ingest high-throughput telemetry and webhooks via a distributed event streaming mechanism. `[Must Have]`
*   **FR-5.2 Delivery Guarantees:** The platform shall support 'At-least-once' delivery and handle consumer-level deduplication. `[Must Have]`
*   **FR-5.3 Dead Letter Queues (DLQ):** Failed events must be routed to a DLQ for inspection and automated replay. `[Must Have]`
*   **FR-5.4 Ordering:** The platform shall guarantee strict chronological ordering for specific domain streams. `[Should Have]`

### FR-6 Entity Relationship Management
*   **FR-6.1 Entity Persistence:** The platform shall persist nodes and edges (users, accounts, devices) in a graph database. `[Must Have]`
*   **FR-6.2 Graph Traversals:** The platform shall expose APIs for graph traversals and shortest-path queries. `[Must Have]`

### FR-7 Investigation Case Management
*   **FR-7.1 State Machine:** The platform shall track cases through a defined state machine (`New` → `Assigned` → `Investigating` → `Pending_AI` → `Action_Taken` → `Closed`). *Transition Rule: A case may re-enter Investigating from Pending_AI on AI timeout or manual override; Pending_AI is not a terminal or blocking state.* `[Must Have]`
*   **FR-7.2 Case Assignment:** The platform shall support manual and automated assignment of cases to investigators. `[Must Have]`
*   **FR-7.3 Case Escalation:** The platform shall support SLA-based escalation of stagnant cases. `[Should Have]`
*   **FR-7.4 Case Comments:** The platform shall allow authorized users to append notes and comments to a case. `[Must Have]`
*   **FR-7.5 Case Ownership Transfer:** The platform shall support transferring case ownership across jurisdictions. `[Should Have]`
*   **FR-7.6 Case Priority:** The platform shall allow dynamic prioritization of cases based on severity. `[Should Have]`
*   **FR-7.7 Timeline Generation:** The platform shall generate a chronological audit timeline for all case events and status changes. `[Must Have]`

### FR-8 Digital Evidence Management
*   **FR-8.1 Upload & Retrieval:** The platform shall securely handle evidence upload and retrieval to scalable object storage. `[Must Have]`
*   **FR-8.2 Unique Identification:** Every evidence file shall receive a globally unique, immutable Evidence ID. `[Must Have]`
*   **FR-8.3 Integrity Verification:** The platform must generate and store hashes using an industry-standard cryptographic hashing algorithm for all evidence. `[Must Have]`
*   **FR-8.4 Versioning:** The platform shall maintain versions of evidence files and associated metadata. `[Should Have]`
*   **FR-8.5 Court-Admissible Intelligence Package:** The platform shall generate structured, cryptographically signed intelligence packages — containing linked case records, evidence hashes, graph traversal exports, AI prediction audit trails, and chain-of-custody logs — suitable for direct submission as court-admissible evidence. `[Must Have]`

### FR-9 Search Capabilities
*   **FR-9.1 Full-Text Search:** The platform shall support full-text search across case notes and investigations. `[Must Have]`
*   **FR-9.2 Structured Search:** The platform shall support structured filtering on entity attributes. `[Must Have]`
*   **FR-9.3 Fuzzy Search:** The platform shall support typo-tolerant fuzzy searching for names and addresses. `[Should Have]`
*   **FR-9.4 Geospatial Search:** The platform shall support bounding-box and radius geospatial queries. `[Should Have]`
*   **FR-9.5 Faceted Search:** The platform shall support aggregated faceted search results. `[Could Have]`
*   **FR-9.6 Autocomplete:** The platform shall provide low-latency typeahead autocomplete for entity lookups. `[Could Have]`

### FR-10 Notification & Alerting
*   **FR-10.1 Omnichannel Delivery:** The platform shall support SMS, Email, Push Notifications, and Webhooks. `[Must Have]`
*   **FR-10.2 Templates:** The platform shall manage dynamic notification templates. `[Must Have]`
*   **FR-10.3 Preferences:** The platform shall respect user-defined notification preferences and quiet hours. `[Should Have]`
*   **FR-10.4 Priorities:** The platform shall support priority queues (e.g., critical alerts bypass queues). `[Must Have]`
*   **FR-10.5 Acknowledgements:** The platform shall track delivery acknowledgements (Sent, Delivered, Failed). `[Should Have]`
*   **FR-10.6 Real-time Updates:** The platform shall use Server-Sent Events (SSE) or WebSockets for real-time UI updates. `[Must Have]`
*   **FR-10.7 MHA Alert Delivery:** The platform shall support a dedicated Ministry of Home Affairs (MHA) alert webhook channel, distinct from standard citizen notifications, routing confirmed scam session events to designated law enforcement endpoints within 5 seconds of detection. `[Must Have]`

### FR-11 Conversational Bot & Citizen Reporting Channels
*   **FR-11.1 Dialogue Management:** The platform shall support a multi-turn conversational bot capable of maintaining dialogue state for citizen risk assessments across 12 languages. `[Must Have]`
*   **FR-11.2 Orchestrator Integration:** The bot service must strictly proxy all AI natural language processing through the central Inference Orchestrator to maintain a single AI integration boundary. `[Must Have]`
*   **FR-11.3 Web / Mobile Channel:** The citizen bot shall be accessible via web chat widget and mobile browser. `[Must Have — hackathon demo channel]`
*   **FR-11.4 WhatsApp Channel:** The platform shall support receiving citizen fraud reports via WhatsApp Business API webhook, normalizing incoming messages into the standard bot session format. `[Should Have]` *Hackathon: stubbed as a webhook endpoint `POST /bot/whatsapp` that echoes a structured acknowledgement response. Production wires to Meta WhatsApp Business API.*
*   **FR-11.5 IVR / Telephony Channel:** The platform shall support an IVR voice flow (DTMF + speech-to-text) for citizens to report fraud via phone call without smartphone or internet access. `[Could Have]` *Hackathon: not built. Architecture diagram shows IVR adapter as a planned integration with Twilio/Exotel connecting to the same bot session API. Demo shows the endpoint contract; voice flow is a slide.*

### FR-12 Edge Inference & Synchronization
*   **FR-12.1 Offline Execution:** The platform must support syncing quantized ML models to mobile and POS edge devices to enable offline counterfeit detection. `[Should Have]`
*   **FR-12.2 Version Skew Tolerance:** The platform must gracefully tolerate edge devices operating on stale model versions without breaking core synchronization protocols. `[Must Have]`
*   **FR-12.3 Conflict Resolution:** Offline-collected scan logs synced upon reconnection must implement a defined conflict resolution strategy (e.g., last-write-wins or manual investigator resolution) for near-duplicate records. `[Must Have]`

### FR-13 Geospatial Crime Pattern Intelligence
*   **FR-13.1 Crime Hotspot Mapping:** The platform shall maintain a geospatial data layer recording fraud complaint locations, counterfeit currency seizure points, and cybercrime hotspot coordinates indexed by administrative boundary. `[Must Have]`
*   **FR-13.2 Patrol Resource Deployment:** The platform shall expose geospatial APIs enabling law enforcement command centers to query hotspot density, recommended patrol zones, and resource deployment suggestions within defined administrative boundaries. `[Must Have]`
*   **FR-13.3 Inter-District Intelligence Sharing:** The platform shall support cross-jurisdiction geospatial data sharing, allowing investigators from different districts to query incident density maps strictly within their RBAC-authorized geographic scope. `[Must Have]`
*   **FR-13.4 Near-Real-Time Layer Updates:** The geospatial data layer must be updated within 60 seconds of a new case being created or a counterfeit scan being submitted. `[Must Have]`
*   **FR-13.5 Geospatial Export:** The platform shall support exporting geospatial intelligence layers in standard formats (e.g., GeoJSON) for integration with external mapping and patrol management tools. `[Should Have]`

### FR-14 Multi-Source Inference Fusion Orchestration
*   **FR-14.1 Parallel AI Invocation:** The Inference Orchestrator shall support parallel invocation of multiple AI Platform endpoints (e.g., Vision, NLP/Audio, Graph) for a single investigation trigger, with a configurable per-model-type timeout. `[Must Have]`
*   **FR-14.2 Fused Verdict Persistence:** The platform shall persist a unified fused prediction record aggregating individual model outputs, confidence scores, and a composite risk score, tagged with all contributing model versions and a fusion timestamp. `[Must Have]`
*   **FR-14.3 Partial Failure Handling:** If one or more AI model invocations time out or return an error, the orchestrator must persist the available partial results, mark the fused verdict as `INCOMPLETE`, and route the case to manual review without discarding any returned evidence. `[Must Have]`
*   **FR-14.4 Fusion Configuration:** The contribution weighting of individual model outputs to the composite risk score must be configurable via the Configuration Service without requiring a service restart. `[Should Have]`

## 13. Non-Functional Requirements (NFRs)

### NFR-0 Hackathon Brief Scope Gaps
*The following capabilities are explicitly called out in the hackathon evaluation brief but are currently scoped as architecture-level designs rather than fully-built features. They are documented here so judges can evaluate the completeness of the platform vision.*

*   **Video Call / Deepfake Detection (Brief §2.3):** The brief specifically cites "digital arrest" scams over video call and "deepfake identification" as evaluation tech. The current platform implements audio voice-spoof detection (Audio Analyzer ML model). A video deepfake analyzer would be integrated as a 5th ML source in the Inference Orchestrator using identical parallel fan-out and fusion patterns. `[Architecture documented; not built in hackathon]`
*   **Fraud Network Lead Time (Brief Evaluation Metric):** The brief lists "fraud network detection lead time before mass victimisation" as a judging criterion. **Platform target: fraud ring identified and MHA alert dispatched within 5 minutes of the first entity linkage being established in the graph** (measured from `Case.Created` → `Entity.RelationshipDiscovered` → `FraudRing.NodeIdentified` → `MHAAlert.Sent`). This is demonstrable via the Day 8 E2E smoke test. Added to SLO table below.

### NFR-1 Performance & Latency
*   **NFR-1.1 Synchronous API SLA:** Citizen-facing APIs must complete within < 1.5 seconds. *Note: This budget must actively account for the mandatory mTLS handshake overhead imposed by the service mesh.* `[Must Have]`
*   **NFR-1.2 Asynchronous Lag:** Background processing must not exceed a 2-second lag under normal load. `[Must Have]`
*   **NFR-1.3 Caching:** The platform shall implement a distributed caching layer to reduce API latency. `[Must Have]`

### NFR-2 Scalability & Deployment
*   **NFR-2.1 Cloud-Native:** The platform shall be containerized and orchestrated via a container orchestration platform. `[Must Have]`
*   **NFR-2.2 Auto-scaling:** Services must configure horizontal autoscaling based on utilization metrics. `[Must Have]`
*   **NFR-2.3 Zero Downtime Deployment:** The platform must support rolling updates, blue-green, and canary deployments. `[Must Have]`

### NFR-3 Service Communication & Reliability
*   **NFR-3.1 Protocols:** The platform shall support both synchronous request-response and asynchronous event-driven communication. `[Must Have]`
*   **NFR-3.2 Circuit Breakers:** The platform shall implement circuit breakers for cross-service RPC calls. `[Must Have]`
*   **NFR-3.3 Bulkhead Isolation:** The platform shall isolate critical workloads to prevent cascading resource exhaustion. `[Should Have]`
*   **NFR-3.4 Backpressure:** The platform shall handle demand spikes using backpressure mechanisms. `[Should Have]`
*   **NFR-3.5 Service Discovery:** Microservices must communicate via internal service discovery mechanisms. `[Must Have]`

### NFR-4 Availability & Disaster Recovery
*   **NFR-4.1 High Availability:** The platform aims for 99.99% uptime via multi-zone deployments. `[Must Have]`
*   **NFR-4.2 Database Replication:** Databases must run in High Availability (HA) clusters with read replicas. `[Must Have]`
*   **NFR-4.3 RTO/RPO:** The platform shall target an RTO of < 15 minutes and an RPO of < 1 minute. `[Must Have]`
*   **NFR-4.4 Graceful Degradation:** The platform shall maintain core capabilities even if non-critical subsystems fail. `[Must Have]`

### NFR-5 Observability
*   **NFR-5.1 Metrics:** The platform must expose RED metrics (Rate, Errors, Duration). `[Must Have]`
*   **NFR-5.2 Distributed Tracing:** Every request must be tagged with a unique correlation ID and traced. `[Must Have]`
*   **NFR-5.3 Centralized Logging:** Services must output structured JSON logs to a centralized stack. `[Must Have]`
*   **NFR-5.4 Health Checks:** Services must expose Readiness, Liveness, and Dependency Health APIs. `[Must Have]`

### NFR-6 Security & Compliance
*   **NFR-6.1 Immutable Logs:** Administrative actions must be written to an immutable audit log. `[Must Have]`
*   **NFR-6.2 Encryption:** Data at rest and in transit must be encrypted using industry-standard ciphers. `[Must Have]`
*   **NFR-6.3 Data Retention:** The platform must enforce strict data retention and archival policies. `[Must Have]`
*   **NFR-6.4 Legal Hold:** The platform must support locking investigative data from deletion. `[Must Have]`
*   **NFR-6.5 Right to Erasure:** The platform must support automated data deletion workflows where legally applicable. `[Must Have]`
*   **NFR-6.6 Data Portability:** The platform must support exporting user data in standard formats. `[Should Have]`
*   **NFR-6.7 Mandatory Service Mesh (mTLS):** All inter-service communication should occur over an enforced mTLS service mesh in production (Kubernetes + Istio). `[Must Have for production]` *Hackathon note: Kong handles TLS termination at the gateway layer. Inter-service HTTP is plain within the isolated Docker bridge network (`172.20.0.0/16`). Full Istio mTLS is documented in the architecture diagram for the production target.*

### NFR-7 Platform Operations
*   **NFR-7.1 Scheduled Jobs:** The platform shall support distributed, fault-tolerant cron jobs. `[Must Have]`
*   **NFR-7.2 Backup & Archival:** The platform shall support automated backup scheduling and data archival. `[Must Have]`
*   **NFR-7.3 Maintenance:** The platform shall support a maintenance mode for controlled downtime operations. `[Should Have]`
*   **NFR-7.4 Configuration Reload:** The platform shall support reloading configurations without requiring service restarts. `[Should Have]`

### NFR-8 Human-in-the-Loop & Decision Auditability
*   **NFR-8.1 Low-Confidence Override Routing:** When a fused AI verdict falls below a configurable confidence threshold, the platform must automatically route the case to a manual review queue and suppress all high-impact automated actions (e.g., account locks, citizen scam alerts, MHA webhooks) pending explicit investigator approval. `[Must Have]`
*   **NFR-8.2 Explainability Metadata Propagation:** The platform shall propagate and persist explainability metadata returned by the AI Platform (e.g., contributing feature weights per verdict), linking it immutably to the corresponding prediction record for legal and audit purposes. `[Must Have]`
*   **NFR-8.3 Citizen-Facing False Positive Gate:** Automated actions with direct citizen impact (e.g., blocking an account, issuing a public scam alert) must pass through a human-approval gate before execution, ensuring a demonstrably low false positive rate for citizen-facing outcomes. `[Must Have]`
*   **NFR-8.4 Override Audit Trail:** All investigator overrides of AI verdicts must generate an immutable override record capturing: the original AI verdict and confidence score, the override decision, the responsible investigator ID, timestamp, and a mandatory free-text justification note. `[Must Have]`

## 14. Data Ownership Map
| Domain / Service | Owned Data |
| :--- | :--- |
| Identity | Users, Roles, Sessions |
| Investigation | Cases, Assignments, Timelines |
| Evidence | Evidence Metadata, Cryptographic Hashes, Intelligence Package Artifacts |
| Entity Relationship | Graph Nodes, Edges |
| Notification | Notification History, Templates, Preferences, MHA Alert Records |
| AI Orchestrator | Prediction Requests, Fused Prediction Results, Model Metadata, Override Records |
| Audit | Immutable Audit Logs |
| **Reporting** | **Generated Report Artifacts, Export Metadata, Court-Admissible Packages** |
| **Conversational Bot** | **Dialogue Session State, Conversation History** |
| **Geospatial Intelligence** | **Crime Hotspot Layers, Patrol Zone Metadata, Jurisdiction Boundaries, GeoJSON Exports** |

## 15. Domain Event Catalog
*   `Case.Created` / `Case.Updated` / `Case.Assigned` / `Case.Closed`
*   `Evidence.Uploaded` / `Evidence.Deleted`
*   `Audio.Uploaded` / `Audio.Processed`
*   `Prediction.Requested` / `Prediction.Completed` / `Prediction.Failed` / `Prediction.Overridden`
*   `Entity.RelationshipDiscovered` / `FraudRing.NodeIdentified`
*   `Notification.Requested` / `Notification.Sent` / `Notification.Delivered` / `Notification.Failed`
*   `MHAAlert.Sent`
*   `User.Registered` / `User.LoginFailed`
*   `CallSession.Initiated` / `CallSession.Flagged`
*   `Intervention.Requested`
*   `CounterfeitScan.Submitted`
*   `GeoLayer.Updated`
*   `IntelligencePackage.Generated`
*   `Audit.Recorded`
*   `Report.Generated`
*   `TelecomEvent.Ingested`
*   `Transaction.Ingested`

## 16. External Interfaces
*   **REST/JSON:** Primary interface for Web/Mobile clients.
*   **gRPC:** Inter-service communication for low-latency operations.
*   **Server-Sent Events (SSE) / WebSockets:** Real-time dashboard updates.
*   **Webhooks:** Outbound event notification for Telecom providers.
*   **Object Storage Interface:** For direct, secure evidence uploads (e.g., S3 presigned URLs).
*   **Authentication Provider (OIDC/OAuth):** Integration with external identity providers.
*   **Email/SMS Gateway:** Outbound notification gateways.

## 17. Quality Attribute Scenarios (QAS)
*   **QAS-1 (Performance):** When a Citizen submits a suspicious payment link during peak hours (10,000 concurrent users), the platform validates, orchestrates AI inference, and returns a risk score within 1.5s (P99).
*   **QAS-2 (Availability):** When a primary database node crashes, the platform promotes a read replica and restores availability within 60s (RPO=0).
*   **QAS-3 (Scalability):** When telecom metadata spikes by 300%, event processing auto-scales horizontally within 2m to maintain < 2s consumer lag.
*   **QAS-4 (Security):** When an unauthorized user queries a restricted case, the platform blocks it (403), writes an immutable audit log within 50ms, and alerts the SOC.
*   **QAS-5 (Real-Time Latency):** When an active scam session is detected on a telecom trunk, risk classification metadata must be ingested and processed via the real-time streaming path, returning a deterministic interdiction decision within 300ms (P99) to enable pre-transfer financial blockage.

## 18. Service Level Objectives (SLO)
| Metric | Target |
| :--- | :--- |
| API Availability | 99.99% |
| API Success Rate | 99.9% |
| Event Delivery Success | 99.99% |
| Notification Delivery | 99.0% |
| AI API Timeout | < 2 sec |
| Mean Time to Recovery (MTTR) | < 15 min |
| MHA Alert Delivery Latency | < 5 sec from `CallSession.Flagged` |
| Geospatial Layer Update Latency | < 60 sec from source event |
| NCRB Report Submission | < 30 sec after `Case.Closed` |
| Manual Review Routing (Low Confidence) | < 10 sec from verdict generation |
| **Fraud Network Lead Time** | **< 5 min from first `Case.Created` to `MHAAlert.Sent` for a detected fraud ring** |
| Interdiction Path Latency (P99) | < 300 ms end-to-end (synchronous path) |

## 19. Acceptance Criteria
*   **Functional Acceptance:** All FRs must pass automated integration testing via CI/CD pipelines.
*   **Performance Acceptance:** The platform must sustain 5,000 RPS with P99 latency < 1.5s during a 4-hour load test.
*   **Security Acceptance:** The platform must pass a third-party penetration test and automated SAST/DAST scans with zero critical vulnerabilities.
*   **Reliability Acceptance:** The platform must successfully complete a chaos engineering drill (e.g., random pod termination) without violating SLOs.
*   **Scalability Acceptance:** The platform must successfully auto-scale from baseline to peak capacity within 5 minutes of a synthetic load spike.
*   **Compliance Acceptance:** The audit logs and data retention policies must be signed off by the legal/compliance team.
*   **Multilingual Acceptance:** The Conversational Bot must pass functional dialogue testing across all 12 supported regional languages with a task-completion rate ≥ 90%.
*   **Intelligence Package Acceptance:** Generated court-admissible intelligence packages must pass a legal chain-of-custody review, confirming hash integrity, signature validity, and completeness of audit trail linkage.
*   **Human-in-the-Loop Acceptance:** The platform must demonstrate that zero high-impact citizen-facing actions are executed without investigator approval when AI confidence falls below the configured threshold.

## 20. Traceability Matrix
| Requirement | Priority | Risk | Service Owner | Verification |
| :--- | :--- | :--- | :--- | :--- |
| FR-4.2 (AI Invocation) | Must | High | AI Orchestrator | Integration Test |
| FR-5.1 (Event Ingestion) | Must | High | Event Streaming Service | Load Test |
| NFR-5.2 (Distributed Tracing) | Must | Medium | Platform Core | Trace Validation Test |
| NFR-4.1 (High Availability) | Must | Critical | Platform Core | Chaos Testing |
| FR-7.1 (State Machine) | Must | Low | Case Management Service | Unit/Workflow Test |
| FR-11.1 (Dialogue Management) | Must | Medium | Conversational Bot Service | Integration Test |
| FR-11.2 (Orchestrator Proxy) | Must | High | Bot + AI Orchestrator | Contract Test |
| FR-12.1 (Offline Edge Execution) | Should | Medium | Edge Sync Module | Offline Simulation Test |
| FR-12.2 (Version Skew Tolerance) | Must | High | Edge Sync Module | Compatibility Matrix Test |
| FR-12.3 (Conflict Resolution) | Must | High | Edge Sync Module | Conflict Injection Test |
| FR-13.1 (Hotspot Mapping) | Must | Medium | Geospatial Intelligence Service | Integration + Data Freshness Test |
| FR-13.3 (Inter-District Sharing) | Must | High | Geospatial Intelligence Service | RBAC Scope Test |
| FR-13.4 (GeoLayer Update SLA < 60s) | Must | Medium | Geospatial Intelligence Service | Event-to-Layer Latency Test |
| FR-14.1 (Parallel AI Invocation) | Must | High | Inference Orchestrator | Parallelism + Timeout Test |
| FR-14.2 (Fused Verdict Persistence) | Must | High | Inference Orchestrator | Data Integrity Test |
| FR-14.3 (Partial Failure — INCOMPLETE) | Must | High | Inference Orchestrator | Fault Injection Test |
| FR-8.5 (Intelligence Package) | Must | High | Reporting + Evidence Service | Signature Verification + Legal Review |
| FR-10.7 (MHA Alert < 5s) | Must | Critical | Notification Service | End-to-End Latency Test |
| NFR-8.1 (Low-Confidence Routing) | Must | Critical | Inference Orchestrator + Case Service | Threshold Injection Test |
| NFR-8.3 (Citizen False Positive Gate) | Must | Critical | Case Service + Notification Service | Manual-Approval Gate Test |
| NFR-8.4 (Override Audit Trail) | Must | High | Audit Service | Immutability + Completeness Test |
| QAS-5 (300ms Interdiction SLA) | Must | Critical | Event Processing + AI Orchestrator | Latency Load Test (P99) |
| NFR-6.7 (Mandatory mTLS) | Must | Critical | Platform Core (Service Mesh) | mTLS Verification Scan — Production target; Kong TLS used in demo |
*(Note: Complete matrix to be fully populated during the execution and QA phases)*

## 21. Known Residual Risks
*   **RPO Delay under Load:** The Recovery Point Objective (RPO) of < 1 minute relies on asynchronous outbox replication. Under extreme load scenarios, outbox publishing may lag, posing a risk of marginal data loss during a hard failover. Strict guarantees would require synchronous write-DB replication, which trades off write latency.
*   **Single-Cluster DR Abstraction:** The current deployment architecture outlines a highly available single-cluster design. A true disaster recovery (DR) posture across multiple geographic zones requires a fully dedicated active-passive or active-active secondary cluster architecture that is abstracted from the current baseline.
