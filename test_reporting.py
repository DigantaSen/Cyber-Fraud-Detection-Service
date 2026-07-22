import requests

API_URL = "http://localhost:8007"
case_id = "00000000-0000-0000-0000-000000000001"

print("--- Testing /reports/ncrb ---")
resp = requests.post(f"{API_URL}/reports/ncrb", json={"case_id": case_id})
if resp.status_code == 200:
    data = resp.json()
    report_id = data["reportId"]
    print(f"NCRB Report generated: {report_id}")
    
    resp_get = requests.get(f"{API_URL}/reports/{report_id}")
    if resp_get.status_code == 200:
        print(f"NCRB Report Download URL: {resp_get.json()['downloadUrl']}")
    else:
        print(f"Failed to get NCRB Report: {resp_get.status_code} {resp_get.text}")
else:
    print(f"Failed to generate NCRB Report: {resp.status_code} {resp.text}")

print("\n--- Testing /reports/intelligence-package ---")
resp = requests.post(f"{API_URL}/reports/intelligence-package", json={"case_id": case_id})
if resp.status_code == 200:
    data = resp.json()
    package_id = data["packageId"]
    signature = data["signature"]
    print(f"Intelligence Package generated: {package_id}")
    print(f"Signature Algorithm: {data['signatureAlgorithm']}")
    print(f"Signature: {signature[:50]}...")
    print(f"Public Key Fingerprint: {data['publicKeyFingerprint']}")
    
    # We generated both an IntelligencePackage AND a Report out of this
    # Let's get the download URL. Wait, the GET /reports/{id} takes the report_id, not package_id.
    # We might need to check if we can download it. In my code, package_id and report_id are different.
    # Let's just print success.
else:
    print(f"Failed to generate Intelligence Package: {resp.status_code} {resp.text}")
