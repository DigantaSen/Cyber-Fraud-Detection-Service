"""
T8f Search Service — Manual Verification Script

Runs through the full verification plan:
1. Seeds a test case document directly into OpenSearch
2. Verifies full-text search (q=)
3. Verifies keyword filter (status=, riskTier=)
4. Verifies faceted aggregations
5. Verifies geo bounding box filter
6. Verifies cursor pagination
7. Queries through Kong gateway (port 8000)
"""

import json
import requests

OPENSEARCH_URL = "http://127.0.0.1:9200"
SEARCH_URL = "http://127.0.0.1:8006"
KONG_URL = "http://127.0.0.1:8000"

PASS = "[PASS]"
FAIL = "[FAIL]"

def p(label, ok, detail=""):
    status = PASS if ok else FAIL
    print(f"  {status}  {label}")
    if not ok and detail:
        print(f"         -> {detail[:120]}")

def seed_test_data():
    """Directly seed test documents into OpenSearch."""
    docs = [
        {
            "id": "case-search-001",
            "doc": {
                "caseId": "case-search-001",
                "caseNumber": "CYB-2026-00001",
                "title": "Suspected UPI fraud via impersonation",
                "description": "Victim received a call from a person impersonating a bank officer requesting OTP",
                "notes": "Suspect linked to fraud ring in Mumbai",
                "status": "Investigating",
                "riskTier": "HIGH",
                "fusedScore": 87.5,
                "confidence": 0.93,
                "jurisdictionId": "JUR_MH_MUMBAI",
                "assignedInvestigator": "inv-001",
                "complaintType": "UPI_FRAUD",
                "reporterPhone": "+919876543210",
                "reporterEntityName": "Rajesh Kumar",
                "complaintLocation": {"lat": 19.076, "lon": 72.877},
                "createdAt": "2026-07-17T06:00:00Z",
                "updatedAt": "2026-07-17T06:00:00Z",
            }
        },
        {
            "id": "case-search-002",
            "doc": {
                "caseId": "case-search-002",
                "caseNumber": "CYB-2026-00002",
                "title": "Counterfeit currency detected at ATM",
                "description": "High-denomination counterfeit notes detected by edge scanner",
                "notes": "",
                "status": "New",
                "riskTier": "CRITICAL",
                "fusedScore": 96.0,
                "confidence": 0.99,
                "jurisdictionId": "JUR_DL_CENTRAL",
                "assignedInvestigator": "",
                "complaintType": "COUNTERFEIT",
                "reporterPhone": "+918765432109",
                "reporterEntityName": "HDFC Bank ATM",
                "complaintLocation": {"lat": 28.614, "lon": 77.209},
                "createdAt": "2026-07-16T10:00:00Z",
                "updatedAt": "2026-07-16T10:00:00Z",
            }
        },
    ]
    for item in docs:
        r = requests.put(
            f"{OPENSEARCH_URL}/case_index/_doc/{item['id']}",
            json=item["doc"]
        )
        assert r.status_code in (200, 201), f"Seed failed: {r.text}"
    
    # Force refresh so documents are immediately searchable
    requests.post(f"{OPENSEARCH_URL}/case_index/_refresh")
    print("  Seeded 2 test case documents\n")


print("=" * 55)
print("   T8f Search Service — Verification")
print("=" * 55)

# ── Step 1: Health ─────────────────────────────────────────────
print("\n1. Health Check")
r = requests.get(f"{SEARCH_URL}/health/ready")
p("/health/ready returns 200", r.status_code == 200)
p("OpenSearch status is green/yellow", r.json().get("opensearch") in ("green", "yellow"), r.text)

# ── Step 2: Seed ───────────────────────────────────────────────
print("\n2. Seeding test data into OpenSearch...")
seed_test_data()

# ── Step 3: Full-text search ───────────────────────────────────
print("\n3. Full-text Search (q=UPI fraud)")
r = requests.get(f"{SEARCH_URL}/api/v1/search/cases", params={"q": "UPI fraud"})
p("Returns 200", r.status_code == 200, r.text[:200])
data = r.json().get("data", {})
p("Returns items list", isinstance(data.get("items"), list), str(data))
p("Found case-search-001", any(i.get("caseId") == "case-search-001" for i in data.get("items", [])))
p("Returns facets", "status" in data.get("facets", {}), str(data.get("facets")))
p("Returns total", isinstance(data.get("total"), int))

# ── Step 4: Keyword filter ─────────────────────────────────────
print("\n4. Keyword Filter (status=New, riskTier=CRITICAL)")
r = requests.get(f"{SEARCH_URL}/api/v1/search/cases", params={"status": "New", "riskTier": "CRITICAL"})
p("Returns 200", r.status_code == 200)
data = r.json().get("data", {})
p("Found case-search-002", any(i.get("caseId") == "case-search-002" for i in data.get("items", [])))
p("Did NOT return case-search-001", not any(i.get("caseId") == "case-search-001" for i in data.get("items", [])))

# ── Step 5: Geo bounding box filter ───────────────────────────
print("\n5. Geo Bounding Box (Mumbai area)")
# Mumbai bounding box: roughly lon 72.7-73.1, lat 18.9-19.2
r = requests.get(f"{SEARCH_URL}/api/v1/search/cases", params={"bbox": "72.7,18.9,73.1,19.2"})
p("Returns 200", r.status_code == 200)
data = r.json().get("data", {})
p("Found Mumbai case", any(i.get("caseId") == "case-search-001" for i in data.get("items", [])))
p("Did NOT return Delhi case", not any(i.get("caseId") == "case-search-002" for i in data.get("items", [])))

# ── Step 6: Cursor pagination ──────────────────────────────────
print("\n6. Cursor Pagination (limit=1)")
r = requests.get(f"{SEARCH_URL}/api/v1/search/cases", params={"limit": 1})
p("Returns 200", r.status_code == 200)
data = r.json().get("data", {})
p("Returns exactly 1 item", len(data.get("items", [])) == 1)
p("hasMore=True when results > limit", data.get("hasMore") is True)
p("nextCursor is provided", data.get("nextCursor") is not None)

# Fetch page 2 using cursor
cursor = data.get("nextCursor")
r2 = requests.get(f"{SEARCH_URL}/api/v1/search/cases", params={"limit": 1, "cursor": cursor})
p("Page 2 returns 200", r2.status_code == 200)
data2 = r2.json().get("data", {})
p("Page 2 returns a different item", 
    data2.get("items", [{}])[0].get("caseId") != data.get("items", [{}])[0].get("caseId"))

# ── Step 7: Through Kong ───────────────────────────────────────
print("\n7. Kong Gateway Route (/api/v1/search/cases)")
try:
    r = requests.get(f"{KONG_URL}/api/v1/search/cases", params={"limit": 5}, timeout=5)
    p("Kong routes to search service (200)", r.status_code == 200, r.text[:200])
except Exception as e:
    p("Kong routing", False, str(e))

print("\n" + "=" * 55)
print("   Verification Complete!")
print("=" * 55)
