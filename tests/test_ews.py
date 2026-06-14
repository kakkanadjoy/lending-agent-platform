"""EWS tests.

Feature logic is pure and tested without models. The scoring fallback works
with no trained model. The training test is marked slow (it trains XGBoost and
logs to MLflow) and includes a leakage guard: a model that scores a perfect
AUC on this data would mean the label leaked into a feature again.
"""
import pytest

from ews.features import build_features, label_of, FEATURE_NAMES


# ── feature logic, no models ────────────────────────────────────────────────

def test_feature_vector_has_fixed_length_and_order():
    loan = dict(dscr=1.3, dscr_prior=1.6, leverage=3.0,
                utilization=0.5, facility_type="revolving_line")
    f = build_features(loan)
    assert len(f) == len(FEATURE_NAMES)
    # dscr_delta = current - prior = 1.3 - 1.6 = -0.3
    assert f[FEATURE_NAMES.index("dscr_delta")] == pytest.approx(-0.3)


def test_missing_prior_assumes_flat_delta():
    loan = dict(dscr=1.4, leverage=2.0, facility_type="term_loan")
    f = build_features(loan)
    assert f[FEATURE_NAMES.index("dscr_delta")] == 0.0


def test_high_utilization_flag_only_for_hot_revolvers():
    hot = build_features(dict(dscr=1.5, utilization=0.9,
                              facility_type="revolving_line"))
    assert hot[FEATURE_NAMES.index("high_utilization")] == 1.0
    term = build_features(dict(dscr=1.5, utilization=0.9,
                               facility_type="term_loan"))
    assert term[FEATURE_NAMES.index("high_utilization")] == 0.0


def test_label_reads_planted_ground_truth():
    assert label_of({"ground_truth": {"deteriorated": True}}) == 1
    assert label_of({"ground_truth": {"deteriorated": False}}) == 0
    assert label_of({}) == 0


# ── scoring fallback (no trained model needed) ──────────────────────────────

def test_heuristic_scores_worse_for_eroding_coverage():
    from ews.score import _heuristic
    healthy = _heuristic(dict(dscr=1.6, dscr_prior=1.6, leverage=2.0,
                              utilization=0.4, facility_type="revolving_line"))
    eroding = _heuristic(dict(dscr=1.1, dscr_prior=1.5, leverage=4.3,
                              utilization=0.93, facility_type="revolving_line"))
    assert eroding > healthy


def test_score_many_orders_worst_first():
    from ews.score import score_many
    loans = [
        dict(loan_id="good", dscr=1.8, dscr_prior=1.8, leverage=2.0,
             utilization=0.3, facility_type="revolving_line", ground_truth={}),
        dict(loan_id="bad", dscr=1.05, dscr_prior=1.5, leverage=4.5,
             utilization=0.95, facility_type="revolving_line", ground_truth={}),
    ]
    order = [lid for lid, _ in score_many(loans)]
    assert order[0] == "bad"


# ── training (slow: trains XGBoost + logs to MLflow) ────────────────────────

@pytest.mark.slow
def test_training_is_good_but_not_perfect():
    """Trains against the live portfolio. AUC should be strong but < 0.99 —
    a perfect score would signal the label leaked into a feature."""
    pytest.importorskip("xgboost")
    pytest.importorskip("mlflow")
    from ews.train import train
    result = train(register=False)
    assert 0.60 < result["roc_auc"] < 0.99, result
