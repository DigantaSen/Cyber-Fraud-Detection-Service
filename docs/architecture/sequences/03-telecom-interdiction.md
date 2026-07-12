# 3. Synchronous Telecom Interdiction & MHA Alert

This ultra-low-latency flow demonstrates the synchronous interception of a telecom call. The Orchestrator bypasses Kafka, directly queries specific ML models, and concurrently dispatches a network-level block and a high-priority government webhook, all within strict SLAs.

```mermaid
sequenceDiagram
    actor Telecom as Telecom Switch
    participant EvProc as Event Processing
    participant Orch as Inference Orchestrator
    participant ML as ML Platform
    participant Bank as Bank Stub
    participant NotifSvc as Notification Service
    participant Kafka
    actor MHA as Gov/MHA Portal
    participant Audit as Audit Service

    Telecom->>EvProc: POST /events/telecom-stream
    EvProc->>Orch: POST /inference/analyze (sync: true, onlyModels: scam-nlp, audio-analyzer)
    Note over Orch,ML: 200ms Budget
    par ML Analysis
        Orch->>ML: POST /ml/scam-classify
        Orch->>ML: POST /ml/audio-analyze
    end
    ML-->>Orch: Verdicts returned
    
    Orch->>Orch: Compute Fused Score (CRITICAL)
    
    par Concurrent Actions (asyncio.gather)
        Orch->>Bank: POST /block-transfer (Interdiction)
        Bank-->>Orch: 200 OK
    and
        Orch->>NotifSvc: POST /notify/mha-alert (High-Priority Bypass)
        NotifSvc->>MHA: POST Webhook (MHA Alert, <5s SLO)
        MHA-->>NotifSvc: 200 OK
    end
    
    Orch-->>EvProc: Verdict Returned
    EvProc-->>Telecom: 200 OK {decision: BLOCK}
    Note over Telecom,EvProc: Strict <300ms SLA met
    
    EvProc-)Kafka: Publish Intervention.Requested (post-response, fire-and-forget)
    Kafka-)Audit: Consume Intervention.Requested (Immutable Log)
    NotifSvc-)Kafka: Publish MHAAlert.Sent
```
