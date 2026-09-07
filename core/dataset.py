"""
Real-dataset loader — the UCI **AI4I 2020 Predictive Maintenance** dataset.

10,000 rows of machine telemetry with a binary machine-failure label and five
independent failure-mode flags (TWF/HDF/PWF/OSF/RNF). It is a canonical public
benchmark for predictive maintenance, which gives the model real provenance while
remaining fully shareable. We engineer three physically-meaningful features
(power, temperature differential, overstrain) that map directly onto the
documented failure modes, then expose a clean training frame.

Dataset: Matzka, S. (2020). AI4I 2020 Predictive Maintenance Dataset.
UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

from .config import DATASET_CSV

# Model input features (5 raw + 3 engineered + product-quality tier).
RAW = ["air_temp", "process_temp", "rot_speed", "torque", "tool_wear"]
ENGINEERED = ["power_w", "temp_diff", "overstrain"]
FEATURES = ["type_code"] + RAW + ENGINEERED

FEATURE_LABELS = {
    "type_code":    "Product quality tier",
    "air_temp":     "Air temperature (K)",
    "process_temp": "Process temperature (K)",
    "rot_speed":    "Rotational speed (rpm)",
    "torque":       "Torque (Nm)",
    "tool_wear":    "Tool wear (min)",
    "power_w":      "Mechanical power (W)",
    "temp_diff":    "Process–air ΔT (K)",
    "overstrain":   "Overstrain (tool-wear·torque)",
}

# Failure modes we model (RNF is random noise in the source data — dropped).
MODES = ["TWF", "HDF", "PWF", "OSF"]
MODE_LABELS = {
    "TWF": "Tool Wear Failure",
    "HDF": "Heat-Dissipation Failure",
    "PWF": "Power Failure",
    "OSF": "Overstrain Failure",
    "NONE": "No dominant mode",
}
TYPE_CODE = {"L": 0, "M": 1, "H": 2}


def _engineer(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["power_w"] = df["torque"] * df["rot_speed"] * (2 * math.pi / 60.0)
    df["temp_diff"] = df["process_temp"] - df["air_temp"]
    df["overstrain"] = df["tool_wear"] * df["torque"]
    return df


def load_raw() -> pd.DataFrame:
    """Load AI4I 2020 and normalise column names to our schema."""
    if not DATASET_CSV.exists():
        raise FileNotFoundError(
            f"AI4I dataset not found at {DATASET_CSV}. Run `python -m core.dataset` "
            f"or place ai4i2020.csv in the data/ directory."
        )
    df = pd.read_csv(DATASET_CSV)
    df = df.rename(columns={
        "Type": "type",
        "Air temperature [K]": "air_temp",
        "Process temperature [K]": "process_temp",
        "Rotational speed [rpm]": "rot_speed",
        "Torque [Nm]": "torque",
        "Tool wear [min]": "tool_wear",
        "Machine failure": "failure",
    })
    df["type_code"] = df["type"].map(TYPE_CODE).fillna(0).astype(int)
    return _engineer(df)


def training_frame() -> pd.DataFrame:
    """Return the engineered frame with binary `failure` and a `mode` label."""
    df = load_raw()

    def dominant_mode(row) -> str:
        for m in MODES:                       # priority order; RNF ignored
            if row.get(m, 0) == 1:
                return m
        return "NONE"

    df["mode"] = df.apply(dominant_mode, axis=1)
    return df


def features_frame(feats: dict) -> pd.DataFrame:
    """Build a single-row model-input frame from a live feature dict, computing
    the engineered features so callers only supply the raw sensor values."""
    row = dict(feats)
    row.setdefault("power_w", row["torque"] * row["rot_speed"] * (2 * math.pi / 60.0))
    row.setdefault("temp_diff", row["process_temp"] - row["air_temp"])
    row.setdefault("overstrain", row["tool_wear"] * row["torque"])
    return pd.DataFrame([[row[f] for f in FEATURES]], columns=FEATURES)


def healthy_baseline() -> dict:
    """Median feature values across healthy rows — the counterfactual for local
    attribution (‘how much does each feature raise risk vs a healthy machine’)."""
    df = training_frame()
    healthy = df[df["failure"] == 0]
    return {f: float(healthy[f].median()) for f in FEATURES}


if __name__ == "__main__":
    d = training_frame()
    print("rows:", len(d), "| failures:", int(d.failure.sum()))
    print("mode distribution:", d[d.failure == 1]["mode"].value_counts().to_dict())
    print("healthy baseline:", {k: round(v, 1) for k, v in healthy_baseline().items()})
