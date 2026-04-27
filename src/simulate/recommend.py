"""Branch ranking and human-readable recommendation generation."""
from __future__ import annotations

_RESERVE_FLOOR = 100_000   # below this → heavy reserve penalty
_RESERVE_WARN  = 400_000   # below this → mild reserve penalty
_DTI_MAX       = 0.45      # above this → DTI penalty

_LABELS: dict[str, str] = {
    "keep_as_is":       "Ponechat beze změny",
    "partial_prepay":   "Mimořádná splátka 500k",
    "full_prepay":      "Úplné splacení",
    "refinance":        "Refinancování @ 4.20%",
    "fixation_renewal": "Nová fixace @ 4.50%",
    "extend_term":      "Prodloužit na 25 let",
}

_CAVEATS: dict[str, str] = {
    "keep_as_is":       "žádná úspora",
    "partial_prepay":   "rezerva klesne na 300k (hraniční)",
    "full_prepay":      "rezerva záporná — vyžaduje externí zdroje",
    "refinance":        "poplatky 15k, ~4 měsíce procesu",
    "fixation_renewal": "méně agresivní úspora než refinancování",
    "extend_term":      "celkový úrok vyšší než výchozí stav",
}


def score_branch(result: dict, scenario: dict) -> float:
    """
    Composite score in [−2, 1]. Higher is better.

    Components:
      0.50 × interest_saved (normalised 0-1, capped)
      0.35 × reserve health (0-1; −1 if negative)
      0.15 × DTI factor (0 or 1)
    Penalties override raw scores when reserve < 0 or DTI > threshold.
    """
    baseline = result["total_interest"] + result["interest_saved"]
    savings_ratio = (
        max(-1.0, min(1.0, result["interest_saved"] / baseline))
        if baseline > 0 else 0.0
    )

    reserve      = result["reserve_after"]
    orig_reserve = float(scenario.get("reserve", 800_000))
    if reserve < 0:
        reserve_score = -1.0
    elif reserve < _RESERVE_FLOOR:
        reserve_score = 0.1
    elif reserve < _RESERVE_WARN:
        reserve_score = 0.6
    else:
        reserve_score = min(1.0, reserve / orig_reserve) if orig_reserve > 0 else 1.0

    dti_score = 0.0 if result["dti"] > _DTI_MAX else 1.0

    return 0.50 * savings_ratio + 0.35 * reserve_score + 0.15 * dti_score


def recommend(results: list[dict], scenario: dict | None = None) -> list[dict]:
    """Rank all branches; return top-3 with rationale."""
    if scenario is None:
        from .payoff import REFERENCE_SCENARIO
        scenario = REFERENCE_SCENARIO

    scored = sorted(
        ((score_branch(r, scenario), r) for r in results),
        key=lambda x: x[0],
        reverse=True,
    )

    top3 = []
    for rank, (score, r) in enumerate(scored[:3], start=1):
        bid   = r["branch"]
        saved = round(r["interest_saved"])
        dti_pct = round(r["dti"] * 100, 1)
        res   = round(r["reserve_after"])
        label = _LABELS.get(bid, bid)
        caveat = _CAVEATS.get(bid, "")
        reason = (
            f"ušetří {saved:,} CZK, DTI {dti_pct}%, "
            f"rezerva {res:,} CZK"
        )
        top3.append({
            "rank":           rank,
            "branch":         bid,
            "label":          label,
            "score":          round(score, 3),
            "interest_saved": saved,
            "reserve_after":  res,
            "dti":            round(r["dti"], 4),
            "reason":         reason,
            "caveat":         caveat,
        })
    return top3
