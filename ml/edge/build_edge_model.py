"""
T12b — Quantized Edge Model (offline counterfeit currency detector, FR-12).

Trains a small MLP classifier on calibrated synthetic feature vectors (see
features.py for the real, dependency-light extractor used at inference time),
exports it to ONNX, and INT8-quantizes it so it can run fully offline on
mobile / POS terminals with no network connectivity.

Why synthetic features instead of a labeled currency-image dataset: the
live counterfeit-cv model (backend/ml-stubs/main.py) delegates to Groq's
hosted vision LLM rather than a locally trained CNN, so no labeled image
corpus exists in this repo. The synthetic distributions below are calibrated
against real feature-extractor output (edge density, Laplacian sharpness,
color variance, contrast, texture uniformity, saturation, aspect-ratio
deviation) measured on synthetic "sharp/high-detail" vs "blurry/degraded"
sample images, and encode the same documented security-feature intuition
used in the ml-contract.md prompt (security thread, watermark, microprinting,
color-shift ink, print quality). Swap `synth_dataset()` for a real labeled
feature set once one is available — the training/export/quantization
pipeline below does not need to change.

Usage: python3 build_edge_model.py
Outputs:
  models/counterfeit_detector_fp32.onnx   (float32, intermediate)
  models/counterfeit_detector.onnx        (INT8 dynamic-quantized, final artifact)
"""
import os

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

from features import FEATURE_NAMES

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(MODELS_DIR, exist_ok=True)

RNG = np.random.default_rng(42)
N_PER_CLASS = 1500


def _clip(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip(values, lo, hi)


def synth_dataset() -> tuple[np.ndarray, np.ndarray]:
    """Generate calibrated synthetic (features, label) pairs.
    label = 1 -> counterfeit/suspicious, 0 -> authentic-looking."""

    # Authentic: crisp, well-lit, well-cropped capture of a genuine note.
    authentic = np.stack(
        [
            _clip(RNG.normal(0.30, 0.10, N_PER_CLASS), 0, 0.65),   # edge_density
            _clip(RNG.normal(20.0, 8.0, N_PER_CLASS), 0, 40),      # sharpness
            _clip(RNG.normal(0.010, 0.004, N_PER_CLASS), 0, 0.02),  # color_variance
            _clip(RNG.normal(0.10, 0.03, N_PER_CLASS), 0.02, 0.16),  # contrast
            _clip(RNG.normal(0.985, 0.008, N_PER_CLASS), 0.9, 1.0),  # local_uniformity
            _clip(RNG.normal(0.28, 0.05, N_PER_CLASS), 0.1, 0.4),   # saturation_mean
            _clip(RNG.normal(0.02, 0.03, N_PER_CLASS), 0, 0.3),    # aspect_ratio_dev
        ],
        axis=1,
    )

    # Counterfeit: degraded reproduction (photocopy / rescanned / cropped).
    counterfeit = np.stack(
        [
            _clip(RNG.normal(0.08, 0.07, N_PER_CLASS), 0, 0.65),
            _clip(RNG.normal(6.0, 5.0, N_PER_CLASS), 0, 40),
            _clip(RNG.normal(0.004, 0.003, N_PER_CLASS), 0, 0.02),
            _clip(RNG.normal(0.05, 0.025, N_PER_CLASS), 0.02, 0.16),
            _clip(RNG.normal(0.99, 0.01, N_PER_CLASS), 0.9, 1.0),
            _clip(RNG.normal(0.20, 0.06, N_PER_CLASS), 0.1, 0.4),
            _clip(RNG.normal(0.08, 0.07, N_PER_CLASS), 0, 0.3),
        ],
        axis=1,
    )

    X = np.concatenate([authentic, counterfeit], axis=0).astype(np.float32)
    y = np.concatenate([np.zeros(N_PER_CLASS), np.ones(N_PER_CLASS)]).astype(np.int64)
    return X, y


def train() -> Pipeline:
    X, y = synth_dataset()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "mlp",
                MLPClassifier(
                    hidden_layer_sizes=(16, 8),
                    activation="relu",
                    max_iter=500,
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    print(f"Feature order: {FEATURE_NAMES}")
    print(f"Train samples: {len(X_train)} | Test samples: {len(X_test)}")
    print(f"Test accuracy: {accuracy_score(y_test, y_pred):.4f}")
    print(classification_report(y_test, y_pred, target_names=["authentic", "counterfeit"]))

    return pipeline


def export_onnx(pipeline: Pipeline) -> str:
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    initial_type = [("input", FloatTensorType([None, len(FEATURE_NAMES)]))]
    onnx_model = convert_sklearn(
        pipeline,
        initial_types=initial_type,
        options={id(pipeline): {"zipmap": False}},
        target_opset=15,
    )
    fp32_path = os.path.join(MODELS_DIR, "counterfeit_detector_fp32.onnx")
    with open(fp32_path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    print(f"Wrote float32 ONNX model: {fp32_path} "
          f"({os.path.getsize(fp32_path) / 1024:.1f} KB)")
    return fp32_path


def quantize(fp32_path: str) -> str:
    import shutil
    import tempfile
    from onnxruntime.quantization import quantize_dynamic, QuantType

    # onnxruntime's quantizer writes+deletes an intermediate "-inferred.onnx"
    # file next to its inputs/outputs. Some mounted/network filesystems
    # reject unlink() on that intermediate file, so stage the whole
    # quantization step in a local temp dir and copy the final artifact back.
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_fp32 = os.path.join(tmp_dir, "model_fp32.onnx")
        tmp_quant = os.path.join(tmp_dir, "model_quant.onnx")
        shutil.copyfile(fp32_path, tmp_fp32)

        quantize_dynamic(
            model_input=tmp_fp32,
            model_output=tmp_quant,
            weight_type=QuantType.QInt8,
        )

        quant_path = os.path.join(MODELS_DIR, "counterfeit_detector.onnx")
        shutil.copyfile(tmp_quant, quant_path)

    size_kb = os.path.getsize(quant_path) / 1024
    print(f"Wrote INT8-quantized ONNX model: {quant_path} ({size_kb:.1f} KB)")
    assert size_kb / 1024 <= 10, "edge model exceeds the 10MB budget (FR-12/T12b)"
    return quant_path


if __name__ == "__main__":
    pipeline = train()
    fp32_path = export_onnx(pipeline)
    quant_path = quantize(fp32_path)
    print("\nDone. Final offline artifact:", quant_path)
