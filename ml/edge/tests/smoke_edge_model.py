"""
Smoke test for the T12b offline edge counterfeit detector.
Generates synthetic "sharp/genuine-like" and "blurry/degraded" test images
(no real currency dataset needed), runs them through the fully-offline
ONNX pipeline, and checks:
  1. Response conforms to the CounterfeitDetectResponse contract shape.
  2. The quantized model file is <=10MB (FR-12 / T12b budget).
  3. Directionally sane behavior: sharp/high-detail image scores lower
     (more "authentic") than a blurred/degraded version of a similar scene.

Run: python3 tests/smoke_edge_model.py   (from ml/edge/)
"""
import io
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from edge_infer import analyze_counterfeit_offline, MODEL_PATH  # noqa: E402

REQUIRED_FIELDS = {
    "score", "isAuthentic", "confidence", "detectedFeatures",
    "signals", "explanation", "modelVersion", "processingMs",
}


def make_test_image(sharp: bool, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    w, h = 860, 400
    img = Image.new("RGB", (w, h), (210, 200, 160))
    draw = ImageDraw.Draw(img)
    n_lines = 400 if sharp else 60
    for _ in range(n_lines):
        x = int(rng.integers(0, w))
        draw.line([(x, 0), (x, h)], fill=(80, 60, 40), width=1)
    draw.ellipse([w * 0.6, h * 0.3, w * 0.6 + 80, h * 0.3 + 80], outline=(255, 255, 255), width=3)
    arr = np.asarray(img).astype(np.float32)
    noise = rng.normal(0, 5 if sharp else 30, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    if not sharp:
        img = img.filter(ImageFilter.GaussianBlur(radius=3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def validate_contract(body):
    missing = REQUIRED_FIELDS - set(body)
    assert not missing, f"missing fields: {sorted(missing)}"
    assert isinstance(body["score"], int) and 0 <= body["score"] <= 100
    assert isinstance(body["isAuthentic"], bool)
    assert isinstance(body["confidence"], (int, float)) and 0 <= body["confidence"] <= 1
    assert isinstance(body["detectedFeatures"], dict)
    assert isinstance(body["signals"], list) and body["signals"]
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert body["modelVersion"].startswith("edge-onnx-")


def main():
    failures = []

    # 1. Model size budget
    size_mb = os.path.getsize(MODEL_PATH) / (1024 * 1024)
    print(f"Model size: {size_mb:.3f} MB (budget: 10 MB)")
    if size_mb > 10:
        failures.append("model exceeds 10MB budget")

    # 2. Contract + directional sanity
    sharp_bytes = make_test_image(sharp=True, seed=1)
    blur_bytes = make_test_image(sharp=False, seed=2)

    sharp_result = analyze_counterfeit_offline(sharp_bytes, denomination=500)
    blur_result = analyze_counterfeit_offline(blur_bytes, denomination=500)

    for name, result in [("sharp", sharp_result), ("blurry", blur_result)]:
        try:
            validate_contract(result)
            print(f"PASS contract shape: {name} -> score={result['score']} "
                  f"isAuthentic={result['isAuthentic']} ms={result['processingMs']}")
        except AssertionError as exc:
            print(f"FAIL contract shape: {name}: {exc}")
            failures.append(f"contract:{name}")

    if sharp_result["score"] < blur_result["score"]:
        print(f"PASS directional check: sharp score ({sharp_result['score']}) "
              f"< blurry score ({blur_result['score']})")
    else:
        print(f"FAIL directional check: sharp score ({sharp_result['score']}) "
              f">= blurry score ({blur_result['score']})")
        failures.append("directional")

    print(f"\nSUMMARY passed={3 - len(failures)} failed={len(failures)} total=3")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
