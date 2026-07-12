# Evidence Management Service — API Contract
**Service:** `evidence` | **Port:** 8000 | **Owner:** Nilkanta | **Task:** T6a
**Internal only** — accessed by Citizen BFF and Investigator BFF.

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Upload Flow (MinIO Presigned PUT)

```
Client → POST /cases/:id/evidence → Get presigned PUT URL
Client → PUT <presigned URL> → Upload directly to MinIO (bypasses API server)
Client → POST /evidence/:id/confirm → Trigger SHA-256 + MIME validation
Service → Publish Evidence.Uploaded → Kafka
```

---

## Allowed MIME Types (FR-3.5)

| MIME | Extension |
|---|---|
| `image/png` | `.png` |
| `image/jpeg` | `.jpg`, `.jpeg` |
| `application/pdf` | `.pdf` |
| `audio/wav` | `.wav` |
| `audio/mpeg` | `.mp3` |
| `audio/m4a` | `.m4a` |
| `audio/ogg` | `.ogg` |

Max file size: **50 MB** per file. Max files per case: **20**.

---

## Endpoints

### POST /cases/:caseId/evidence
Request a presigned PUT URL to upload a file directly to MinIO.

**Headers:** `Authorization: Bearer <JWT>` | `Idempotency-Key: <uuid>`

**Request:**
```json
{
  "fileName": "scam_screenshot.png",
  "mimeType": "image/png",
  "fileSizeBytes": 204800
}
```

**Response 201:**
```json
{
  "data": {
    "evidenceId": "uuid-v4",
    "uploadUrl": "https://minio:9000/evidence/uuid-v4?X-Amz-Signature=...",
    "uploadUrlExpiresAt": "2026-07-11T12:15:00Z",
    "instructions": "PUT the file binary to uploadUrl. Then call POST /evidence/:id/confirm."
  }
}
```

**Errors:**
- `404 CASE_NOT_FOUND`
- `400 UNSUPPORTED_MIME` — MIME not in allowed list
- `400 FILE_TOO_LARGE` — exceeds 50MB
- `409 MAX_EVIDENCE_REACHED` — case already has 20 files

---

### POST /evidence/:evidenceId/confirm
Called by client after successful MinIO upload to trigger server-side validation.

**Request:**
```json
{
  "clientSha256": "abc123..."
}
```

**Response 200:**
```json
{
  "data": {
    "evidenceId": "uuid",
    "sha256": "abc123...",
    "hashMatch": true,
    "malwareScan": "CLEAN",
    "status": "VERIFIED",
    "verifiedAt": "2026-07-11T12:02:00Z"
  }
}
```

**Implementation notes:**
- Service downloads file from MinIO, computes SHA-256, compares with `clientSha256`
- Malware scan: calls `scan_file()` stub returning `{clean: true}` — **[STUB: ClamAV deferred]**
- If hash mismatch: marks evidence `CORRUPT`, deletes from MinIO, returns `422 HASH_MISMATCH`

**Events published:** `Evidence.Uploaded` (after successful verification)

---

### GET /evidence/:evidenceId
Get evidence metadata (not the file binary — use download URL for that).

**Response 200:**
```json
{
  "data": {
    "evidenceId": "uuid",
    "caseId": "uuid",
    "fileName": "scam_screenshot.png",
    "mimeType": "image/png",
    "fileSizeBytes": 204800,
    "sha256": "abc123...",
    "status": "VERIFIED",
    "uploadedBy": "user-uuid",
    "downloadUrl": "https://minio:9000/...(presigned GET, 1h TTL)",
    "createdAt": "2026-07-11T12:00:00Z"
  }
}
```

**Errors:** `404 EVIDENCE_NOT_FOUND`

---

### GET /evidence/:evidenceId/hash
Return only the stored cryptographic hash — used for court chain-of-custody verification.

**Response 200:**
```json
{
  "data": {
    "evidenceId": "uuid",
    "algorithm": "SHA-256",
    "hash": "abc123...",
    "verifiedAt": "2026-07-11T12:02:00Z"
  }
}
```

---

### GET /cases/:caseId/evidence
List all evidence items for a case (paginated).

**Response 200:** Paginated list of evidence metadata objects (without download URLs — call individual GET for those).
