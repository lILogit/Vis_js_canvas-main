"""
Mortgage branch payoff calculations.
All values in CZK. Annuity formula: P·r·(1+r)^n / ((1+r)^n − 1).
"""
from __future__ import annotations
import math

REFERENCE_SCENARIO: dict = {
    "principal":       2_400_000,
    "annual_rate":     0.049,
    "years_remaining": 18,
    "monthly_income":  85_000,
    "reserve":         800_000,
    "prepay_amount":   500_000,
    "alt_rate":        0.042,
    "alt_fees":        15_000,
    "renewal_rate":    0.045,
    "extend_years":    25,
}

BRANCH_IDS: list[str] = [
    "keep_as_is",
    "partial_prepay",
    "full_prepay",
    "refinance",
    "fixation_renewal",
    "extend_term",
]


def annuity_payment(principal: float, annual_rate: float, years: int) -> float:
    r = annual_rate / 12
    n = years * 12
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def months_to_payoff(principal: float, annual_rate: float, monthly: float) -> float:
    """Exact (fractional) months to retire principal at a fixed monthly payment."""
    r = annual_rate / 12
    if monthly <= principal * r:
        return math.inf
    return math.log(monthly / (monthly - principal * r)) / math.log(1 + r)


def compute_branch(branch_id: str, scenario: dict | None = None) -> dict:
    """
    Compute payoff metrics for one mortgage strategy branch.

    Returns a dict with keys:
      branch, monthly_payment, total_interest, interest_saved,
      months, reserve_after, dti
    """
    s = scenario if scenario is not None else REFERENCE_SCENARIO
    principal = float(s["principal"])
    rate      = float(s["annual_rate"])
    years     = int(s["years_remaining"])
    income    = float(s["monthly_income"])
    reserve   = float(s["reserve"])

    base_monthly  = annuity_payment(principal, rate, years)
    base_interest = base_monthly * years * 12 - principal

    if branch_id == "keep_as_is":
        return dict(
            branch="keep_as_is",
            monthly_payment=base_monthly,
            total_interest=base_interest,
            interest_saved=0.0,
            months=years * 12,
            reserve_after=reserve,
            dti=base_monthly / income,
        )

    if branch_id == "partial_prepay":
        prepay    = float(s["prepay_amount"])
        new_p     = principal - prepay
        months    = months_to_payoff(new_p, rate, base_monthly)
        interest  = base_monthly * months - new_p
        return dict(
            branch="partial_prepay",
            monthly_payment=base_monthly,
            total_interest=interest,
            interest_saved=base_interest - interest,
            months=months,
            reserve_after=reserve - prepay,
            dti=base_monthly / income,
        )

    if branch_id == "full_prepay":
        return dict(
            branch="full_prepay",
            monthly_payment=0.0,
            total_interest=0.0,
            interest_saved=base_interest,
            months=0,
            reserve_after=reserve - principal,
            dti=0.0,
        )

    if branch_id == "refinance":
        alt_rate = float(s["alt_rate"])
        fees     = float(s["alt_fees"])
        monthly  = annuity_payment(principal, alt_rate, years)
        interest = monthly * years * 12 - principal + fees
        return dict(
            branch="refinance",
            monthly_payment=monthly,
            total_interest=interest,
            interest_saved=base_interest - interest,
            months=years * 12,
            reserve_after=reserve - fees,
            dti=monthly / income,
        )

    if branch_id == "fixation_renewal":
        renewal_rate = float(s["renewal_rate"])
        monthly      = annuity_payment(principal, renewal_rate, years)
        interest     = monthly * years * 12 - principal
        return dict(
            branch="fixation_renewal",
            monthly_payment=monthly,
            total_interest=interest,
            interest_saved=base_interest - interest,
            months=years * 12,
            reserve_after=reserve,
            dti=monthly / income,
        )

    if branch_id == "extend_term":
        renewal_rate = float(s["renewal_rate"])
        ext_years    = int(s["extend_years"])
        monthly      = annuity_payment(principal, renewal_rate, ext_years)
        interest     = monthly * ext_years * 12 - principal
        return dict(
            branch="extend_term",
            monthly_payment=monthly,
            total_interest=interest,
            interest_saved=base_interest - interest,
            months=ext_years * 12,
            reserve_after=reserve,
            dti=monthly / income,
        )

    raise ValueError(f"Unknown branch: {branch_id!r}")
