from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
import httpx
from sse_starlette.sse import EventSourceResponse
import os, re, asyncpg
from datetime import datetime, timezone
from typing import Optional
from auth import get_current_user

router = APIRouter(prefix="/api/v1/bank")

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://notification:8000/api/v1/notify")
SEARCH_URL  = os.environ.get("SEARCH_URL",  "http://search:8000/api/v1/search/cases")
_RAW_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://platform_user:change_me_postgres@postgres:5432/platform"
).replace("postgresql+asyncpg://", "postgresql://")

_TX_DECISIONS: dict = {}

_TRANSACTIONS: dict = {
    "TXN-987654321": {
        "transactionId": "TXN-987654321", "amount": 50000.0, "currency": "INR",
        "senderAccount": "1234567890", "receiverAccount": "scammer.payee@okicici",
        "senderName": "John Doe", "receiverName": "Suspect Payee Account",
        "riskScore": 95.5, "riskTier": "CRITICAL",
        "blockReasons": ["High Risk Impersonation Pattern"], "status": "FLAGGED",
        "flaggedAt": "2026-07-20T10:00:00Z", "caseId": None,
        "reporterUserId": None, "assignedInvestigator": None,
    },
}

_RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _tx_id(text, fallback=""):
    text = text or ""
    m = re.search(r'(?:transaction\s*id|utr\s*no|ref\s*no|txn\s*no|utr|txn|ref)[-:\s#]*([A-Za-z0-9]{6,35})', text, re.IGNORECASE)
    if m and len(m.group(1)) >= 5:
        return "TXN-" + m.group(1).upper()
    t = re.search(r'\b(?:UPI|TXN|UTR)[0-9A-Z]{8,30}\b', text, re.IGNORECASE)
    if t:
        return "TXN-" + t.group(0).upper()
    return ("TXN-" + fallback) if fallback else ""


def _amount(text, payload=0.0):
    if payload and payload > 0:
        return float(payload)
    text = text or ""
    for pat, mult in [(r'(\d+(?:\.\d+)?)\s*(?:lakhs?|lacs?)', 100000), (r'(\d+(?:\.\d+)?)\s*(?:crores?)', 10000000), (r'(\d+(?:\.\d+)?)\s*(?:k\b|thousand)', 1000)]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try: return float(m.group(1)) * mult
            except: pass
    m = re.search(r'(?:Rs\.?,?|INR|[\u20b9])\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupees|rs|inr)', text, re.IGNORECASE)
    if m:
        try:
            v = float((m.group(1) or m.group(2)).replace(",",""))
            if v > 0: return v
        except: pass
    m = re.search(r'\b(?:\d{1,3}(?:,\d{2,3})+|\d{4,9})(?:\.\d+)?\b', text)
    if m:
        try:
            v = float(m.group(0).replace(",",""))
            if 100.0 <= v <= 1e8: return v
        except: pass
    return None


def _suspect(r, text):
    a = (r.get("suspectAccount") or r.get("suspect_account") or "").strip()
    if not a:
        m = re.search(r'\b[A-Za-z0-9._%+-]+@[a-zA-Z]{3,}\b', text)
        if m: a = m.group(0)
        else:
            m2 = re.search(r'\b\d{9,18}\b', text)
            if m2: a = m2.group(0)
    return a if a else None


def _build(r, seen):
    cid = str(r.get("caseId") or r.get("case_id") or "")
    if not cid or cid in seen: return None
    tier  = (r.get("riskTier") or r.get("risk_tier") or "").upper()
    score = float(r.get("fusedScore") or r.get("fused_score") or 0.0)
    if tier not in ("HIGH","CRITICAL") and score < 60.0: return None
    title = r.get("title") or ""; desc = r.get("description") or ""
    text  = title + " " + desc + " " + (r.get("summary") or r.get("explanation") or "")
    cnum  = r.get("caseNumber") or r.get("case_number") or cid[:8]
    txid  = _tx_id(text, cnum)
    if not txid: return None
    sus   = _suspect(r, text)
    if not sus: return None
    amt   = _amount(text, float(r.get("amount") or 0.0))
    if not amt or amt <= 0: return None
    dec   = _TX_DECISIONS.get(txid, {})
    uid   = str(r.get("reporterUserId") or r.get("reporter_user_id") or "")
    inv   = str(r.get("assignedInvestigator") or r.get("assigned_investigator") or "")
    base  = {
        "transactionId": txid, "amount": amt, "currency": "INR",
        "senderAccount": r.get("reporterPhone") or r.get("reporter_phone") or "9876543210",
        "receiverAccount": sus, "senderName": title[:60], "receiverName": "Suspect Payee Account",
        "riskScore": score if score > 0 else 73.0,
        "riskTier": tier if tier in ("HIGH","CRITICAL") else "HIGH",
        "blockReasons": [r.get("summary") or r.get("explanation") or "AI risk consensus"],
        "status": dec.get("status","FLAGGED"),
        "flaggedAt": r.get("createdAt") or r.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "caseId": cid, "reporterUserId": uid, "assignedInvestigator": inv,
    }
    if dec.get("status") == "BLOCKED":
        base.update({"blockedAt": dec["actionAt"], "blockedBy": dec["actionBy"], "blockReason": dec["reason"]})
    if dec.get("status") == "CLEARED":
        base.update({"dismissedAt": dec["actionAt"], "dismissedBy": dec["actionBy"], "dismissNote": dec["reason"]})
    return base


async def _pg_fetch():
    results = []
    try:
        conn = await asyncpg.connect(_RAW_DB_URL)
        try:
            rows = await conn.fetch("""
                SELECT c.case_id, c.case_number, c.title, c.description,
                       c.suspect_account, c.reporter_phone, c.reporter_user_id,
                       c.assigned_investigator, c.created_at,
                       COALESCE(v.fused_score, 0.0)            AS fused_score,
                       COALESCE(v.risk_tier,   'UNKNOWN')      AS risk_tier,
                       COALESCE(v.explanation, 'AI consensus') AS explanation
                FROM investigation.cases c
                LEFT JOIN LATERAL (
                    SELECT fused_score, risk_tier, explanation
                    FROM   inference.fused_verdicts
                    WHERE  case_id = c.case_id
                    ORDER  BY fusion_timestamp DESC LIMIT 1
                ) v ON true
                WHERE v.risk_tier IN ('HIGH','CRITICAL') OR v.fused_score >= 60
                ORDER BY c.created_at DESC LIMIT 100
            """)
            for row in rows:
                d = dict(row)
                d["caseId"]             = str(d.pop("case_id"))
                d["caseNumber"]         = d.pop("case_number")
                d["suspectAccount"]     = d.pop("suspect_account") or ""
                d["reporterPhone"]      = d.pop("reporter_phone") or ""
                d["reporterUserId"]     = str(d.pop("reporter_user_id") or "")
                d["assignedInvestigator"] = d.pop("assigned_investigator") or ""
                d["fusedScore"]         = float(d.pop("fused_score") or 0.0)
                d["riskTier"]           = d.pop("risk_tier") or "UNKNOWN"
                d["summary"]            = d.pop("explanation") or ""
                d["createdAt"]          = d["created_at"].isoformat() if d.get("created_at") else ""
                results.append(d)
        finally:
            await conn.close()
    except Exception as e:
        print(f"[bank-bff] Postgres error: {e}")
    return results


async def _search_fetch(seen):
    results = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(SEARCH_URL, params={"limit": 100})
            if r.status_code == 200:
                for item in r.json().get("data", {}).get("items", []):
                    if item.get("caseId") not in seen:
                        results.append(item)
    except Exception as e:
        print(f"[bank-bff] Search fallback: {e}")
    return results


async def fetch_db_flagged_transactions():
    items, seen = [], set()
    for r in await _pg_fetch():
        tx = _build(r, seen)
        if tx:
            seen.add(r["caseId"]); items.append(tx)
    for r in await _search_fetch(seen):
        tx = _build(r, seen)
        if tx:
            seen.add(r.get("caseId","")); items.append(tx)
    return items


async def _write_note(case_id, action, reason, by):
    if not case_id or case_id in ("None",""):
        return
    note = f"BANK_ACTION:{action}|reason:{reason}|by:{by}|at:{datetime.now(timezone.utc).isoformat()}"
    try:
        conn = await asyncpg.connect(_RAW_DB_URL)
        try:
            await conn.execute(
                "UPDATE investigation.cases SET notes = COALESCE(notes || E'\n', '') || $1 WHERE case_id = $2::uuid",
                note, case_id
            )
        finally:
            await conn.close()
    except Exception as e:
        print(f"[bank-bff] DB note error: {e}")


async def _notify(user_id, template_id, variables):
    if not user_id or user_id in ("None",""):
        return
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            await c.post(f"{NOTIFY_URL}/send", json={
                "userId": user_id, "channel": "IN_APP",
                "templateId": template_id, "variables": variables, "priority": "HIGH",
            })
    except Exception as e:
        print(f"[bank-bff] Notify error {user_id}: {e}")


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/transactions/flagged")
async def get_flagged_transactions(
    request: Request, cursor: str = None, limit: int = 50,
    riskTier: str = None, status: str = None,
    from_date: str = None, to_date: str = None,
    user=Depends(get_current_user("BANK_OFFICIAL")),
):
    db  = await fetch_db_flagged_transactions()
    ids = {t["transactionId"] for t in db}
    all_items = db + [t for t in _TRANSACTIONS.values() if t["transactionId"] not in ids]
    if riskTier: all_items = [t for t in all_items if t["riskTier"] == riskTier]
    if status:   all_items = [t for t in all_items if t["status"] == status]
    all_items.sort(key=lambda t: t.get("flaggedAt",""), reverse=True)
    return {"data": {"items": all_items[:limit], "nextCursor": None, "hasMore": False, "total": len(all_items[:limit])}}


class BlockRequest(BaseModel):
    reason: str = Field(..., min_length=5)

@router.post("/transactions/{transaction_id}/block", status_code=200)
async def block_transaction(
    transaction_id: str, body: BlockRequest, request: Request,
    user=Depends(get_current_user("BANK_OFFICIAL")),
):
    acted_by = user.get("email","bank_official")
    acted_at = datetime.now(timezone.utc).isoformat()
    all_tx   = await fetch_db_flagged_transactions()
    tx_data  = next((t for t in all_tx if t["transactionId"] == transaction_id), {})
    case_id  = tx_data.get("caseId","")
    uid      = tx_data.get("reporterUserId","")
    inv      = tx_data.get("assignedInvestigator","")
    amt      = tx_data.get("amount",0)
    sus      = tx_data.get("receiverAccount","")

    _TX_DECISIONS[transaction_id] = {"status":"BLOCKED","actionAt":acted_at,"actionBy":acted_by,"reason":body.reason}
    if transaction_id in _TRANSACTIONS:
        _TRANSACTIONS[transaction_id].update({"status":"BLOCKED","blockedAt":acted_at,"blockedBy":acted_by})

    await _write_note(case_id, "BLOCKED", body.reason, acted_by)
    await _notify(uid, "BANK_TRANSACTION_BLOCKED", {"transactionId":transaction_id,"amount":str(amt),"suspectAccount":sus,"blockedAt":acted_at,"reason":body.reason,"caseId":case_id})
    await _notify(inv, "BANK_TRANSACTION_BLOCKED_INVESTIGATOR", {"transactionId":transaction_id,"amount":str(amt),"suspectAccount":sus,"blockedAt":acted_at,"reason":body.reason,"caseId":case_id,"blockedBy":acted_by})

    return {"data":{"transactionId":transaction_id,"status":"BLOCKED","blockedAt":acted_at,"blockedBy":acted_by,"reason":body.reason,"message":f"Transaction {transaction_id} blocked. Citizen & investigator notified."}}


class DismissRequest(BaseModel):
    note: str = Field(default="No action taken by bank", min_length=3)

@router.post("/transactions/{transaction_id}/dismiss", status_code=200)
async def dismiss_transaction(
    transaction_id: str, body: DismissRequest, request: Request,
    user=Depends(get_current_user("BANK_OFFICIAL")),
):
    acted_by = user.get("email","bank_official")
    acted_at = datetime.now(timezone.utc).isoformat()
    all_tx   = await fetch_db_flagged_transactions()
    tx_data  = next((t for t in all_tx if t["transactionId"] == transaction_id), {})
    case_id  = tx_data.get("caseId","")

    _TX_DECISIONS[transaction_id] = {"status":"CLEARED","actionAt":acted_at,"actionBy":acted_by,"reason":body.note}
    if transaction_id in _TRANSACTIONS:
        _TRANSACTIONS[transaction_id]["status"] = "CLEARED"

    await _write_note(case_id, "DISMISSED", body.note, acted_by)
    return {"data":{"transactionId":transaction_id,"status":"CLEARED","dismissedAt":acted_at,"dismissedBy":acted_by,"note":body.note}}


@router.get("/stream")
async def stream_bank_events(request: Request, user=Depends(get_current_user("BANK_OFFICIAL"))):
    async def gen():
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                hdrs = {"X-User-Role":"BANK_OFFICIAL"}
                if "jurisdictionId" in user: hdrs["X-Jurisdiction-Id"] = user["jurisdictionId"]
                async with c.stream("GET", f"{NOTIFY_URL}/stream", headers=hdrs) as resp:
                    async for line in resp.aiter_lines():
                        if line: yield line
        except httpx.RequestError:
            yield "event: error\ndata: notification service unavailable\n\n"
    return EventSourceResponse(gen())
