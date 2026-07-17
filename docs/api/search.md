# ✅ Search Service — API Contract (IMPLEMENTED)
**Service:** `search` | **Port:** 8000 | **Owner:** Diganta | **Task:** T8f
**Kong prefix:** `/api/v1/search` (JWT required, direct exposure — no BFF)

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Architecture

Search is a **CQRS read model** powered by OpenSearch. The service:
1. Maintains a Kafka consumer on `Case.Created`, `Case.Updated`, `Evidence.Uploaded`, `Prediction.Completed`
2. Upserts documents into `case_index` and `evidence_index` in OpenSearch
3. Serves all search queries against OpenSearch (never PostgreSQL)

**OpenSearch indices:**
- `case_index` — 1 shard (local), 3 shards + 1 replica (production)
- `evidence_index` — 1 shard (local)

---

## Endpoints

### GET /search/cases
Full-text, faceted, fuzzy, and geospatial case search.

**Query params:**
| Param | Type | Description |
|---|---|---|
| `q` | string | Full-text search across title, description, notes |
| `status` | string | Filter: `New|Assigned|Investigating|Pending_AI|Action_Taken|Closed` |
| `riskTier` | string | Filter: `LOW|MEDIUM|HIGH|CRITICAL` |
| `assignedTo` | uuid | Filter by investigator UUID |
| `complaintType` | string | Filter by type |
| `from` | ISO8601 | Created after |
| `to` | ISO8601 | Created before |
| `bbox` | string | `minLon,minLat,maxLon,maxLat` — geo filter (FR-9.4) |
| `fuzzy` | string | Fuzzy entity name search (FR-9.3) |
| `cursor` | string | Opaque pagination cursor |
| `limit` | integer | Default 20, max 100 |

**Response 200:**
```json
{
  "items": [
    {
      "caseId": "uuid",
      "caseNumber": "CYB-2026-00001",
      "title": "Suspected UPI fraud",
      "status": "Investigating",
      "riskTier": "HIGH",
      "fusedScore": 87.5,
      "assignedTo": "investigator-uuid",
      "jurisdictionId": "JUR_MH_MUMBAI",
      "createdAt": "2026-07-11T12:00:00Z"
    }
  ],
  "nextCursor": "eyJjcmVhdGVkX2F0IjoiMjAyNi0wNy0xMSIsImlkIjoidXVpZCJ9",
  "hasMore": true,
  "total": 347,
  "facets": {
    "status": {"New": 12, "Investigating": 89, "Closed": 246},
    "riskTier": {"LOW": 120, "MEDIUM": 98, "HIGH": 89, "CRITICAL": 40}
  }
}
```

**OpenSearch queries used:**
- `q` → `multi_match` on `title`, `description`, `notes`
- `fuzzy` → `fuzzy` query on `reporterEntityName`
- `bbox` → `geo_bounding_box` on `complaintLocation`
- `status`/`riskTier` → `term` filters
- `facets` → `terms` aggregations on `status` and `riskTier` (FR-9.5)

**RBAC:** Results automatically filtered by `jurisdictionId` from JWT claim.

---

### GET /search/evidence
Search evidence items by case or content.

**Query params:** `q`, `caseId`, `mimeType`, `cursor`, `limit`

**Response 200:** Paginated list of evidence metadata.

---

## Events Consumed (Kafka Consumer)

| Event | Action |
|---|---|
| `Case.Created` | Upsert document into `case_index` with `_id=caseId` |
| `Case.Updated` | Partial update document in `case_index` |
| `Evidence.Uploaded` | Upsert document into `evidence_index` with `_id=evidenceId` |
| `Prediction.Completed` | Update `case_index` with `fusedScore`, `riskTier`, `confidence` |
