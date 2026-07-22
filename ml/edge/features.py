"""
Offline, dependency-light feature extraction for the quantized edge counterfeit
detector (T12b). Deliberately avoids OpenCV/torch/tensorflow so the wrapper
stays small enough for mobile / POS-terminal deployment (FR-12: works with
zero network connectivity).

Only numpy + Pillow are required at inference time.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

FEATURE_NAMES = [
    "edge_density",
    "sharpness",
    "color_variance",
    "contrast",
    "local_uniformity",
    "saturation_mean",
    "aspect_ratio_dev",
]

# Standard INR banknote aspect ratio is ~2.15:1 (varies slightly by denomination).
EXPECTED_ASPECT_RATIO = 2.15


def _to_image(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def extract_features(image_bytes: bytes) -> np.ndarray:
    """Extract a 7-dim feature vector from raw image bytes (JPEG/PNG)."""
    image = _to_image(image_bytes)
    # Normalize working size for fast, deterministic feature extraction on
    # low-power devices; large phone-camera photos are downsampled.
    image = image.copy()
    image.thumbnail((256, 256))

    rgb = np.asarray(image, dtype=np.float32) / 255.0
    gray_image = image.convert("L")
    gray = np.asarray(gray_image, dtype=np.float32) / 255.0

    # 1. Edge density — fraction of pixels with strong local gradient
    #    (proxy for microprinting / fine security-line detail).
    gx = np.diff(gray, axis=1)
    gy = np.diff(gray, axis=0)
    grad_mag = np.sqrt(gx[:-1, :] ** 2 + gy[:, :-1] ** 2)
    edge_density = float((grad_mag > 0.08).mean())

    # 2. Sharpness — variance of a Laplacian-filtered image (blur detector;
    #    photocopies/rescans of counterfeit notes are typically softer).
    laplacian = gray_image.filter(ImageFilter.FIND_EDGES)
    lap_arr = np.asarray(laplacian, dtype=np.float32)
    sharpness = float(lap_arr.var()) / 255.0

    # 3. Color variance — richness of ink reproduction (proxy for
    #    color-shift security ink / print fidelity).
    color_variance = float(rgb.reshape(-1, 3).var(axis=0).mean())

    # 4. Contrast — tonal range (proxy for watermark visibility).
    contrast = float(gray.std())

    # 5. Local uniformity — std of block-wise texture std-devs. Genuine notes
    #    have structured, repeating microprint texture; poor copies tend to be
    #    flatter or unevenly noisy.
    h, w = gray.shape
    block = 16
    block_stds = []
    for by in range(0, h - block, block):
        for bx in range(0, w - block, block):
            block_stds.append(gray[by:by + block, bx:bx + block].std())
    local_uniformity = float(1.0 - np.std(block_stds)) if block_stds else 0.5

    # 6. Saturation mean (HSV) — muted saturation is common in low-quality
    #    scans/photocopies used to produce counterfeits.
    hsv = np.asarray(image.convert("HSV"), dtype=np.float32) / 255.0
    saturation_mean = float(hsv[:, :, 1].mean())

    # 7. Aspect ratio deviation — cropping/resizing artifacts.
    width, height = image.size
    aspect_ratio = max(width, height) / max(1, min(width, height))
    aspect_ratio_dev = float(abs(aspect_ratio - EXPECTED_ASPECT_RATIO))

    return np.array(
        [
            edge_density,
            sharpness,
            color_variance,
            contrast,
            local_uniformity,
            saturation_mean,
            aspect_ratio_dev,
        ],
        dtype=np.float32,
    )


def describe_features(vector: np.ndarray) -> dict[str, Any]:
    """Map raw feature values to human-readable detected-feature flags,
    mirroring the CounterfeitDetectResponse.detectedFeatures contract shape
    used by the live Groq-backed model (backend/ml-stubs/main.py)."""
    (
        edge_density,
        sharpness,
        color_variance,
        contrast,
        local_uniformity,
        saturation_mean,
        aspect_ratio_dev,
    ) = vector.tolist()

    if sharpness > 15 and edge_density > 0.15:
        image_quality = "clear"
    elif sharpness > 5:
        image_quality = "blurry"
    else:
        image_quality = "low_light"

    return {
        "securityThread": edge_density > 0.20,
        "watermark": contrast > 0.08,
        "microprinting": sharpness > 10,
        "colorShift": color_variance > 0.005,
        "imageQuality": image_quality,
    }
