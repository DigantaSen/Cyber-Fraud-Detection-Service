import json
import base64
import struct
import time
import urllib.request
import zlib


URL = "http://localhost:8101/ml/counterfeit-detect"
REQUIRED_FIELDS = {
    "score",
    "isAuthentic",
    "confidence",
    "detectedFeatures",
    "signals",
    "explanation",
    "modelVersion",
    "processingMs",
}


def make_test_png_base64(width=320, height=160):
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if 30 < x < 290 and 35 < y < 125:
                row.extend([190, 150, 85])
            else:
                row.extend([235, 230, 210])
        rows.append(bytes(row))

    def chunk(chunk_type, data):
        checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)

    raw = b"".join(rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def post_case():
    payload = {
        "imageBase64": make_test_png_base64(),
        "denomination": 500,
        "metadata": {},
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=75) as response:
        body = json.loads(response.read().decode())
    return body, round((time.perf_counter() - started) * 1000)


def validate_contract(body):
    missing = REQUIRED_FIELDS - set(body)
    assert not missing, f"missing fields: {sorted(missing)}"
    assert isinstance(body["score"], int) and 0 <= body["score"] <= 100
    assert isinstance(body["isAuthentic"], bool)
    assert isinstance(body["confidence"], (int, float)) and 0 <= body["confidence"] <= 1
    assert isinstance(body["detectedFeatures"], dict)
    assert isinstance(body["signals"], list) and body["signals"]
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert body["modelVersion"].startswith(("groq:", "stub"))


def main():
    body, elapsed_ms = post_case()
    validate_contract(body)
    print(
        f"PASS counterfeit cv: score={body['score']} authentic={body['isAuthentic']} "
        f"provider={body['modelVersion']} api_ms={elapsed_ms} model_ms={body['processingMs']}"
    )
    print(f"  signals={body['signals']}")
    print(f"  explanation={body['explanation']}")


if __name__ == "__main__":
    main()
