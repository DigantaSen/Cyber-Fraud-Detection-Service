# 1. Citizen Report & AI Fusion HITL Gate

This sequence maps the flow of a citizen submitting a fraud report. The report automatically triggers an asynchronous multi-model AI evaluation. If the fused AI confidence falls below a defined threshold, the case is routed to a Human-in-the-Loop (HITL) gate for manual review.

```mermaid
sequenceDiagram
    actor Citizen
    participant CBFF as Citizen-BFF
    participant CaseSvc as Case Service
    participant Kafka
    participant Orch as Inference Orchestrator
    participant Graph as Entity Graph Svc
    participant ML as ML Platform
    actor Investigator
    participant IBFF as Investigator-BFF

    Citizen->>CBFF: POST /citizen/report
    CBFF->>CaseSvc: POST /cases
    CaseSvc-->>CBFF: 201 Created (caseId)
    CBFF-->>Citizen: 201 Created (trackingUrl)
    CaseSvc-)Kafka: Publish Case.Created

    Kafka-)Orch: Consume Case.Created
    Orch->>Graph: GET /graph/linkages (anchor=suspectPhone)
    Graph-->>Orch: 200 OK (2-hop neighborhood)
    
    par Multi-Source ML (asyncio.gather)
        Orch->>ML: POST /ml/scam-classify
        ML-->>Orch: 200 OK (score, riskTier)
    and
        Orch->>ML: POST /ml/graph-analyze
        ML-->>Orch: 200 OK (fraudRingProbability)
    end
    
    Orch->>Orch: Compute Fused Score
    Note over Orch: Confidence < 0.70 -> PENDING_REVIEW
    Orch->>Orch: Persist FusedVerdict to DB
    Orch-)Kafka: Publish Prediction.Completed
    
    Kafka-)CaseSvc: Consume Prediction.Completed
    CaseSvc->>CaseSvc: Update case status to Pending_AI
    
    Investigator->>IBFF: GET /investigator/cases/:caseId
    IBFF->>CaseSvc: GET /cases/:caseId
    CaseSvc-->>IBFF: 200 OK (Case + Prediction)
    Note over IBFF,Investigator: UI displays HITL gate (Action required)
    IBFF-->>Investigator: Display HITL gate
```
