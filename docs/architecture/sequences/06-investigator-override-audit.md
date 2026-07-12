# 6. HITL Override & Immutable Audit Trail

When an investigator manually overrides an AI verdict, the system enforces RBAC, executes a state machine transition, and creates an append-only cryptographic audit log to fulfill core compliance requirements.

```mermaid
sequenceDiagram
    actor Investigator
    participant IBFF as Investigator-BFF
    participant CaseSvc as Case Service
    participant DB as PostgreSQL (Case)
    participant Kafka
    participant AuditSvc as Audit Service
    participant AuditDB as PostgreSQL (audit_log)

    Investigator->>IBFF: POST /investigator/cases/:caseId/override
    IBFF->>CaseSvc: PATCH /cases/:caseId/verdict/override
    
    CaseSvc->>CaseSvc: Validate RBAC (INVESTIGATOR or ADMIN)
    CaseSvc->>DB: Persist immutable OverrideRecord
    CaseSvc->>DB: Update Case state (Action_Taken or Closed)
    DB-->>CaseSvc: OK
    
    CaseSvc-->>IBFF: 200 OK
    IBFF-->>Investigator: 200 OK
    
    CaseSvc-)Kafka: Publish Prediction.Overridden
    Kafka-)AuditSvc: Consume Prediction.Overridden
    
    AuditSvc->>AuditDB: INSERT INTO audit_log (Append Only)
    AuditDB-->>AuditSvc: OK
    Note over AuditSvc,AuditDB: BR-5: Immutable audit trail created
```
