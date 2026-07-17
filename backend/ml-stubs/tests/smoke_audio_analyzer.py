"""
Smoke test — Audio Voice Spoof Analyzer
POST /ml/audio-analyze on port 8103

Generates a minimal valid WAV file in memory (no external libs required),
base64-encodes it, and validates the full response contract.
Runs against a live service at localhost:8103.
"""
import base64
import json
import struct
import time
import urllib.request


URL = "http://localhost:8103/ml/audio-analyze"
REQUIRED_FIELDS = {
    "score",
    "isAISpoofed",
    "confidence",
    "voiceFeatures",
    "signals",
    "explanation",
    "modelVersion",
    "processingMs",
}


# ---------------------------------------------------------------------------
# Minimal WAV generator (no external dependencies)
# Produces a valid 1-second mono 8kHz PCM-16 WAV containing silence.
# Groq Whisper accepts this — it will produce an empty / near-empty transcript.
# ---------------------------------------------------------------------------

def _make_wav_bytes(duration_seconds: float = 1.0, sample_rate: int = 8000) -> bytes:
    """Return a minimal valid PCM-16 WAV as raw bytes."""
    num_channels = 1
    bits_per_sample = 16
    num_samples = int(sample_rate * duration_seconds)
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    # 44-byte RIFF/WAV header
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,   # ChunkSize
        b"WAVE",
        b"fmt ",
        16,               # Subchunk1Size (PCM)
        1,                # AudioFormat (PCM)
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    # Silence samples (all zeros)
    pcm_data = b"\x00" * data_size
    return header + pcm_data


def _make_speech_like_wav_bytes(duration_seconds: float = 5.0, sample_rate: int = 8000) -> bytes:
    """
    Return a WAV with a simple synthetic sine-wave pattern that resembles speech energy
    (still silence from Whisper's perspective, but tests the pipeline end-to-end).
    """
    import math
    num_channels = 1
    bits_per_sample = 16
    num_samples = int(sample_rate * duration_seconds)
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    # 440 Hz tone (synthetic, non-human)
    samples = bytearray()
    for i in range(num_samples):
        value = int(8000 * math.sin(2 * math.pi * 440 * i / sample_rate))
        samples += struct.pack("<h", value)
    return header + bytes(samples)


def _wav_to_base64(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

CASES = [
    {
        "name": "silence WAV (1s) — stub/fallback path",
        "audioBase64": _wav_to_base64(_make_wav_bytes(1.0)),
        "mimeType": "audio/wav",
        "durationSeconds": 1.0,
        "expect_spoofed": None,  # don't assert — provider may vary
    },
    {
        "name": "synthetic tone WAV (5s) — Whisper + LLM path",
        "audioBase64": _wav_to_base64(_make_speech_like_wav_bytes(5.0)),
        "mimeType": "audio/wav",
        "durationSeconds": 5.0,
        "expect_spoofed": None,
    },
]


def post_case(case: dict) -> tuple[dict, int]:
    payload = {
        "audioBase64": case["audioBase64"],
        "mimeType": case["mimeType"],
        "durationSeconds": case["durationSeconds"],
        "metadata": {},
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode())
    return body, round((time.perf_counter() - started) * 1000)


def validate_contract(body: dict) -> None:
    """Validate that the response matches the ml-contract.md schema."""
    missing = REQUIRED_FIELDS - set(body)
    assert not missing, f"missing fields: {sorted(missing)}"

    assert isinstance(body["score"], int), "score must be int"
    assert 0 <= body["score"] <= 100, f"score out of range: {body['score']}"

    assert isinstance(body["isAISpoofed"], bool), "isAISpoofed must be bool"

    assert isinstance(body["confidence"], (int, float)), "confidence must be numeric"
    assert 0.0 <= body["confidence"] <= 1.0, f"confidence out of range: {body['confidence']}"

    assert isinstance(body["voiceFeatures"], dict), "voiceFeatures must be dict"

    vf = body["voiceFeatures"]
    if "pitchVariance" in vf:
        assert isinstance(vf["pitchVariance"], (int, float)), "pitchVariance must be numeric"
    if "spectralEntropy" in vf:
        assert isinstance(vf["spectralEntropy"], (int, float)), "spectralEntropy must be numeric"
    if "melFrequencyCepstral" in vf and vf["melFrequencyCepstral"] is not None:
        assert isinstance(vf["melFrequencyCepstral"], list), "melFrequencyCepstral must be list"

    assert isinstance(body["signals"], list) and body["signals"], "signals must be non-empty list"
    for sig in body["signals"]:
        assert isinstance(sig, str), "each signal must be a string"

    assert isinstance(body["explanation"], str) and body["explanation"], (
        "explanation must be a non-empty string"
    )
    assert isinstance(body["modelVersion"], str) and body["modelVersion"], (
        "modelVersion must be a non-empty string"
    )
    assert isinstance(body["processingMs"], int) and body["processingMs"] >= 0, (
        "processingMs must be non-negative int"
    )

    # isAISpoofed must be consistent with score (when score >= 50 it should be True).
    # We allow some LLM discretion at boundary scores (45–54 range).
    if body["score"] >= 55:
        assert body["isAISpoofed"], (
            f"isAISpoofed=False inconsistent with score={body['score']}"
        )
    if body["score"] <= 35:
        assert not body["isAISpoofed"], (
            f"isAISpoofed=True inconsistent with score={body['score']}"
        )


def main() -> None:
    failures: list[str] = []
    for case in CASES:
        name = case["name"]
        try:
            body, elapsed_ms = post_case(case)
            validate_contract(body)

            # Provider-specific model version checks
            assert body["modelVersion"].startswith(("groq:", "stub", "rules")), (
                f"unexpected modelVersion: {body['modelVersion']}"
            )

            print(
                f"PASS {name}: score={body['score']} spoofed={body['isAISpoofed']} "
                f"provider={body['modelVersion']} api_ms={elapsed_ms} model_ms={body['processingMs']}"
            )
            print(f"  voiceFeatures={json.dumps({k: v for k, v in body['voiceFeatures'].items() if k != 'melFrequencyCepstral'})}")
            print(f"  signals={body['signals']}")
            print(f"  explanation={body['explanation'][:120]}")
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failures.append(name)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
            failures.append(name)

    print(
        f"\nSUMMARY passed={len(CASES) - len(failures)} failed={len(failures)} total={len(CASES)}"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
