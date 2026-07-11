# Investigator BFF — API Contract
**Service:** `investigator-bff` | **Port:** 8000 | **Owner:** Nilkanta | **Task:** T6d
**Kong prefix:** `/api/v1/investigator` (JWT required, role: `INVESTIGATOR` or `ADMIN`)

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Architecture

The Investigator BFF is a **stateless aggregation gateway** that fans out parallel calls using `asyncio.gather` for the case detail view (case data + graph + geo + evidence in a single request). Adding more data sources only adds parallelism, not latency.

RBAC `jurisdictionId` from JWT is injected into every downstream call.

---

## Endpoints

### GET /investigator/cases
Live case queue — SSE-enhanced paginated list.

**Query params:** `cursor`, `limit`, `status`, `riskTier`, `assignedTo`, `q` (full-text search)

**BFF orchestration:** Calls `GET /search/cases` on Search Service (OpenSearch).

**Response 200:** Paginated list with facets (see [search.md](./search.md)).

---

### GET /investigator/cases/:caseId
Full case detail — parallel aggregation.

**BFF orchestration (asyncio.gather):**
```python
case_data, graph_data, geo_nearby, evidence_list = await asyncio.gather(
    case_service.get(caseId),
    graph_service.get_linkages(entityId=case.suspectPhone, hops=2),
    geo_service.get_hotspots(bbox=bbox_around_complaint),
    evidence_service.list(caseId),
)
```

**Response 200:**
```json
{
  "data": {
    "case": { ... },
    "prediction": { ... },
    "graphSummary": {
      "anchorEntity": "+919876543210",
      "totalLinkedNodes": 8,
      "totalEdges": 12,
      "fraudRingDetected": true,
      "nodes": [ ... ],
      "edges": [ ... ]
    },
    "nearbyHotspots": [ ... ],
    "evidence": [ ... ],
    "timeline": [ ... ]
  }
}
```

---

### POST /investigator/cases/:caseId/override
HITL verdict override.

**BFF orchestration:** Proxies to `PATCH /cases/:caseId/verdict/override` on Case Service.

**Request/Response:** Same as [case.md](./case.md) `PATCH /cases/:caseId/verdict/override`.

---

### GET /investigator/cases/:caseId/geo
Get geospatial hotspots near a case's complaint location.

**BFF orchestration:** Calls `GET /geo/hotspots?bbox=...` on Geospatial Service, using a ±0.05° bounding box around the case's `complaintLat`/`complaintLon`.

**Response 200:** GeoJSON FeatureCollection (see [geospatial.md](./geospatial.md)).

---

### GET /investigator/cases/:caseId/graph
Get entity graph for a case.

**BFF orchestration:** Calls `GET /graph/linkages?entityId=<suspectPhone>&hops=2` on Graph Service.

**Response 200:** Graph nodes and edges (see [graph.md](./graph.md)).

---

### POST /investigator/cases/:caseId/evidence
Upload evidence to a case.

**BFF orchestration:** Proxies to `POST /cases/:caseId/evidence` on Evidence Service.

---

### POST /investigator/reports/intelligence-package
Generate a court-admissible intelligence package.

**BFF orchestration:** Proxies to `POST /reports/intelligence-package` on Reporting Service.

**Request/Response:** Same as [reporting.md](./reporting.md).

---

### GET /investigator/stream
SSE stream for real-time dashboard updates (new cases, verdicts, HITL alerts).

**BFF orchestration:** Proxies to `GET /notify/stream` on Notification Service.

**Response:** SSE stream (see [notification.md](./notification.md)).
