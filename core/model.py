"""
Predictive health model — the ML core of the loop, trained on the real AI4I 2020
benchmark (see dataset.py).

Two heads:
  * failure head  — GradientBoosting classifier → P(machine failure) / health_score
  * mode head     — GradientBoosting classifier → probability of each failure mode
                    (Tool-Wear / Heat-Dissipation / Power / Overstrain), so the
                    agent's diagnosis is grounded in the model, not hard-coded.

`attribute()` gives ablation-based local feature attribution ("why this score")
against the dataset's own healthy-median baseline.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, average_precision_score
import joblib

from .config import MODEL_PATH
from . import dataset as ds


@dataclass
class TrainReport:
    auc: float
    ap: float
    n_train: int
    n_test: int
    positive_rate: float
    mode_accuracy: float
    modes: list = field(default_factory=list)


class HealthModel:
    def __init__(self, failure_clf, mode_clf, baseline: dict, report: TrainReport | None = None):
        self.failure_clf = failure_clf
        self.mode_clf = mode_clf            # may be None if too few mode samples
        self.baseline = baseline
        self.report = report

    # ---- inference -------------------------------------------------------
    def failure_prob(self, feats: dict) -> float:
        p = float(self.failure_clf.predict_proba(ds.features_frame(feats))[0, 1])
        return max(0.0, min(1.0, p))

    def predict(self, feats: dict) -> dict:
        p = self.failure_prob(feats)
        return {"failure_prob": p, "health_score": 1.0 - p}

    def predict_mode(self, feats: dict) -> dict:
        """Most-likely failure mode + full distribution."""
        if self.mode_clf is None:
            return {"mode": "NONE", "mode_label": ds.MODE_LABELS["NONE"], "confidence": 0.0, "distribution": {}}
        X = ds.features_frame(feats)
        proba = self.mode_clf.predict_proba(X)[0]
        classes = list(self.mode_clf.classes_)
        dist = {c: round(float(p), 3) for c, p in zip(classes, proba)}
        top = max(dist, key=dist.get)
        return {"mode": top, "mode_label": ds.MODE_LABELS.get(top, top),
                "confidence": dist[top], "distribution": dist}

    def attribute(self, feats: dict, top_k: int = 4) -> list[dict]:
        """Ablation attribution: risk removed if each feature were healthy."""
        base_p = self.failure_prob(feats)
        contribs = []
        for f in ds.FEATURES:
            if f == "type_code":
                continue                      # quality tier isn't an actionable driver
            cf = dict(feats)
            # rebuild engineered features if a raw one is ablated
            cf[f] = self.baseline[f]
            for eng in ("power_w", "temp_diff", "overstrain"):
                cf.pop(eng, None)
            delta = base_p - self.failure_prob(cf)
            contribs.append({
                "feature": f, "label": ds.FEATURE_LABELS[f],
                "value": round(float(feats.get(f, self.baseline[f])), 2),
                "contribution": round(float(delta), 4),
            })
        contribs.sort(key=lambda d: d["contribution"], reverse=True)
        return contribs[:top_k]

    # ---- persistence -----------------------------------------------------
    def save(self, path=MODEL_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"failure": self.failure_clf, "mode": self.mode_clf,
                     "baseline": self.baseline, "report": self.report}, path)

    @classmethod
    def load(cls, path=MODEL_PATH) -> "HealthModel":
        d = joblib.load(path)
        return cls(d["failure"], d["mode"], d["baseline"], d.get("report"))


def train(seed: int = 42) -> HealthModel:
    df = ds.training_frame()
    X, y = df[ds.FEATURES], df["failure"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=seed, stratify=y)
    failure_clf = GradientBoostingClassifier(
        n_estimators=240, max_depth=3, learning_rate=0.06, subsample=0.9, random_state=seed)
    failure_clf.fit(Xtr, ytr)
    proba = failure_clf.predict_proba(Xte)[:, 1]

    # Mode head — trained on failing rows only (which specific mode fired).
    fail = df[df["failure"] == 1]
    mode_clf, mode_acc, modes = None, 0.0, []
    if fail["mode"].nunique() >= 2 and len(fail) >= 40:
        Mx, My = fail[ds.FEATURES], fail["mode"]
        mxr, mxe, myr, mye = train_test_split(Mx, My, test_size=0.25, random_state=seed, stratify=My)
        mode_clf = GradientBoostingClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.08, random_state=seed)
        mode_clf.fit(mxr, myr)
        mode_acc = round(float((mode_clf.predict(mxe) == mye).mean()), 4)
        modes = list(mode_clf.classes_)

    report = TrainReport(
        auc=round(float(roc_auc_score(yte, proba)), 4),
        ap=round(float(average_precision_score(yte, proba)), 4),
        n_train=len(Xtr), n_test=len(Xte),
        positive_rate=round(float(y.mean()), 4),
        mode_accuracy=mode_acc, modes=modes)
    return HealthModel(failure_clf, mode_clf, ds.healthy_baseline(), report)


def load_or_train() -> HealthModel:
    try:
        m = HealthModel.load()
        # sanity: ensure feature schema matches current dataset code
        _ = m.failure_prob({"air_temp": 300, "process_temp": 310, "rot_speed": 1500,
                            "torque": 40, "tool_wear": 10, "type_code": 0})
        return m
    except Exception:
        m = train()
        m.save()
        return m


if __name__ == "__main__":
    m = train()
    m.save()
    print("Trained:", m.report)
    demo = {"type_code": 0, "air_temp": 302.0, "process_temp": 311.5, "rot_speed": 1330,
            "torque": 62.0, "tool_wear": 216.0}
    print("degraded sample:", m.predict(demo), "| mode:", m.predict_mode(demo)["mode_label"])
    for c in m.attribute(demo):
        print("   ", c["label"], c["contribution"])
