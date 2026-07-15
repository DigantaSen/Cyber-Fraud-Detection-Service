import json
import time
import urllib.request


URL = "http://localhost:8100/ml/scam-classify"
REQUIRED_FIELDS = {
    "score",
    "riskTier",
    "category",
    "confidence",
    "signals",
    "explanation",
    "modelVersion",
    "processingMs",
}
ALLOWED_CATEGORIES = {
    "IMPERSONATION_FRAUD",
    "UPI_SCAM",
    "INVESTMENT_FRAUD",
    "LOTTERY_SCAM",
    "ROMANCE_SCAM",
    "UNKNOWN",
}


CASES = [
    (
        "authority impersonation",
        "IMPERSONATION_FRAUD",
        70,
        "This is CBI. Transfer 50000 immediately or FIR and arrest will happen.",
        "CALL_FRAUD",
    ),
    (
        "upi scam",
        "UPI_SCAM",
        60,
        "Someone sent a UPI collect request on PhonePe and asked me to approve it to receive a refund.",
        "UPI_FRAUD",
    ),
    (
        "investment scam",
        "INVESTMENT_FRAUD",
        60,
        "A Telegram group promised guaranteed crypto trading profit and asked me to invest more money.",
        "CYBER_CRIME",
    ),
    (
        "normal message",
        "UNKNOWN",
        0,
        "I want to know the status of my bank account statement request.",
        "OTHER",
    ),
]


def expected_tier(score):
    if score >= 90:
        return "CRITICAL"
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def post_case(text, complaint_type):
    payload = {
        "text": text,
        "languageCode": "en",
        "complaintType": complaint_type,
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
    assert body["riskTier"] == expected_tier(body["score"])
    assert body["category"] in ALLOWED_CATEGORIES
    assert isinstance(body["confidence"], (int, float)) and 0 <= body["confidence"] <= 1
    assert isinstance(body["signals"], list) and body["signals"]
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert body["modelVersion"].startswith(("ollama:", "rules"))


def main():
    failures = []
    for name, expected_category, min_score, text, complaint_type in CASES:
        try:
            body, elapsed_ms = post_case(text, complaint_type)
            validate_contract(body)
            assert body["category"] == expected_category, (
                f"expected category {expected_category}, got {body['category']}"
            )
            assert body["score"] >= min_score, f"expected score >= {min_score}, got {body['score']}"
            print(
                f"PASS {name}: category={body['category']} score={body['score']} "
                f"tier={body['riskTier']} api_ms={elapsed_ms} model_ms={body['processingMs']}"
            )
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            failures.append(name)

    print(f"SUMMARY passed={len(CASES) - len(failures)} failed={len(failures)} total={len(CASES)}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
