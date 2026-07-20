"""
T12b — Offline inference wrapper for the quantized edge counterfeit detector.

Fully offline: only numpy, Pillow, and onnxruntime are required (no network
call, no FastAPI, no Groq dependency). Designed to run on mobile / POS
terminals per FR-12, and to sync results back to the platform once
connectivity returns (see docs/architecture/sequences/04-offline-counterfeit-sync.md).

Response shape intentionally mirrors CounterfeitDetectResponse from
backend/ml-stubs/main.py / docs/api/ml-contract.md so the sync step can
upsert edge-produced verdicts using the same contract as the online model.
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Any

import numpy as np
import onnxruntime as ort

from features import extract_features, describe_features

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "counterfeit_detector.onnx")
MODEL_VERSION = "edge-onnx-int8-v0.1"

_session: ort.InferenceSession | None = None


def _get_session() -> ort.InferenceSession:
    global _session
    if _session is None:
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1  # POS/mobile-friendly: single-threaded, low overhead
        _session = ort.InferenceSession(MODEL_PATH, sess_options=so, providers=["CPUExecutionProvider"])
    return _session


def _signals_from_features(detected: dict[str, Any], counterfeit_prob: float) -> list[str]:
    signals = []
    if not detected["securityThread"]:
        signals.append("security thread not detected (edge-model heuristic)")
    if not detected["watermark"]:
        signals.append("low watermark contrast (edge-model heuristic)")
    if not detected["microprinting"]:
        signals.append("microprinting sharpness below threshold (edge-model heuristic)")
    if not detected["colorShift"]:
        signals.append("color-shift ink signal weak (edge-model heuristic)")
    if detected["imageQuality"] in ("blurry", "low_light"):
        signals.append(f"image quality: {detected['imageQuality']}")
    if not signals:
        signals.append("security features consistent with genuine note (edge-model heuristic)")
    return signals[:5]


def analyze_counterfeit_offline(image_bytes: bytes, denomination: int | None = None) -> dict[str, Any]:
    """Run the fully-offline edge model. Mirrors CounterfeitDetectResponse."""
    start = time.perf_counter()

    feature_vector = extract_features(image_bytes)
    detected = describe_features(feature_vector)

    session = _get_session()
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: feature_vector.reshape(1, -1).astype(np.float32)})

    # skl2onnx MLPClassifier output: [label, probabilities] with zipmap disabled
    # -> outputs[1] is a (1, 2) float array [P(authentic), P(counterfeit)].
    probs = np.asarray(outputs[1])[0]
    counterfeit_prob = float(probs[1])

    score = int(round(counterfeit_prob * 100))
    is_authentic = score < 50
    confidence = round(float(abs(counterfeit_prob - 0.5) * 2), 2)  # distance from decision boundary
    confidence = max(0.50, confidence)  # edge model floor; never overstate certainty below coin-flip

    signals = _signals_from_features(detected, counterfeit_prob)
    denom_note = f" for INR {denomination}" if denomination else ""
    explanation = (
        f"Offline edge model{denom_note}: counterfeit-suspicion score {score}/100 "
        f"(no network connection used). Verify with the full model when online."
    )

    return {
        "score": score,
        "isAuthentic": is_authentic,
        "confidence": confidence,
        "detectedFeatures": detected,
        "signals": signals,
        "explanation": explanation,
        "modelVersion": MODEL_VERSION,
        "processingMs": max(1, round((time.perf_counter() - start) * 1000)),
        "offline": True,
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description="Offline edge counterfeit-detector inference")
    parser.add_argument("image_path", help="Path to a JPEG/PNG currency note image")
    parser.add_argument("--denomination", type=int, default=None)
    args = parser.parse_args()

    with open(args.image_path, "rb") as f:
        image_bytes = f.read()

    result = analyze_counterfeit_offline(image_bytes, args.denomination)
    import json
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
