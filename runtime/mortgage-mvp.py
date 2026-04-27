"""Mortgage Strategy MVP — forged from chains/mortgage-mvp.causal.json"""
from __future__ import annotations

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
from dataclasses import dataclass
from forge.runtime import (
    ASSET, BLACKBOX, DECISION, EVENT, GATE, GOAL, STATE, TASK,
    causes, diverges_to, enables, frames, instantiates, precondition_of, triggers, simulate,
)

_forge_meta = {
    "source_chain":  "mortgage-mvp",
    "source_hash":   "sha256:ff43e09b5492d1db225d1d4643c2daed9cc3d34eb7c5d01584b83d104be5faa3",
    "forge_version": "1.0.0",
    "timestamp":     "2026-04-27T12:22:51Z",
    "last_enrichment": "ev_2026-04-27_hn_cz_01",
}

# ─── STATES ────────────────────────────────────────────────────────────────────

@STATE(rcde_id="fixation_ending_soon", certainty=0.9500, archetype="root_cause")
@dataclass
class FixationEndingSoon:
    """Current interest rate fixation expires in 3 months, opening a penalty-free renegotiation window under Czech mortgage law."""
    pass

@STATE(rcde_id="interest_minimized", certainty=0.8000, archetype="effect")
@dataclass
class InterestMinimized:
    """Total interest cost reduced by at least 250 000 CZK relative to keep-as-is baseline. Acceptable DTI maintained."""
    pass

@STATE(rcde_id="monthly_income", certainty=1.0000, archetype="moderator")
@dataclass
class MonthlyIncome:
    """Net monthly household income 85 000 CZK — denominator for DTI calculation."""
    pass

@STATE(rcde_id="mortgage_active", certainty=1.0000, archetype="root_cause")
@dataclass
class MortgageActive:
    """2 400 000 CZK principal at 4.9% annual rate, 18 years remaining on term."""
    pass

@STATE(rcde_id="payment_reduced", certainty=0.7500, archetype="effect")
@dataclass
class PaymentReduced:
    """Monthly mortgage payment reduced to below 14 000 CZK, bringing DTI under 0.17. Prioritises cash flow over total cost."""
    pass

@STATE(rcde_id="savings_reserve", certainty=1.0000, archetype="moderator")
@dataclass
class SavingsReserve:
    """Liquid savings of 800 000 CZK available for lump-sum prepayment or fee coverage."""
    pass

# ─── ASSETS ────────────────────────────────────────────────────────────────────

@ASSET(rcde_id="alt_bank_offer", certainty=0.7500, archetype="evidence", _evidence_refs=["ev_2026-04-27_hn_cz_01"])
@dataclass
class AltBankOffer:
    """Competitor refinancing offer: 4.20% rate, processing fee 15 000 CZK, requires credit reapproval (~4 months)."""
    rate: float = 0.0395

@ASSET(rcde_id="renewal_offer", certainty=0.8500, archetype="evidence")
@dataclass
class RenewalOffer:
    """Current bank renewal at 4.50% — no processing fee, immediate confirmation, same term or extended."""
    pass

# ─── EVENTS ────────────────────────────────────────────────────────────────────

@EVENT(rcde_id="rate_review_event", certainty=0.9500, archetype="mechanism")
@dataclass
class RateReviewEvent:
    """Bank initiates rate renegotiation at end of fixation period. Triggers evaluation of all available strategies."""
    pass

# ─── GATES ─────────────────────────────────────────────────────────────────────

@GATE(rcde_id="financial_viability_gate", certainty=0.9000, archetype="mechanism")
@dataclass
class FinancialViabilityGate:
    """Checks DTI ≤ 0.45 and sufficient reserve before allowing strategy selection. Blocks execution if thresholds not met."""
    pass

# ─── DECISIONS ─────────────────────────────────────────────────────────────────

@DECISION(rcde_id="mortgage_strategy", certainty=0.8500, archetype="mechanism")
@dataclass
class MortgageStrategy:
    """Chooses among 6 branches based on interest savings, DTI impact, reserve depletion, and time horizon. Scored decision with branch weights."""
    pass

# ─── TASKS ─────────────────────────────────────────────────────────────────────

@TASK(rcde_id="extend_term", certainty=0.7000, archetype="effect")
@dataclass
class ExtendTerm:
    """Extend remaining term to 25 years at 4.50%. Monthly drops to 13 363 CZK (DTI 15.7%) but total interest increases by 313k vs baseline."""
    pass

@TASK(rcde_id="fixation_renewal", certainty=0.8500, archetype="effect")
@dataclass
class FixationRenewal:
    """Renew with current bank at 4.50%, same term. Monthly 16 743 CZK, total interest savings ~280k CZK. Simplest option, no paperwork."""
    pass

@TASK(rcde_id="full_prepay", certainty=0.7000, archetype="effect")
@dataclass
class FullPrepay:
    """Full repayment at fixation end. Zero prepayment penalty under Czech law. Reserve goes negative — requires additional financing."""
    pass

@TASK(rcde_id="keep_as_is", certainty=0.9000, archetype="effect")
@dataclass
class KeepAsIs:
    """No action — continue at current 4.9% rate until next fixation. Monthly payment 17 109 CZK, total interest 1 295 619 CZK."""
    pass

@TASK(rcde_id="partial_prepay", certainty=0.8000, archetype="effect")
@dataclass
class PartialPrepay:
    """One-time 500 000 CZK lump-sum payment at fixation end. Reduces principal, shortens term by ~5 years. Reserve drops to 300k."""
    pass

@TASK(rcde_id="refinance", certainty=0.7500, archetype="effect")
@dataclass
class Refinance:
    """Switch to Alt Bank at 4.20% + 15 000 CZK fees. Monthly 16 234 CZK, total interest savings ~380k CZK. Requires ~4 months and credit reapproval."""
    pass

# ─── TERMINALS ─────────────────────────────────────────────────────────────────

@GOAL(rcde_id="mortgage_closed", certainty=0.9000, archetype="effect")
@dataclass
class MortgageClosed:
    """Mortgage fully repaid. No further interest liability."""
    pass

@BLACKBOX(rcde_id="rate_regime_2028", certainty=0.5000, archetype="mechanism")
@dataclass
class RateRegime2028:
    """Post-fixation interest rate environment. Mechanism intentionally absent — structural uncertainty that cannot be resolved before next fixation."""
    symptom: str = "Post-fixation interest rate environment. Mechanism intentionally absent — structural uncertainty that cannot be resolved before next fixation."

# ─── CHAIN ─────────────────────────────────────────────────────────────────────

CHAIN = [
    causes("fixation_ending_soon", "rate_review_event"),
    causes("mortgage_active", "rate_review_event"),
    diverges_to("financial_viability_gate", "mortgage_strategy"),
    diverges_to("mortgage_strategy", "extend_term"),
    diverges_to("mortgage_strategy", "fixation_renewal"),
    diverges_to("mortgage_strategy", "full_prepay"),
    diverges_to("mortgage_strategy", "keep_as_is"),
    diverges_to("mortgage_strategy", "partial_prepay"),
    diverges_to("mortgage_strategy", "refinance"),
    enables("alt_bank_offer", "refinance"),
    enables("renewal_offer", "extend_term"),
    enables("renewal_offer", "fixation_renewal"),
    enables("savings_reserve", "full_prepay"),
    enables("savings_reserve", "partial_prepay"),
    frames("rate_regime_2028", "extend_term"),
    frames("rate_regime_2028", "mortgage_strategy"),
    instantiates("extend_term", "payment_reduced"),
    instantiates("fixation_renewal", "interest_minimized"),
    instantiates("full_prepay", "mortgage_closed"),
    instantiates("keep_as_is", "mortgage_closed"),
    instantiates("partial_prepay", "interest_minimized"),
    instantiates("refinance", "interest_minimized"),
    precondition_of("monthly_income", "financial_viability_gate"),
    precondition_of("savings_reserve", "financial_viability_gate"),
    triggers("rate_review_event", "financial_viability_gate"),
]

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Chain : Mortgage Strategy MVP")
    print("Source: chains/mortgage-mvp.causal.json")
    print("Hash  : sha256:ff43e09b5492d1db225d1d4643c2daed9cc3d34eb7c5d01584b83d104be5faa3")
    result = simulate(CHAIN, mode="monte_carlo", n=10_000, seed=42)
    print(f"Simulation result: {result}")
