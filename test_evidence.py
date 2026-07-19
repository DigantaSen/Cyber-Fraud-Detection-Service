import time
import time
import requests

API_URL = "http://localhost:8006"

# A valid UUID case id
case_id = "00000000-0000-0000-0000-000000000001"

# 1. Request upload URL
print("Requesting upload...")
resp = requests.post(f"{API_URL}/cases/{case_id}/evidence", json={
    "filename": "test.png",
    "content_type": "image/png",
    "file_size_bytes": 100
})
if resp.status_code != 200:
    print(f"Failed to request upload: {resp.status_code} {resp.text}")
    exit(1)

data = resp.json()
evidence_id = data["evidenceId"]
upload_url = data["uploadUrl"]
print(f"Got evidence_id: {evidence_id}")
print(f"Upload URL: {upload_url}")

# Replace minio:9000 with localhost:9000 for local testing
upload_url = upload_url.replace("minio:9000", "localhost:9000")
upload_url = upload_url.replace("https://", "http://")

# 2. Upload a dummy PNG file directly to MinIO
print("Uploading dummy PNG to MinIO...")
# smallest 1x1 png
png_data = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")
resp = requests.put(upload_url, data=png_data)
if resp.status_code != 200:
    print(f"Failed to upload to MinIO: {resp.status_code} {resp.text}")
    exit(1)

# 3. Confirm upload
print("Confirming upload...")
resp = requests.post(f"{API_URL}/evidence/{evidence_id}/confirm")
if resp.status_code != 200:
    print(f"Failed to confirm upload: {resp.status_code} {resp.text}")
    exit(1)

hash_data = resp.json()
print(f"Confirmed upload. Hash info: {hash_data}")

# 4. Get evidence download URL
print("Getting evidence...")
resp = requests.get(f"{API_URL}/evidence/{evidence_id}")
if resp.status_code != 200:
    print(f"Failed to get evidence: {resp.status_code} {resp.text}")
    exit(1)
print(f"Evidence Download URL: {resp.json()['downloadUrl']}")

# 5. Get hash
print("Getting hash...")
resp = requests.get(f"{API_URL}/evidence/{evidence_id}/hash")
if resp.status_code != 200:
    print(f"Failed to get hash: {resp.status_code} {resp.text}")
    exit(1)
print(f"Evidence Hash: {resp.json()['hash']}")

print("All tests passed successfully.")
