"""
Five-gate enrichment pipeline.

Gate order (mandatory):
  1. Schema validation    — already enforced by classify_event() before gates run
  2. Credibility gate     — source_credibility × extraction_confidence ≥ 0.75
  3. Bounded shift        — proposed delta ≤ MAX_SHIFT_PER_CYCLE
  4. Grammar re-check     — in-memory mutation passes chain validate()
  5. Circuit breaker      — no branch payoff shifts by > 15%
"""
from __future__ import annotations

# ── Constants ─────────────────────────────────────────────────────────────────

SOURCE_CREDIBILITY: dict[str, float] = {
    "hn.cz":   0.88,
    "cnb.cz":  0.95,
    "unknown": 0.50,
}
CREDIBILITY_THRESHOLD   = 0.75
MAX_SHIFT_PER_CYCLE     = 0.10   # absolute rate shift cap per enrichment cycle
CIRCUIT_BREAKER_THRESH  = 0.15   # >15% payoff change triggers human gate

# Maps target_node_id → (scenario_key, chain_node_id)
_TARGET_MAP: dict[str, tuple[str, str]] = {
    "AltBankOffer.rate":          ("alt_rate",    "alt_bank_offer"),
    "RenewalOffer.rate":          ("renewal_rate", "renewal_offer"),
    "MortgageActive.annual_rate": ("annual_rate",  "mortgage_active"),
    "FixationEndingSoon":         ("confidence",   "fixation_ending_soon"),
    "RateRegime2028":             ("confidence",   "rate_regime_2028"),
    "MonthlyIncome":              ("confidence",   "monthly_income"),
    "SavingsReserve":             ("confidence",   "savings_reserve"),
}


def get_source_credibility(source: str) -> float:
    return SOURCE_CREDIBILITY.get(source, SOURCE_CREDIBILITY["unknown"])


def get_current_value(chain: dict, target_node_id: str) -> float | None:
    """Return the current scenario value for a target, respecting any prior overrides."""
    from simulate.payoff import REFERENCE_SCENARIO  # noqa: PLC0415
    info = _TARGET_MAP.get(target_node_id)
    if info is None:
        return None
    key = info[0]
    overrides = chain.get("meta", {}).get("scenario_overrides", {})
    return overrides.get(key, REFERENCE_SCENARIO.get(key))


# ── Individual gates ──────────────────────────────────────────────────────────

def _gate_credibility(event: dict, source_credibility: float) -> tuple[bool, str]:
    score = source_credibility * event.get("extraction_confidence", 0.0)
    if score < CREDIBILITY_THRESHOLD:
        return False, (
            f"credibility gate failed: {source_credibility:.2f} × "
            f"{event['extraction_confidence']:.2f} = {score:.3f} < {CREDIBILITY_THRESHOLD}"
        )
    return True, f"credibility OK ({score:.3f})"


def _gate_bounded_shift(
    event: dict, old_value: float
) -> tuple[bool, str, float, float, bool]:
    """
    Returns (passed, reason, shift_proposed, shift_applied, was_capped).
    shift_applied is the actual delta that will be applied (capped if necessary).
    """
    hint = event.get("new_value_hint")
    if hint is None:
        return True, "no new_value_hint — bounded shift N/A", 0.0, 0.0, False
    shift_proposed = old_value - hint
    shift_applied  = max(-MAX_SHIFT_PER_CYCLE, min(MAX_SHIFT_PER_CYCLE, shift_proposed))
    was_capped     = abs(shift_applied) < abs(shift_proposed)
    return True, "bounded shift OK", shift_proposed, shift_applied, was_capped


def _gate_grammar(chain: dict, event: dict, new_value: float) -> tuple[bool, str]:
    """Apply mutation in-memory; run validate(); abort if any error-severity issue."""
    import json  # noqa: PLC0415
    from chain import io as chain_io  # noqa: PLC0415
    from chain.validate import validate  # noqa: PLC0415

    # Shallow-copy chain with the proposed scenario override
    info = _TARGET_MAP.get(event.get("target_node_id", ""))
    if info is None:
        return True, "grammar re-check skipped (no target map entry)"

    chain_copy = json.loads(json.dumps(chain))  # deep copy via JSON round-trip
    meta = chain_copy.setdefault("meta", {})
    meta.setdefault("scenario_overrides", {})[info[0]] = new_value

    causal = chain_io.from_dict(chain_copy)
    issues = validate(causal)
    errors = [i for i in issues if i.get("severity") == "error"]
    if errors:
        msgs = "; ".join(i["message"] for i in errors[:3])
        return False, f"grammar re-check failed: {msgs}"
    return True, "grammar OK"


def _gate_circuit_breaker(
    chain: dict, event: dict, new_value: float
) -> tuple[bool, str]:
    """Run T3 simulation before/after; block if any branch payoff shifts > 15%."""
    from simulate.payoff import BRANCH_IDS, REFERENCE_SCENARIO, compute_branch  # noqa: PLC0415

    info = _TARGET_MAP.get(event.get("target_node_id", ""))
    if info is None:
        return True, "circuit breaker skipped (no target map entry)"

    overrides = chain.get("meta", {}).get("scenario_overrides", {})
    scenario_before = dict(REFERENCE_SCENARIO, **overrides)
    scenario_after  = dict(scenario_before, **{info[0]: new_value})

    for bid in BRANCH_IDS:
        before = compute_branch(bid, scenario_before)["total_interest"]
        after  = compute_branch(bid, scenario_after)["total_interest"]
        if before != 0:
            shift_pct = abs(after - before) / abs(before)
            if shift_pct > CIRCUIT_BREAKER_THRESH:
                return False, (
                    f"circuit breaker: branch '{bid}' payoff shift "
                    f"{shift_pct:.1%} > {CIRCUIT_BREAKER_THRESH:.0%}"
                )
    return True, "circuit breaker OK"


# ── Public entry point ────────────────────────────────────────────────────────

class GateResult:
    __slots__ = ("passed", "reason", "gate", "shift_proposed",
                 "shift_applied", "shift_capped", "new_value")

    def __init__(self, *, passed: bool, reason: str, gate: str,
                 shift_proposed: float = 0.0, shift_applied: float = 0.0,
                 shift_capped: bool = False, new_value: float | None = None):
        self.passed         = passed
        self.reason         = reason
        self.gate           = gate
        self.shift_proposed = shift_proposed
        self.shift_applied  = shift_applied
        self.shift_capped   = shift_capped
        self.new_value      = new_value


def run_gates(event: dict, chain: dict, source: str = "unknown") -> GateResult:
    """
    Run all 5 gates in canonical order. Return on first failure.

    Gate 1 (schema validation) is performed by classify_event() before calling here.
    """
    sc = get_source_credibility(source)

    # Gate 2 — credibility
    ok, reason = _gate_credibility(event, sc)
    if not ok:
        return GateResult(passed=False, reason=reason, gate="credibility")

    # Resolve old value for gates 3-5
    old_value = get_current_value(chain, event.get("target_node_id", ""))
    if old_value is None:
        return GateResult(passed=False, reason="unknown target_node_id", gate="schema")

    # Gate 3 — bounded shift
    ok, reason, shift_proposed, shift_applied, was_capped = _gate_bounded_shift(event, old_value)
    new_value = old_value - shift_applied if shift_applied != 0.0 else (
        event.get("new_value_hint", old_value)
    )

    # Gate 4 — grammar re-check
    ok, reason = _gate_grammar(chain, event, new_value)
    if not ok:
        return GateResult(passed=False, reason=reason, gate="grammar",
                          shift_proposed=shift_proposed, shift_applied=shift_applied,
                          shift_capped=was_capped, new_value=new_value)

    # Gate 5 — circuit breaker
    ok, reason = _gate_circuit_breaker(chain, event, new_value)
    if not ok:
        return GateResult(passed=False, reason=reason, gate="circuit_breaker",
                          shift_proposed=shift_proposed, shift_applied=shift_applied,
                          shift_capped=was_capped, new_value=new_value)

    return GateResult(
        passed=True, reason="all gates passed", gate="none",
        shift_proposed=shift_proposed, shift_applied=shift_applied,
        shift_capped=was_capped, new_value=new_value,
    )
