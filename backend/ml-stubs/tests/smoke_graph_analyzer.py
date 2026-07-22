import json
import time
import urllib.request


URL = "http://localhost:8102/ml/graph-analyze"
REQUIRED_FIELDS = {
    "score",
    "fraudRingProbability",
    "suspiciousNodes",
    "ringSize",
    "signals",
    "explanation",
    "modelVersion",
    "processingMs",
}


CASES = [
    {
        "name": "sparse low risk graph",
        "max_score": 35,
        "payload": {
            "anchorEntityId": "phone-a",
            "graph": {
                "nodes": [
                    {"id": "phone-a", "type": "PHONE", "fraudScore": 10},
                    {"id": "phone-b", "type": "PHONE", "fraudScore": 15},
                ],
                "edges": [
                    {"from": "phone-a", "to": "phone-b", "relation": "CALLED", "count": 1},
                ],
            },
            "metadata": {},
        },
    },
    {
        "name": "high risk ring graph",
        "min_score": 70,
        "payload": {
            "anchorEntityId": "phone-a",
            "graph": {
                "nodes": [
                    {"id": "phone-a", "type": "PHONE", "fraudScore": 88},
                    {"id": "phone-b", "type": "PHONE", "fraudScore": 92},
                    {"id": "acct-1", "type": "BANK_ACCOUNT", "fraudScore": 81},
                    {"id": "device-1", "type": "DEVICE", "fraudScore": 45},
                ],
                "edges": [
                    {"from": "phone-a", "to": "phone-b", "relation": "CALLED", "count": 9},
                    {"from": "phone-a", "to": "acct-1", "relation": "USED_ACCOUNT", "count": 4},
                    {"from": "phone-a", "to": "device-1", "relation": "USED_DEVICE", "count": 2},
                    {"from": "phone-b", "to": "acct-1", "relation": "USED_ACCOUNT", "count": 8},
                    {"from": "acct-1", "to": "device-1", "relation": "USED_DEVICE", "count": 6},
                ],
            },
            "metadata": {},
        },
    },
]


def post_case(payload):
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode())
    return body, round((time.perf_counter() - started) * 1000)


def validate_contract(body):
    missing = REQUIRED_FIELDS - set(body)
    assert not missing, f"missing fields: {sorted(missing)}"
    assert isinstance(body["score"], int) and 0 <= body["score"] <= 100
    assert isinstance(body["fraudRingProbability"], (int, float))
    assert 0 <= body["fraudRingProbability"] <= 1
    assert isinstance(body["suspiciousNodes"], list)
    assert isinstance(body["ringSize"], int) and body["ringSize"] >= 0
    assert isinstance(body["signals"], list) and body["signals"]
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert body["modelVersion"] == "graph-features-v0.1"


def main():
    failures = []
    for case in CASES:
        try:
            body, elapsed_ms = post_case(case["payload"])
            validate_contract(body)
            if "min_score" in case:
                assert body["score"] >= case["min_score"], (
                    f"expected score >= {case['min_score']}, got {body['score']}"
                )
                assert body["suspiciousNodes"], "expected suspicious nodes"
            if "max_score" in case:
                assert body["score"] <= case["max_score"], (
                    f"expected score <= {case['max_score']}, got {body['score']}"
                )

            print(
                f"PASS {case['name']}: score={body['score']} "
                f"prob={body['fraudRingProbability']} ringSize={body['ringSize']} "
                f"api_ms={elapsed_ms} model_ms={body['processingMs']}"
            )
            print(f"  signals={body['signals']}")
        except Exception as exc:
            print(f"FAIL {case['name']}: {exc}")
            failures.append(case["name"])

    print(f"SUMMARY passed={len(CASES) - len(failures)} failed={len(failures)} total={len(CASES)}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
