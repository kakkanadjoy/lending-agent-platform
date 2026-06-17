"""Score loans with the trained early-warning model.

Loads the model from the MLflow registry by name (not a file path), so
promoting a new version in MLflow changes what serves here with no code
change. The score is a deterioration probability in [0,1] used to ORDER the
renewal queue and size the document chase — it prioritizes attention and
never decides anything.

If no model has been trained yet, scoring falls back to a transparent
heuristic so the rest of the platform still works during early development.
"""
from __future__ import annotations

import functools
import os

import numpy as np

from ews.features import build_features, FEATURE_NAMES

MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
REGISTERED_NAME = "ews-deterioration"


LOCAL_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "model_artifact", "model", "model.xgb"
)

@functools.lru_cache(maxsize=1)
def _model():
    """Load the EWS model. Priority:
    1. Local file (baked into Docker image — production path)
    2. MLflow registry (local dev with MLflow running)
    3. None -> heuristic fallback
    """
    # 1. Local file first (production)
    if os.path.exists(LOCAL_MODEL_PATH):
        try:
            import xgboost as xgb
            m = xgb.Booster()
            m.load_model(LOCAL_MODEL_PATH)
            return m
        except Exception:
            pass
    # 2. MLflow registry (local dev)
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_URI)
        return mlflow.xgboost.load_model(f"models:/{REGISTERED_NAME}/latest")
    except Exception:
        return None

def _heuristic(loan: dict) -> float:
    """Transparent stand-in when no model is loaded: a coverage drop and hot
    utilization both push the score up. Bounded to [0,1]."""
    f = build_features(loan)
    dscr, dscr_delta, _, leverage, utilization, high_util, _ = f
    score = 0.0
    if dscr < 1.20:
        score += 0.4
    if dscr_delta < 0:
        score += min(0.3, -dscr_delta)
    if leverage > 4.0:
        score += 0.2
    score += 0.1 * high_util
    return max(0.0, min(1.0, score))


def score_loan(loan: dict) -> float:
    """Deterioration risk in [0,1] for one loan."""
    model = _model()
    if model is None:
        return _heuristic(loan)
    import xgboost as xgb
    dmatrix = xgb.DMatrix(np.array([build_features(loan)], dtype=float))
    return float(model.predict(dmatrix)[0])


def score_many(loans: list[dict]) -> list[tuple[str, float]]:
    """Score a batch and return (loan_id, score) sorted worst-first — the
    renewal queue ordering."""
    scored = [(l["loan_id"], score_loan(l)) for l in loans]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored

def explain_loan(loan: dict) -> dict:
    """Return SHAP feature contributions for one loan."""
    model = _model()
    if model is None:
        return {}
    try:
        import shap
        import xgboost as xgb
        import pandas as pd

        features = build_features(loan)
        df = pd.DataFrame([features], columns=FEATURE_NAMES)

        # Use Booster's built-in SHAP prediction (no TreeExplainer needed)
        dmatrix = xgb.DMatrix(df)
        shap_matrix = model.predict(dmatrix, pred_contribs=True)

        # pred_contribs returns [feature_shaps..., bias] — last col is bias
        shap_vals = shap_matrix[0][:-1]
        base_value = float(shap_matrix[0][-1])

        contributions = {
            name: round(float(val), 4)
            for name, val in zip(FEATURE_NAMES, shap_vals)
        }
        contributions = dict(
            sorted(contributions.items(),
                   key=lambda x: abs(x[1]), reverse=True)
        )
        return {
            "score": round(score_loan(loan), 4),
            "base_value": round(base_value, 4),
            "contributions": contributions,
        }
    except Exception as e:
        return {"error": str(e)}