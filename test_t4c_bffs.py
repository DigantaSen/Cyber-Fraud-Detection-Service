"""
T4c — Department BFFs Comprehensive Test Suite
================================================
Tests all endpoints across Bank BFF, Telecom BFF, and Gov BFF.

Endpoints under test:
  Bank BFF     (/api/v1/bank/)
    GET  /transactions/flagged       → BANK_OFFICIAL only
    GET  /stream                     → BANK_OFFICIAL only, SSE

  Telecom BFF  (/api/v1/telecom/)
    GET  /sessions/active            → TELECOM_ADMIN only
    GET  /stream                     → TELECOM_ADMIN only, SSE

  Gov BFF      (/api/v1/gov/)
    GET  /alerts                     → GOV_OFFICIAL only
    GET  /reports                    → GOV_OFFICIAL only
    POST /reports/intelligence-package → GOV_OFFICIAL only
    GET  /stream                     → GOV_OFFICIAL only, SSE

  BFF Health
    GET  /health/live
    GET  /health/ready

Auth tests (via Kong gateway):
  - No token → 401
  - Wrong role token → 403
  - Expired/invalid token → 401
  - Correct role token → 200

Run:
    python test_t4c_bffs.py
"""

import urllib.request
import urllib.error
import json
import uuid
import socket
import threading
import sys
import time

BASE_KONG = "http://localhost:8000"     # Kong API Gateway
BASE_AUTH = f"{BASE_KONG}/api/v1/auth"

# ─── ANSI Colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = 0
failed = 0
skipped = 0

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _req(method: str, url: str, body=None, headers=None, timeout=10):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, json.loads(raw) if raw else {}
    except Exception as e:
        return 0, {"error": str(e)}

def get(url, headers=None, timeout=10):
    return _req("GET", url, headers=headers, timeout=timeout)

def post(url, body=None, headers=None, timeout=10):
    return _req("POST", url, body=body, headers=headers, timeout=timeout)

def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

# ─── Test runner ───────────────────────────────────────────────────────────────

def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  {GREEN}✔{RESET}  {name}")
    else:
        failed += 1
        print(f"  {RED}✘{RESET}  {name}")
        if detail:
            print(f"        {RED}→ {detail}{RESET}")

def section(title: str):
    print(f"\n{CYAN}{BOLD}{'─'*60}{RESET}")
    print(f"{CYAN}{BOLD}  {title}{RESET}")
    print(f"{CYAN}{BOLD}{'─'*60}{RESET}")

def skip(name: str, reason: str):
    global skipped
    skipped += 1
    print(f"  {YELLOW}~{RESET}  {name} [{YELLOW}SKIPPED{RESET}: {reason}]")

# ─── Token factory ─────────────────────────────────────────────────────────────

_token_cache = {}

def get_token(role: str, email: str, password: str, phone="+919000000001") -> str | None:
    if role in _token_cache:
        return _token_cache[role]

    idem = str(uuid.uuid4())
    s, _ = post(f"{BASE_AUTH}/register", {
        "email": email, "password": password, "phone": phone,
        "role": role, "jurisdiction_id": "JUR_MH_MUMBAI"
    }, {"Idempotency-Key": idem})
    # 201 = created, 409 = already exists (both fine)
    if s not in (201, 409):
        print(f"  {YELLOW}  Could not register {role} ({s}){RESET}")

    s2, b2 = post(f"{BASE_AUTH}/login", {"email": email, "password": password})
    if s2 != 200:
        print(f"  {RED}  Login failed for {role}: {s2} {b2}{RESET}")
        return None

    token = b2.get("data", {}).get("access_token")
    if token:
        _token_cache[role] = token
    return token

INVALID_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.totally.invalid"

# ─── SSE helper ────────────────────────────────────────────────────────────────

def check_sse_connects(url: str, token: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Returns (connected: bool, first_line: str). Uses raw socket to check SSE."""
    try:
        parsed = urllib.request.urlparse(url) if hasattr(urllib.request, "urlparse") else None
        from urllib.parse import urlparse
        p = urlparse(url)
        host = p.hostname
        port = p.port or 80
        path_qs = f"{p.path}?{p.query}" if p.query else p.path

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(
            f"GET {path_qs} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Connection: close\r\n\r\n".encode()
        )
        # Read response header
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = s.recv(512)
            if not chunk:
                break
            response += chunk
        header = response.decode(errors="replace")
        status_line = header.split("\r\n")[0]
        status_code = int(status_line.split(" ")[1]) if " " in status_line else 0

        # Read a little body
        body_chunk = b""
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                s.settimeout(1.0)
                chunk = s.recv(512)
                if chunk:
                    body_chunk += chunk
                else:
                    break
            except socket.timeout:
                break
        s.close()

        first_body = body_chunk.decode(errors="replace")
        return status_code == 200, f"HTTP {status_code} | body_start={first_body[:60]!r}"
    except Exception as e:
        return False, str(e)

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUPS
# ══════════════════════════════════════════════════════════════════════════════

def test_health():
    section("BFF Health Endpoints")
    # We hit the BFF directly via Kong prefix — /api/v1/bank/../health won't
    # work; health is at the BFF container level. Kong doesn't expose it.
    # We'll call via docker-internal port but Kong should be enough to confirm
    # the service is up (any 200 route proves it).
    s, b = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged")
    # 401 means BFF is reachable (just unauthenticated) — that's fine
    check("BFF reachable via Kong (bank route returns 4xx not 502)", s in (401, 403, 200),
          f"Got {s}")


def test_bank_auth():
    section("Bank BFF — Authentication & Authorization")

    # ── 1. No token → 401
    s, b = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged")
    check("GET /bank/transactions/flagged — no token → 401", s == 401, f"got {s}")

    # ── 2. Invalid token → 401
    s, b = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged", auth_header(INVALID_TOKEN))
    check("GET /bank/transactions/flagged — invalid token → 401", s == 401, f"got {s}")

    # ── 3. Wrong role (TELECOM_ADMIN) → 403
    telecom_token = get_token("TELECOM_ADMIN", "t4c.telecom@fraud.gov.in", "Telecom@T4c!", "+919001000001")
    if telecom_token:
        s, b = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged", auth_header(telecom_token))
        check("GET /bank/transactions/flagged — wrong role (TELECOM_ADMIN) → 403", s == 403, f"got {s} body={str(b)[:80]}")
    else:
        skip("Wrong role → 403", "Could not obtain TELECOM_ADMIN token")

    # ── 4. Correct role → 200
    bank_token = get_token("BANK_OFFICIAL", "t4c.bank@fraud.gov.in", "BankOff@T4c!", "+919001000002")
    if bank_token:
        s, b = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged", auth_header(bank_token))
        check("GET /bank/transactions/flagged — correct role (BANK_OFFICIAL) → 200", s == 200, f"got {s} body={str(b)[:100]}")
        return bank_token
    else:
        skip("Correct role → 200", "Could not obtain BANK_OFFICIAL token")
        return None


def test_bank_data(bank_token: str | None):
    section("Bank BFF — Data Shape & Content")
    if not bank_token:
        skip("All data tests", "No BANK_OFFICIAL token available")
        return

    s, b = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged", auth_header(bank_token))
    check("Response is 200", s == 200, f"got {s}")

    data = b.get("data", {})
    check("Response has 'data' envelope", "data" in b, f"keys={list(b.keys())}")
    check("Response.data has 'items' list", "items" in data, f"data keys={list(data.keys())}")
    check("Response.data has 'total' field", "total" in data, f"data keys={list(data.keys())}")

    items = data.get("items", [])
    check("At least one transaction returned", len(items) > 0, "items list is empty")

    if items:
        tx = items[0]
        required_fields = [
            "transactionId", "amount", "currency",
            "senderAccount", "receiverAccount", "senderName", "receiverName",
            "riskScore", "riskTier", "blockReasons", "status", "flaggedAt"
        ]
        for field in required_fields:
            check(f"Transaction has field '{field}'", field in tx,
                  f"missing from tx keys: {list(tx.keys())}")

        check("riskTier is valid enum", tx.get("riskTier") in ("LOW", "MEDIUM", "HIGH", "CRITICAL"),
              f"got {tx.get('riskTier')}")
        check("riskScore is numeric 0-100", isinstance(tx.get("riskScore"), (int, float)) and 0 <= tx["riskScore"] <= 100,
              f"got {tx.get('riskScore')}")
        check("status is valid enum", tx.get("status") in ("FLAGGED", "UNDER_REVIEW", "BLOCKED", "CLEARED"),
              f"got {tx.get('status')}")
        check("blockReasons is a list", isinstance(tx.get("blockReasons"), list),
              f"got {type(tx.get('blockReasons'))}")

    # ── riskTier filter
    s2, b2 = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged?riskTier=CRITICAL", auth_header(bank_token))
    check("GET /bank/transactions/flagged?riskTier=CRITICAL → 200", s2 == 200, f"got {s2}")

    # ── pagination params accepted
    s3, b3 = get(f"{BASE_KONG}/api/v1/bank/transactions/flagged?limit=5", auth_header(bank_token))
    check("GET /bank/transactions/flagged?limit=5 → 200", s3 == 200, f"got {s3}")


def test_bank_sse(bank_token: str | None):
    section("Bank BFF — SSE Stream")
    if not bank_token:
        skip("All SSE tests", "No BANK_OFFICIAL token available")
        return

    # ── no token → 401
    connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/bank/stream", INVALID_TOKEN)
    check("GET /bank/stream — invalid token → not 200", not connected or "401" in detail or "403" in detail,
          detail)

    # ── valid token → SSE opens (200)
    connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/bank/stream", bank_token, timeout=8)
    check("GET /bank/stream — valid BANK_OFFICIAL token → 200 SSE opened", connected, detail)

    # ── wrong role → 403
    telecom_token = _token_cache.get("TELECOM_ADMIN")
    if telecom_token:
        connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/bank/stream", telecom_token)
        check("GET /bank/stream — wrong role (TELECOM_ADMIN) → not 200", not connected or "403" in detail,
              detail)
    else:
        skip("Wrong role SSE test", "No TELECOM_ADMIN token cached")


def test_telecom_auth():
    section("Telecom BFF — Authentication & Authorization")

    # ── 1. No token → 401
    s, b = get(f"{BASE_KONG}/api/v1/telecom/sessions/active")
    check("GET /telecom/sessions/active — no token → 401", s == 401, f"got {s}")

    # ── 2. Invalid token → 401
    s, b = get(f"{BASE_KONG}/api/v1/telecom/sessions/active", auth_header(INVALID_TOKEN))
    check("GET /telecom/sessions/active — invalid token → 401", s == 401, f"got {s}")

    # ── 3. Wrong role (BANK_OFFICIAL) → 403
    bank_token = _token_cache.get("BANK_OFFICIAL")
    if bank_token:
        s, b = get(f"{BASE_KONG}/api/v1/telecom/sessions/active", auth_header(bank_token))
        check("GET /telecom/sessions/active — wrong role (BANK_OFFICIAL) → 403", s == 403, f"got {s}")
    else:
        skip("Wrong role → 403", "No BANK_OFFICIAL token cached")

    # ── 4. Correct role → 200
    telecom_token = _token_cache.get("TELECOM_ADMIN") or get_token(
        "TELECOM_ADMIN", "t4c.telecom@fraud.gov.in", "Telecom@T4c!", "+919001000001"
    )
    if telecom_token:
        s, b = get(f"{BASE_KONG}/api/v1/telecom/sessions/active", auth_header(telecom_token))
        check("GET /telecom/sessions/active — correct role → 200", s == 200, f"got {s}")
        return telecom_token
    else:
        skip("Correct role → 200", "Could not obtain TELECOM_ADMIN token")
        return None


def test_telecom_data(telecom_token: str | None):
    section("Telecom BFF — Data Shape & Content")
    if not telecom_token:
        skip("All data tests", "No TELECOM_ADMIN token available")
        return

    s, b = get(f"{BASE_KONG}/api/v1/telecom/sessions/active", auth_header(telecom_token))
    check("Response is 200", s == 200, f"got {s}")

    data = b.get("data", {})
    check("Response has 'data' envelope", "data" in b, f"keys={list(b.keys())}")
    check("Response.data has 'items' list", "items" in data, f"data keys={list(data.keys())}")
    check("Response.data has 'total' field", "total" in data, f"data keys={list(data.keys())}")

    items = data.get("items", [])
    check("At least one session returned", len(items) > 0, "items list is empty")

    if items:
        sess = items[0]
        required_fields = [
            "sessionId", "callerNumber", "calleeNumber", "duration",
            "riskScore", "riskTier", "flaggedAt", "status", "flagReasons"
        ]
        for field in required_fields:
            check(f"Session has field '{field}'", field in sess,
                  f"missing from sess keys: {list(sess.keys())}")

        check("riskTier is valid enum", sess.get("riskTier") in ("LOW", "MEDIUM", "HIGH", "CRITICAL"),
              f"got {sess.get('riskTier')}")
        check("riskScore is numeric 0-100", isinstance(sess.get("riskScore"), (int, float)) and 0 <= sess["riskScore"] <= 100,
              f"got {sess.get('riskScore')}")
        check("status is valid enum", sess.get("status") in ("ACTIVE", "ENDED", "BLOCKED"),
              f"got {sess.get('status')}")
        check("flagReasons is a list", isinstance(sess.get("flagReasons"), list),
              f"got {type(sess.get('flagReasons'))}")
        check("callerNumber starts with +", str(sess.get("callerNumber", "")).startswith("+"),
              f"got {sess.get('callerNumber')}")
        check("duration is non-negative int", isinstance(sess.get("duration"), (int, float)) and sess["duration"] >= 0,
              f"got {sess.get('duration')}")

    # ── pagination param accepted
    s2, b2 = get(f"{BASE_KONG}/api/v1/telecom/sessions/active?limit=5", auth_header(telecom_token))
    check("GET /telecom/sessions/active?limit=5 → 200", s2 == 200, f"got {s2}")


def test_telecom_sse(telecom_token: str | None):
    section("Telecom BFF — SSE Stream")
    if not telecom_token:
        skip("All SSE tests", "No TELECOM_ADMIN token available")
        return

    # ── no/invalid token → not 200
    connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/telecom/stream", INVALID_TOKEN)
    check("GET /telecom/stream — invalid token → not 200", not connected or "401" in detail or "403" in detail,
          detail)

    # ── valid token → SSE opens
    connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/telecom/stream", telecom_token, timeout=8)
    check("GET /telecom/stream — valid TELECOM_ADMIN token → 200 SSE opened", connected, detail)

    # ── wrong role → 403
    bank_token = _token_cache.get("BANK_OFFICIAL")
    if bank_token:
        connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/telecom/stream", bank_token)
        check("GET /telecom/stream — wrong role (BANK_OFFICIAL) → not 200", not connected or "403" in detail,
              detail)
    else:
        skip("Wrong role SSE test", "No BANK_OFFICIAL token cached")


def test_gov_auth():
    section("Gov BFF — Authentication & Authorization")

    # ── 1. No token → 401
    s, b = get(f"{BASE_KONG}/api/v1/gov/alerts")
    check("GET /gov/alerts — no token → 401", s == 401, f"got {s}")

    # ── 2. Invalid token → 401
    s, b = get(f"{BASE_KONG}/api/v1/gov/alerts", auth_header(INVALID_TOKEN))
    check("GET /gov/alerts — invalid token → 401", s == 401, f"got {s}")

    # ── 3. Wrong role → 403
    bank_token = _token_cache.get("BANK_OFFICIAL")
    if bank_token:
        s, b = get(f"{BASE_KONG}/api/v1/gov/alerts", auth_header(bank_token))
        check("GET /gov/alerts — wrong role (BANK_OFFICIAL) → 403", s == 403, f"got {s}")
    else:
        skip("Wrong role → 403", "No BANK_OFFICIAL token cached")

    # ── 4. Correct role → 2xx (200 or 502 if reporting is down)
    gov_token = get_token("GOV_OFFICIAL", "t4c.gov@fraud.gov.in", "GovOff@T4c!", "+919001000003")
    if gov_token:
        s, b = get(f"{BASE_KONG}/api/v1/gov/alerts", auth_header(gov_token))
        check("GET /gov/alerts — correct role (GOV_OFFICIAL) → not 401/403", s not in (401, 403),
              f"got {s}")
        return gov_token
    else:
        skip("Correct role → not 401/403", "Could not obtain GOV_OFFICIAL token")
        return None


def test_gov_data(gov_token: str | None):
    section("Gov BFF — Endpoints & Data")
    if not gov_token:
        skip("All data tests", "No GOV_OFFICIAL token available")
        return

    # ── GET /gov/alerts
    s, b = get(f"{BASE_KONG}/api/v1/gov/alerts", auth_header(gov_token))
    check("GET /gov/alerts — reachable (2xx or 5xx from downstream)", s != 401 and s != 403, f"got {s}")
    if s == 200:
        check("GET /gov/alerts — returns list-like body", "items" in b or "data" in b, f"keys={list(b.keys())}")

    # ── GET /gov/reports
    s2, b2 = get(f"{BASE_KONG}/api/v1/gov/reports", auth_header(gov_token))
    check("GET /gov/reports — reachable (auth passes)", s2 not in (401, 403), f"got {s2}")

    # ── POST /gov/reports/intelligence-package
    s3, b3 = post(f"{BASE_KONG}/api/v1/gov/reports/intelligence-package",
                  {"caseId": str(uuid.uuid4()), "jurisdictionId": "JUR_MH_MUMBAI"},
                  auth_header(gov_token))
    check("POST /gov/reports/intelligence-package — auth passes (not 401/403)",
          s3 not in (401, 403), f"got {s3} body={str(b3)[:80]}")

    # ── Wrong role for gov reports
    bank_token = _token_cache.get("BANK_OFFICIAL")
    if bank_token:
        s4, _ = get(f"{BASE_KONG}/api/v1/gov/reports", auth_header(bank_token))
        check("GET /gov/reports — wrong role → 403", s4 == 403, f"got {s4}")

    # ── Pagination params
    s5, _ = get(f"{BASE_KONG}/api/v1/gov/alerts?limit=5", auth_header(gov_token))
    check("GET /gov/alerts?limit=5 → not 4xx auth error", s5 not in (401, 403), f"got {s5}")


def test_gov_sse(gov_token: str | None):
    section("Gov BFF — SSE Stream")
    if not gov_token:
        skip("All SSE tests", "No GOV_OFFICIAL token available")
        return

    # ── invalid token → not 200
    connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/gov/stream", INVALID_TOKEN)
    check("GET /gov/stream — invalid token → not 200", not connected or "401" in detail or "403" in detail,
          detail)

    # ── valid token → SSE opens
    connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/gov/stream", gov_token, timeout=8)
    check("GET /gov/stream — valid GOV_OFFICIAL token → 200 SSE opened", connected, detail)

    # ── wrong role
    bank_token = _token_cache.get("BANK_OFFICIAL")
    if bank_token:
        connected, detail = check_sse_connects(f"{BASE_KONG}/api/v1/gov/stream", bank_token)
        check("GET /gov/stream — wrong role (BANK_OFFICIAL) → not 200",
              not connected or "403" in detail, detail)


def test_cross_bff_isolation():
    section("Cross-BFF Role Isolation")
    bank_token    = _token_cache.get("BANK_OFFICIAL")
    telecom_token = _token_cache.get("TELECOM_ADMIN")
    gov_token     = _token_cache.get("GOV_OFFICIAL")

    combos = [
        (bank_token,    "BANK_OFFICIAL",    f"{BASE_KONG}/api/v1/telecom/sessions/active"),
        (bank_token,    "BANK_OFFICIAL",    f"{BASE_KONG}/api/v1/gov/alerts"),
        (telecom_token, "TELECOM_ADMIN",    f"{BASE_KONG}/api/v1/bank/transactions/flagged"),
        (telecom_token, "TELECOM_ADMIN",    f"{BASE_KONG}/api/v1/gov/alerts"),
        (gov_token,     "GOV_OFFICIAL",     f"{BASE_KONG}/api/v1/bank/transactions/flagged"),
        (gov_token,     "GOV_OFFICIAL",     f"{BASE_KONG}/api/v1/telecom/sessions/active"),
    ]
    for token, role, url in combos:
        if not token:
            endpoint = url.split("/api/v1/")[1]
            skip(f"{role} → {endpoint}", "token unavailable")
            continue
        s, _ = get(url, auth_header(token))
        endpoint = url.split("/api/v1/")[1]
        check(f"{role} → {endpoint} → 403 (cross-BFF blocked)", s == 403, f"got {s}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  T4c — Department BFFs Test Suite{RESET}")
    print(f"{BOLD}  Target: {BASE_KONG}{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}")

    # Health / reachability
    test_health()

    # Bank BFF
    bank_token = test_bank_auth()
    test_bank_data(bank_token)
    test_bank_sse(bank_token)

    # Telecom BFF
    telecom_token = test_telecom_auth()
    test_telecom_data(telecom_token)
    test_telecom_sse(telecom_token)

    # Gov BFF
    gov_token = test_gov_auth()
    test_gov_data(gov_token)
    test_gov_sse(gov_token)

    # Cross-BFF isolation
    test_cross_bff_isolation()

    # ── Summary ────────────────────────────────────────────────────────────────
    total = passed + failed + skipped
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  RESULTS{RESET}")
    print(f"{'─'*60}")
    print(f"  {GREEN}{BOLD}Passed : {passed}{RESET}")
    print(f"  {RED}{BOLD}Failed : {failed}{RESET}")
    print(f"  {YELLOW}{BOLD}Skipped: {skipped}{RESET}")
    print(f"  {BOLD}Total  : {total}{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}\n")

    if failed == 0:
        print(f"{GREEN}{BOLD}  ✔ T4c COMPLETE — All checks passed!{RESET}\n")
    else:
        print(f"{RED}{BOLD}  ✘ T4c has {failed} failing check(s). Review above.{RESET}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
