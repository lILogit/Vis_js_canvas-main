"""E1-E6 event classification metadata."""
from __future__ import annotations

# Valid event classes and whether they are auto-eligible for application
E_CLASS_META: dict[str, dict] = {
    "E1": {"name": "value_update",    "auto_apply": True,  "description": "Quantitative value or certainty update to an existing node field"},
    "E2": {"name": "new_entity",      "auto_apply": False, "description": "New node candidate not yet in the chain"},
    "E3": {"name": "edge_change",     "auto_apply": False, "description": "Modification to a causal edge (relation, weight, condition)"},
    "E4": {"name": "archetype_change","auto_apply": False, "description": "Node archetype or type correction"},
    "E5": {"name": "deprecation",     "auto_apply": False, "description": "Signal that a node or edge should be deprecated"},
    "E6": {"name": "contradiction",   "auto_apply": False, "description": "Evidence contradicts existing causal structure"},
}

# Recognised target node IDs (must match extraction schema enum)
VALID_TARGET_IDS: frozenset[str] = frozenset({
    "AltBankOffer.rate",
    "RenewalOffer.rate",
    "MortgageActive.annual_rate",
    "FixationEndingSoon",
    "RateRegime2028",
    "MonthlyIncome",
    "SavingsReserve",
})


class ClassifyError(ValueError):
    """Raised when an event cannot be classified due to a structural problem."""


def classify_event(event: dict) -> dict:
    """
    Validate and enrich a raw extracted event with E-class metadata.

    Returns a new dict with added keys:
      - auto_apply: bool
      - class_name: str (human-readable class name)
      - valid: True

    Raises ClassifyError on schema violations.
    """
    cls = event.get("class")
    if cls not in E_CLASS_META:
        raise ClassifyError(f"Unknown event class {cls!r}; expected one of {sorted(E_CLASS_META)}")

    target = event.get("target_node_id")
    if not target:
        raise ClassifyError("Event missing 'target_node_id'")
    if target not in VALID_TARGET_IDS:
        raise ClassifyError(
            f"Unknown target_node_id {target!r}; "
            f"valid values: {sorted(VALID_TARGET_IDS)}"
        )

    for field in ("direction", "magnitude", "extraction_confidence", "text_span"):
        if field not in event:
            raise ClassifyError(f"Event missing required field '{field}'")

    meta = E_CLASS_META[cls]
    return {
        **event,
        "auto_apply":  meta["auto_apply"],
        "class_name":  meta["name"],
        "valid":       True,
    }
