# Reporting Service — API Contract
**Service:** `reporting` | **Port:** 8000 | **Owner:** Nilkanta | **Task:** T6b
**Internal only** — called by Investigator BFF and Gov BFF.

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Intelligence Package Structure

A court-admissible intelligence package is a cryptographically signed JSON bundle containing:
1. Full case record snapshot
2. All evidence metadata + SHA-256 hashes
3. Neo4j graph export (nodes + edges relevant to case)
4. Full AI audit trail (all `FusedVerdict` records)
5. Chain-of-custody log (from Audit Service)

**Signing mechanism (FR-8.5):**
```python
canonical_json = json.dumps(package_dict, sort_keys=True)
digest = hashlib.sha256(canonical_json.encode()).digest()
signature = private_key.sign(digest, padding.PKCS1v15(), hashes.SHA256())
```
Returns `signatureAlgorithm: "RS256"`, `signature: base64`, `publicKeyFingerprint: sha256_of_public_key`.

---

## Endpoints

### POST /reports/ncrb
Generate an NCRB-format crime report for a closed case.

**Headers:** `Authorization: Bearer <JWT>` (role: `INVESTIGATOR`, `GOV_OFFICIAL`, `ADMIN`)
**Idempotency-Key required.**

**Request:**
```json
{
  "caseId": "uuid",
  "reportType": "NCRB_ANNUAL_CRIME",
  "notes": "Supplementary notes from investigating officer"
}
```

**Response 202:**
```json
{
  "data": {
    "reportId": "uuid",
    "status": "GENERATING",
    "estimatedReadyAt": "2026-07-11T12:00:30Z"
  }
}
```

**Events published:** `Report.Generated`

---

### POST /reports/intelligence-package
Generate a cryptographically signed court-admissible intelligence package.

**Headers:** `Authorization: Bearer <JWT>` (role: `INVESTIGATOR`, `GOV_OFFICIAL`)
**Idempotency-Key required.**

**Request:**
```json
{
  "caseId": "uuid",
  "includeGraphExport": true,
  "includeAuditTrail": true
}
```

**Response 202:**
```json
{
  "data": {
    "packageId": "uuid",
    "status": "GENERATING",
    "estimatedReadyAt": "2026-07-11T12:00:30Z"
  }
}
```

**Events published:** `IntelligencePackage.Generated`

---

### GET /reports/:reportId
Get report status and download URL.

**Response 200:**
```json
{
  "data": {
    "reportId": "uuid",
    "caseId": "uuid",
    "reportType": "NCRB_ANNUAL_CRIME",
    "status": "READY",
    "downloadUrl": "https://minio:9000/reports/uuid.pdf?... (presigned, 24h TTL)",
    "signatureAlgorithm": "RS256",
    "signature": "base64-encoded-signature",
    "publicKeyFingerprint": "sha256-of-public-key",
    "generatedAt": "2026-07-11T12:00:28Z",
    "generatedBy": "investigator-uuid"
  }
}
```

**Statuses:** `GENERATING | READY | FAILED`

---

### GET /reports
List all reports (paginated). RBAC-scoped by jurisdiction.

**Query params:** `cursor`, `limit`, `caseId`, `reportType`, `status`

**Response 200:** Paginated list of report summaries (without download URLs).
