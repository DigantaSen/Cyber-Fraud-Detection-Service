# 5. Case Created to Real-Time Dashboard Push

This asynchronous flow traces how the creation of a new case propagates through the geospatial intelligence layer and is pushed in real-time to active investigator dashboards via Server-Sent Events (SSE).

```mermaid
sequenceDiagram
    participant CaseSvc as Case Service
    participant Kafka
    participant GeoSvc as Geospatial Service
    participant PostGIS
    participant NotifSvc as Notification Service
    participant IBFF as Investigator-BFF
    actor Dashboard as Investigator Dashboard

    Dashboard->>IBFF: GET /investigator/stream (SSE)
    IBFF->>NotifSvc: GET /notify/stream (SSE connection established)
    
    CaseSvc-)Kafka: Publish Case.Created
    Kafka-)GeoSvc: Consume Case.Created
    
    GeoSvc->>GeoSvc: Compute geom_hash
    GeoSvc->>PostGIS: UPSERT fraud_hotspot
    GeoSvc-)Kafka: Publish GeoLayer.Updated
    
    Kafka-)NotifSvc: Consume GeoLayer.Updated
    NotifSvc-->>IBFF: SSE Event (geo_layer_updated)
    IBFF-->>Dashboard: SSE Event (geo_layer_updated)
    Note over Dashboard: Map UI refreshes dynamically (<60s SLA)
```
