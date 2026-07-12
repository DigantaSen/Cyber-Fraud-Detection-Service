# Entity Graph Service — API Contract
**Service:** `graph` | **Port:** 8000 | **Owner:** Nilkanta | **Task:** T8c
**Internal only** — called by Inference Orchestrator (anchor query) and Investigator BFF (visualization).

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Data Model (Neo4j)

**Node types:**
- `Phone` — `{id: "+91...", country, fraudScore}`
- `BankAccount` — `{id: "ACC...", bank, fraudScore}`
- `Device` — `{id: "IMEI...", model}`
- `User` — `{id: "user-uuid", jurisdictionId}`
- `Case` — `{id: "case-uuid", riskTier}`

**Relationship types:**
- `CALLED` — Phone → Phone
- `TRANSACTED_WITH` — BankAccount → BankAccount
- `OWNS` — User → Phone / BankAccount / Device
- `LINKED_TO` — Case → Phone / BankAccount

**How the graph is built (Kafka consumer):**
Listens to `Case.Created`, `Prediction.Completed`, `TelecomEvent.Ingested`, `Transaction.Ingested`.
Uses Cypher `MERGE` statements — idempotent, never creates duplicates.

```cypher
// Example: Case.Created event
MERGE (a:Phone {id: $suspectPhone})
MERGE (b:Case {id: $caseId, riskTier: $riskTier})
MERGE (b)-[:LINKED_TO]->(a)
```

---

## Endpoints

### GET /graph/linkages
Fetch the 2-hop neighborhood of an anchor entity (used by Orchestrator — Anchor and Expand Strategy).

**Query params:**
- `entityId` (required): phone number, account number, or any entity ID
- `entityType` (optional): `PHONE|BANK_ACCOUNT|DEVICE|USER` — helps resolve ambiguity
- `hops` (optional, default=2, max=3): graph traversal depth
- `cursor`, `limit` — for pagination of nodes returned

**Response 200:**
```json
{
  "data": {
    "anchor": {
      "id": "+919876543210",
      "type": "PHONE",
      "fraudScore": 87
    },
    "nodes": [
      {"id": "+919876543211", "type": "PHONE", "fraudScore": 92, "hopsFromAnchor": 1},
      {"id": "ACC12345", "type": "BANK_ACCOUNT", "fraudScore": 65, "hopsFromAnchor": 2}
    ],
    "edges": [
      {"from": "+919876543210", "to": "+919876543211", "relation": "CALLED", "count": 47, "lastSeen": "2026-07-11T11:00:00Z"},
      {"from": "+919876543211", "to": "ACC12345", "relation": "TRANSACTED_WITH", "count": 3}
    ],
    "totalNodes": 2,
    "totalEdges": 2
  },
  "nextCursor": null,
  "hasMore": false,
  "total": 2
}
```

**Errors:**
- `404 ENTITY_NOT_FOUND` — no node with this ID in graph
- `400 MISSING_ENTITY_ID`

**Cypher executed:**
```cypher
MATCH (e:Entity {id: $entityId})-[r*1..2]-(linked)
RETURN e, r, linked
```

---

### GET /graph/shortest-path
Find the shortest path between two entities.

**Query params:** `from=<entityId>&to=<entityId>`

**Response 200:**
```json
{
  "data": {
    "found": true,
    "pathLength": 3,
    "path": [
      {"id": "+919876543210", "type": "PHONE"},
      {"relation": "CALLED"},
      {"id": "+919000000001", "type": "PHONE"},
      {"relation": "TRANSACTED_WITH"},
      {"id": "ACC99999", "type": "BANK_ACCOUNT"}
    ]
  }
}
```

**Errors:** `404 NO_PATH_FOUND` if entities are disconnected.

---

## Events Published

| Event | Trigger |
|---|---|
| `Entity.RelationshipDiscovered` | New `MERGE` edge written to Neo4j |
| `FraudRing.NodeIdentified` | Node with `fraudScore > 80` linked to ≥3 flagged nodes |
