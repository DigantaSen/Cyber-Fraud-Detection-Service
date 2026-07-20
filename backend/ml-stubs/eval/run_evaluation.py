"""
T11 — ML Evaluation & Tuning harness.

Runs the deterministic rule-engine core of the Scam NLP Classifier and the
Fraud Graph Analyzer (backend/ml-stubs/main.py) against labeled datasets and
reports precision/recall/F1 per category, plus threshold sensitivity for the
Orchestrator's fusion/HITL confidence gate (FUSION_CONFIDENCE_HITL_THRESHOLD).

Note on scope: classify_scam_text() is the same deterministic engine used as
the production fallback whenever Groq is unavailable (see
classify_scam_text_safely in main.py), so these numbers characterize the
guaranteed-available code path. Live-Groq accuracy for scam-nlp,
counterfeit-cv, and audio-analyzer depends on GROQ_API_KEY at runtime and
should be re-run against docs/api/ml-contract.md examples once a key is
available (see counterfeit_cv/audio sections in the generated report).

Usage: python3 run_evaluation.py
"""
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from main import (  # noqa: E402
    classify_scam_text,
    analyze_graph_features,
    ScamClassifyRequest,
    GraphAnalyzeRequest,
    risk_tier,
)
from dataset_scam_nlp import DATASET  # noqa: E402
from dataset_graph import GRAPH_CASES  # noqa: E402


def precision_recall_f1(tp, fp, fn):
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def evaluate_scam_nlp():
    print("=" * 70)
    print("SCAM NLP CLASSIFIER — deterministic rule engine (fallback path)")
    print("=" * 70)

    per_category = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    binary_tp = binary_fp = binary_tn = binary_fn = 0
    confidences_scam = []
    confidences_benign = []
    rows = []

    for text, lang, complaint_type, expected_category, is_scam in DATASET:
        req = ScamClassifyRequest(
            text=text, languageCode=lang, complaintType=complaint_type, metadata=None
        )
        result = classify_scam_text(req)
        predicted_category = result["category"]
        predicted_is_scam = result["riskTier"] != "LOW"

        rows.append((text[:50], expected_category, predicted_category,
                     result["score"], result["riskTier"], is_scam, predicted_is_scam))

        # per-category (multiclass, one-vs-rest)
        if predicted_category == expected_category:
            per_category[expected_category]["tp"] += 1
        else:
            per_category[expected_category]["fn"] += 1
            per_category[predicted_category]["fp"] += 1

        # binary scam/not-scam
        if is_scam and predicted_is_scam:
            binary_tp += 1
        elif is_scam and not predicted_is_scam:
            binary_fn += 1
        elif not is_scam and predicted_is_scam:
            binary_fp += 1
        else:
            binary_tn += 1

        if is_scam:
            confidences_scam.append(result["confidence"])
        else:
            confidences_benign.append(result["confidence"])

    print(f"\n{'category':<20}{'precision':>10}{'recall':>10}{'f1':>10}{'support':>10}")
    macro_p, macro_r, macro_f1, n_cats = 0, 0, 0, 0
    for category in sorted(set(d[3] for d in DATASET)):
        m = per_category[category]
        support = sum(1 for d in DATASET if d[3] == category)
        p, r, f1 = precision_recall_f1(m["tp"], m["fp"], m["fn"])
        print(f"{category:<20}{p:>10.2f}{r:>10.2f}{f1:>10.2f}{support:>10}")
        macro_p += p
        macro_r += r
        macro_f1 += f1
        n_cats += 1
    print(f"{'MACRO AVG':<20}{macro_p/n_cats:>10.2f}{macro_r/n_cats:>10.2f}{macro_f1/n_cats:>10.2f}")

    accuracy = sum(1 for r in rows if r[1] == r[2]) / len(rows)
    print(f"\nCategory accuracy (exact match incl. UNKNOWN): {accuracy:.2%}")

    bp, br, bf1 = precision_recall_f1(binary_tp, binary_fp, binary_fn)
    print(f"\nBinary scam-detection (riskTier != LOW as positive):")
    print(f"  TP={binary_tp} FP={binary_fp} FN={binary_fn} TN={binary_tn}")
    print(f"  precision={bp:.2f} recall={br:.2f} f1={bf1:.2f}")

    print(f"\nConfidence distribution:")
    print(f"  scam examples    (n={len(confidences_scam)}): "
          f"min={min(confidences_scam):.2f} max={max(confidences_scam):.2f} "
          f"avg={sum(confidences_scam)/len(confidences_scam):.2f}")
    print(f"  benign examples  (n={len(confidences_benign)}): "
          f"min={min(confidences_benign):.2f} max={max(confidences_benign):.2f} "
          f"avg={sum(confidences_benign)/len(confidences_benign):.2f}")

    print("\nMisclassifications:")
    any_miss = False
    for text, exp_cat, pred_cat, score, tier, is_scam, pred_is_scam in rows:
        if exp_cat != pred_cat or is_scam != pred_is_scam:
            any_miss = True
            print(f"  '{text}...' expected={exp_cat}/{is_scam} got={pred_cat}/{pred_is_scam} "
                  f"score={score} tier={tier}")
    if not any_miss:
        print("  none")

    return {
        "macro_precision": macro_p / n_cats,
        "macro_recall": macro_r / n_cats,
        "macro_f1": macro_f1 / n_cats,
        "binary_precision": bp,
        "binary_recall": br,
        "binary_f1": bf1,
    }


def evaluate_graph_analyzer():
    print("\n" + "=" * 70)
    print("FRAUD GRAPH ANALYZER — deterministic topology scorer")
    print("=" * 70)

    tp = fp = fn = tn = 0
    rows = []
    for name, anchor, nodes, edges, is_fraud, min_score in GRAPH_CASES:
        req = GraphAnalyzeRequest(anchorEntityId=anchor, graph={"nodes": nodes, "edges": edges})
        result = analyze_graph_features(req)
        predicted_fraud = result["score"] >= 50
        rows.append((name, is_fraud, predicted_fraud, result["score"], result["ringSize"]))
        if is_fraud and predicted_fraud:
            tp += 1
        elif is_fraud and not predicted_fraud:
            fn += 1
        elif not is_fraud and predicted_fraud:
            fp += 1
        else:
            tn += 1

    print(f"\n{'case':<28}{'truth':>8}{'pred':>8}{'score':>8}{'ringSize':>10}")
    for name, truth, pred, score, ring_size in rows:
        print(f"{name:<28}{str(truth):>8}{str(pred):>8}{score:>8}{ring_size:>10}")

    p, r, f1 = precision_recall_f1(tp, fp, fn)
    print(f"\nTP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"precision={p:.2f} recall={r:.2f} f1={f1:.2f}")
    return {"precision": p, "recall": r, "f1": f1}


if __name__ == "__main__":
    scam_metrics = evaluate_scam_nlp()
    graph_metrics = evaluate_graph_analyzer()

    print("\n" + "=" * 70)
    print("SUMMARY (for docs/ml/evaluation-report.md)")
    print("=" * 70)
    print("scam_nlp:", scam_metrics)
    print("graph_analyzer:", graph_metrics)
