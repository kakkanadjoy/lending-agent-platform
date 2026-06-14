"""Train the early-warning model and track it in MLflow.

Pulls the portfolio, builds features, trains an XGBoost classifier on the
planted deterioration label, and logs everything to MLflow: parameters,
metrics, feature importances, and the model artifact. The run is also
registered in the MLflow Model Registry under a stable name, so serving code
loads "the production EWS model" by name rather than by a file path someone
has to remember.

    python -m ews.train

MLflow UI: http://localhost:5000
"""
from __future__ import annotations

import os

import mlflow
import mlflow.xgboost
import numpy as np
import xgboost as xgb
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

from db import repository as repo
from ews.features import FEATURE_NAMES, build_features, label_of

MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT = "ews-deterioration"
REGISTERED_NAME = "ews-deterioration"


def _load_portfolio(url=None):
    with repo.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT loan_id, facility_type, dscr, dscr_prior, "
                        "leverage, utilization, ground_truth FROM loans")
            loans = cur.fetchall()
    X = np.array([build_features(l) for l in loans], dtype=float)
    y = np.array([label_of(l) for l in loans], dtype=int)
    return X, y


def train(url=None, register=True):
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)

    X, y = _load_portfolio(url)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y)

    params = {
        "objective": "binary:logistic",
        "max_depth": 4,
        "eta": 0.1,
        "subsample": 0.9,
        "eval_metric": "aucpr",
        "n_estimators": 120,
    }

    with mlflow.start_run() as run:
        mlflow.log_params(params)
        mlflow.log_param("n_features", len(FEATURE_NAMES))
        mlflow.log_param("n_samples", len(y))
        mlflow.log_param("positive_rate", round(float(y.mean()), 4))

        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train)

        proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, proba)
        ap = average_precision_score(y_test, proba)
        mlflow.log_metric("roc_auc", float(auc))
        mlflow.log_metric("avg_precision", float(ap))

        # Feature importances, named — so the model is inspectable, not a box.
        for name, imp in zip(FEATURE_NAMES, model.feature_importances_):
            mlflow.log_metric(f"importance__{name}", float(imp))

        if register:
            mlflow.xgboost.log_model(model.get_booster(), artifact_path="model",
                                     registered_model_name=REGISTERED_NAME)
        else:
            mlflow.xgboost.log_model(model.get_booster(), artifact_path="model")

        print(f"Trained EWS. ROC-AUC={auc:.3f}  AvgPrecision={ap:.3f}  "
              f"run_id={run.info.run_id}")
        return {"roc_auc": float(auc), "avg_precision": float(ap),
                "run_id": run.info.run_id}


if __name__ == "__main__":
    train()
