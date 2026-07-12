# 2. Evidence Upload & Intelligence Package

This flow demonstrates how investigators upload binary evidence bypassing the API layer (via pre-signed URLs), trigger cryptographic hash verification, and subsequently generate a signed, court-admissible intelligence package for prosecution.

```mermaid
sequenceDiagram
    actor Investigator
    participant IBFF as Investigator-BFF
    participant EvSvc as Evidence Service
    participant MinIO
    participant Kafka
    participant RepSvc as Reporting Service

    Investigator->>IBFF: POST /investigator/cases/:id/evidence
    IBFF->>EvSvc: POST /cases/:id/evidence
    EvSvc-->>IBFF: 201 Created (uploadUrl)
    IBFF-->>Investigator: 201 Created (pre-signed PUT URL)
    
    Investigator->>MinIO: PUT file binary
    MinIO-->>Investigator: 200 OK
    
    Investigator->>IBFF: POST /investigator/evidence/:id/confirm
    IBFF->>EvSvc: POST /evidence/:id/confirm
    EvSvc->>MinIO: Fetch file
    EvSvc->>EvSvc: Compute SHA-256 & Verify Hash Match
    EvSvc->>EvSvc: Persist metadata & status = VERIFIED
    EvSvc-)Kafka: Publish Evidence.Uploaded
    EvSvc-->>IBFF: 200 OK (Verified)
    IBFF-->>Investigator: 200 OK
    
    Investigator->>IBFF: POST /investigator/reports/intelligence-package
    IBFF->>RepSvc: POST /reports/intelligence-package
    RepSvc->>RepSvc: Aggregate Case, Graph, Evidence, Audit
    RepSvc->>RepSvc: Cryptographically sign package (RS256)
    RepSvc->>MinIO: PUT signed package
    RepSvc-)Kafka: Publish IntelligencePackage.Generated
    RepSvc-->>IBFF: 202 Accepted
    IBFF-->>Investigator: 202 Accepted
```
