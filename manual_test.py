import hmac
import hashlib
import json
import urllib.request
import urllib.error
import uuid

BASE_URL = "http://127.0.0.1:8000/api/v1/events"
TELECOM_SECRET = "change_me_telecom"
BANK_SECRET = "change_me_bank"
COUNTERFEIT_SECRET = "change_me_counterfeit"

def send_request(endpoint: str, payload: dict, secret: str):
    url = f"{BASE_URL}/{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    
    # Calculate HMAC-SHA256 signature
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-HMAC-Signature": f"sha256={sig}",
        "X-Correlation-ID": f"corr-manual-{uuid.uuid4().hex[:8]}"
    }
    
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as res:
            print(f"[{endpoint.upper()}] Status Code: {res.status}")
            print(json.dumps(json.loads(res.read().decode("utf-8")), indent=2))
    except urllib.error.HTTPError as e:
        print(f"[{endpoint.upper()}] Error Code: {e.code}")
        print(json.dumps(json.loads(e.read().decode("utf-8")), indent=2))
    except Exception as e:
        print(f"[{endpoint.upper()}] Request failed: {e}")

if __name__ == "__main__":
    print("==========================================")
    print("   Starting Manual Gateway Ingestion Test ")
    print("==========================================\n")

    # 1. Telecom Async Stream
    print("1. Testing Telecom Async Webhook...")
    send_request("telecom-stream", {
        "sessionId": "sess-manual-telecom-async",
        "callerPhone": "+919999999999",
        "calleePhone": "+918888888888",
        "eventType": "CALL_INITIATED",
        "durationSeconds": 0
    }, TELECOM_SECRET)

    print("\n2. Testing Telecom Sync Interdiction Webhook...")
    # 2. Telecom Sync Interdict
    send_request("interdict", {
        "sessionId": "sess-manual-telecom-sync",
        "callerPhone": "+919999999999",
        "calleePhone": "+918888888887",
        "audioChunkBase64": "U2FtcGxlIEF1ZGlv",
        "complaintContext": "Caller impersonating electricity board officer demanding deposit"
    }, TELECOM_SECRET)

    print("\n3. Testing Bank Transaction Webhook...")
    # 3. Bank Transaction
    send_request("bank-transaction", {
        "transactionId": "tx-manual-bank-001",
        "fromAccount": "ACC-999",
        "toAccount": "ACC-888",
        "amountINR": 75000.0,
        "transactionType": "IMPS",
        "timestamp": "2026-07-14T19:00:00Z"
    }, BANK_SECRET)

    print("\n4. Testing Counterfeit Scan Webhook...")
    # 4. Counterfeit Scan
    send_request("counterfeit-scan", {
        "scanId": "scan-manual-cv-001",
        "deviceFingerprint": "dev-fingerprint-manual",
        "scannedAt": "2026-07-14T19:00:00Z",
        "denomination": 500,
        "edgeScore": 92,
        "isAuthentic": False
    }, COUNTERFEIT_SECRET)
