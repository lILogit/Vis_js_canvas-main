"""T3 simulate tests — branch payoffs, DTI flagging, reserve depletion, ranking."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulate.payoff import BRANCH_IDS, REFERENCE_SCENARIO, compute_branch
from simulate.recommend import recommend, score_branch
from simulate.runner import simulate

# ── Reference values (computed from annuity formula, seed=REFERENCE_SCENARIO) ─
# P=2_400_000, r=0.049/12, n=216 months
_REF = {
    "keep_as_is": {
        "monthly_payment": 16743.500190,
        "total_interest":  1216596.041049,
        "interest_saved":  0.0,
        "months":          216.0,
        "reserve_after":   800_000.0,
        "dti":             0.196982,
    },
    "partial_prepay": {
        "monthly_payment": 16743.500190,
        "total_interest":  657470.501396,
        "interest_saved":  559125.539653,
        "months":          152.744078,
        "reserve_after":   300_000.0,
        "dti":             0.196982,
    },
    "full_prepay": {
        "monthly_payment": 0.0,
        "total_interest":  0.0,
        "interest_saved":  1216596.041049,
        "months":          0.0,
        "reserve_after":   -1_600_000.0,
        "dti":             0.0,
    },
    "refinance": {
        "monthly_payment": 15853.872744,
        "total_interest":  1039436.512656,
        "interest_saved":  177159.528393,
        "months":          216.0,
        "reserve_after":   785_000.0,
        "dti":             0.186516,
    },
    "fixation_renewal": {
        "monthly_payment": 16231.790571,
        "total_interest":  1106066.763244,
        "interest_saved":  110529.277805,
        "months":          216.0,
        "reserve_after":   800_000.0,
        "dti":             0.190962,
    },
    "extend_term": {
        "monthly_payment": 13339.979471,
        "total_interest":  1601993.841326,
        "interest_saved":  -385397.800277,
        "months":          300.0,
        "reserve_after":   800_000.0,
        "dti":             0.156941,
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_branch(branch_id: str, key: str, tol: float = 1.0) -> None:
    result = compute_branch(branch_id)
    expected = _REF[branch_id][key]
    assert abs(result[key] - expected) <= tol, (
        f"{branch_id}[{key}]: got {result[key]:.6f}, expected {expected:.6f}"
    )

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_all_branches_produce_finite_output():
    """All 6 branches produce finite, non-NaN numerical output."""
    for bid in BRANCH_IDS:
        r = compute_branch(bid)
        for key in ("monthly_payment", "total_interest", "interest_saved",
                    "months", "reserve_after", "dti"):
            assert math.isfinite(r[key]), f"{bid}[{key}] is not finite"


def test_reference_scenario_payoffs():
    """Numbers match hand-calculated reference within 1 CZK."""
    for bid in BRANCH_IDS:
        r = compute_branch(bid)
        for key in ("monthly_payment", "total_interest", "interest_saved",
                    "reserve_after"):
            assert abs(r[key] - _REF[bid][key]) <= 1.0, (
                f"{bid}[{key}]: got {r[key]:.4f}, expected {_REF[bid][key]:.4f}"
            )
        # DTI within 0.001 (three decimal places)
        assert abs(r["dti"] - _REF[bid]["dti"]) <= 0.001, (
            f"{bid}[dti]: got {r['dti']:.6f}, expected {_REF[bid]['dti']:.6f}"
        )


def test_interest_saved_consistency():
    """interest_saved + total_interest == baseline total_interest for every branch."""
    baseline = compute_branch("keep_as_is")["total_interest"]
    for bid in BRANCH_IDS:
        r = compute_branch(bid)
        assert abs((r["total_interest"] + r["interest_saved"]) - baseline) <= 1.0, \
            f"{bid}: interest_saved + total_interest ≠ baseline"


def test_baseline_has_highest_interest():
    """keep_as_is has more total interest than any interest-reducing variant."""
    baseline = compute_branch("keep_as_is")["total_interest"]
    for bid in ("refinance", "fixation_renewal", "partial_prepay", "full_prepay"):
        r = compute_branch(bid)
        assert r["total_interest"] < baseline, \
            f"{bid} should have less interest than keep_as_is"


def test_extend_term_has_negative_savings():
    """Extending the term costs more total interest — interest_saved is negative."""
    r = compute_branch("extend_term")
    assert r["interest_saved"] < 0, "extend_term should have negative interest_saved"


def test_full_prepay_zero_interest():
    """Full prepayment eliminates all interest."""
    r = compute_branch("full_prepay")
    assert r["total_interest"] == 0.0
    assert r["monthly_payment"] == 0.0
    assert r["months"] == 0


def test_dti_flagging_low_income():
    """With income=30k, all payment-bearing branches except extend_term exceed DTI 0.45."""
    low = dict(REFERENCE_SCENARIO, monthly_income=30_000)
    dti_threshold = 0.45
    # Borrowing branches must breach threshold
    for bid in ("keep_as_is", "partial_prepay", "refinance", "fixation_renewal"):
        r = compute_branch(bid, low)
        assert r["dti"] > dti_threshold, f"{bid} DTI should exceed {dti_threshold} at 30k income"
    # extend_term stays under threshold due to low payment
    r = compute_branch("extend_term", low)
    assert r["dti"] < dti_threshold, "extend_term DTI should be < 0.45 even at 30k income"


def test_reserve_depletion_full_prepay():
    """full_prepay drives reserve below zero."""
    r = compute_branch("full_prepay")
    assert r["reserve_after"] < 0


def test_reserve_depletion_partial_prepay_exceeds_savings():
    """partial_prepay with prepay_amount > reserve drives reserve below zero."""
    over = dict(REFERENCE_SCENARIO, prepay_amount=900_000)
    r = compute_branch("partial_prepay", over)
    assert r["reserve_after"] < 0


def test_partial_prepay_reserve_reduced_by_prepay():
    """partial_prepay reduces reserve by exactly the prepay_amount."""
    r = compute_branch("partial_prepay")
    expected = REFERENCE_SCENARIO["reserve"] - REFERENCE_SCENARIO["prepay_amount"]
    assert abs(r["reserve_after"] - expected) < 0.01


def test_partial_prepay_shorter_term():
    """partial_prepay results in fewer months than keep_as_is."""
    base    = compute_branch("keep_as_is")
    prepaid = compute_branch("partial_prepay")
    assert prepaid["months"] < base["months"]


def test_recommendation_top3_stable():
    """recommend() returns the same top-3 ranking on repeated calls (deterministic)."""
    results = [compute_branch(bid) for bid in BRANCH_IDS]
    first_ranking = [r["branch"] for r in recommend(results)]
    for _ in range(9):
        ranking = [r["branch"] for r in recommend(results)]
        assert ranking == first_ranking, "Ranking changed between calls"


def test_recommendation_excludes_full_prepay_from_top3():
    """full_prepay should not appear in top-3 due to negative reserve penalty."""
    results = [compute_branch(bid) for bid in BRANCH_IDS]
    top3_branches = {r["branch"] for r in recommend(results)}
    assert "full_prepay" not in top3_branches


def test_simulate_returns_six_branches():
    """simulate() returns results for all 6 mortgage branches."""
    result = simulate([], mode="deterministic")
    assert result is not None
    assert len(result["branches"]) == 6
    assert len(result["recommendations"]) == 3
    branch_ids = {b["branch"] for b in result["branches"]}
    assert branch_ids == set(BRANCH_IDS)


def test_simulate_deterministic_matches_payoff():
    """simulate() branch values match direct compute_branch() calls."""
    result = simulate([], initial_state=REFERENCE_SCENARIO)
    for b in result["branches"]:
        direct = compute_branch(b["branch"])
        assert abs(b["monthly_payment"] - direct["monthly_payment"]) < 0.01


def test_simulate_custom_scenario():
    """simulate() respects a custom initial_state scenario."""
    custom = dict(REFERENCE_SCENARIO, annual_rate=0.035)
    result = simulate([], initial_state=custom)
    # Lower rate → lower monthly payment
    keep = next(b for b in result["branches"] if b["branch"] == "keep_as_is")
    base = compute_branch("keep_as_is", REFERENCE_SCENARIO)
    assert keep["monthly_payment"] < base["monthly_payment"]
