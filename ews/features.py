"""Features for the early-warning model.

Deterioration is about *change*, not just where a borrower sits today. A
business at 1.3x coverage that was at 1.8x a year ago is a different story
from one steady at 1.3x — so the features lean on year-over-year deltas and
behavioral signals, not raw levels alone.

Training and scoring both call build_features(), so a loan is turned into the
exact same numbers in both places. That sounds obvious but it's the most
common way ML models quietly break: features computed one way in training and
another at serving time. One function, one definition.
"""
from __future__ import annotations

# The feature columns, in a fixed order. XGBoost takes a plain numeric vector,
# so order matters and must be identical at train and score time.
FEATURE_NAMES = [
    "dscr",
    "dscr_delta",          # current minus prior; negative = coverage eroding
    "dscr_pct_change",     # proportional drop, scale-free
    "leverage",
    "utilization",
    "high_utilization",    # 1 if a revolver is running hot (>0.85)
    "is_revolver",
]


def _f(value, default=0.0):
    """Coerce a possibly-None / Decimal value to float."""
    return default if value is None else float(value)


def build_features(loan: dict) -> list[float]:
    """One loan -> its feature vector, in FEATURE_NAMES order."""
    dscr = _f(loan.get("dscr"))
    dscr_prior = _f(loan.get("dscr_prior"), dscr)   # no prior -> assume flat
    leverage = _f(loan.get("leverage"))
    utilization = _f(loan.get("utilization"))
    is_revolver = 1.0 if loan.get("facility_type") == "revolving_line" else 0.0

    dscr_delta = dscr - dscr_prior
    dscr_pct_change = (dscr_delta / dscr_prior) if dscr_prior else 0.0
    high_utilization = 1.0 if (is_revolver and utilization > 0.85) else 0.0

    return [dscr, dscr_delta, dscr_pct_change, leverage,
            utilization, high_utilization, is_revolver]


def label_of(loan: dict) -> int:
    """The training target: did this credit deteriorate? Planted in Step 5's
    ground_truth, so the model learns against known truth."""
    return 1 if loan.get("ground_truth", {}).get("deteriorated") else 0
