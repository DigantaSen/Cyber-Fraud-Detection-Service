# 4. Offline Counterfeit Sync & Conflict Resolution

Edge POS devices operate offline and sync scan logs upon regaining connectivity. This flow illustrates how the system resolves near-duplicate conflicts (e.g., multiple POS scanning the same note at the same time) using an idempotent spatial upsert.

```mermaid
sequenceDiagram
    actor POS as Edge POS Device
    participant EvProc as Event Processing
    participant Kafka
    participant GeoSvc as Geospatial Service
    participant PostGIS

    Note over POS: Device offline, logs bulk scans
    POS->>EvProc: POST /events/counterfeit-scan (Bulk Sync)
    EvProc-->>POS: 202 Accepted
    EvProc-)Kafka: Publish CounterfeitScan.Submitted
    
    Kafka-)GeoSvc: Consume CounterfeitScan.Submitted
    GeoSvc->>GeoSvc: Compute geom_hash (jurisdiction + lat/lon round)
    GeoSvc->>PostGIS: UPSERT fraud_hotspot (ON CONFLICT (geom_hash) DO UPDATE count + 1)
    PostGIS-->>GeoSvc: OK
    Note over GeoSvc,PostGIS: Conflict resolved via idempotent last-write-wins aggregation
    
    GeoSvc-)Kafka: Publish GeoLayer.Updated
```
