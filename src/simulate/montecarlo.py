"""
Monte Carlo path-probability simulation for the mortgage MVP chain.

Path probability per branch = Π certainties of all nodes on the causal path
(spine nodes + branch-specific ENABLES predecessors + branch task itself).
FRAMES edges are excluded — they are contextual, not causal.
"""
from __future__ import annotations

import random

from .payoff import BRANCH_IDS

# Declared certainties from chains/mortgage-mvp.causal.json
DEFAULT_CERTAINTIES: dict[str, float] = {
    "mortgage_active":          1.00,
    "fixation_ending_soon":     0.95,
    "monthly_income":           1.00,
    "savings_reserve":          1.00,
    "rate_review_event":        0.95,
    "financial_viability_gate": 0.90,
    "mortgage_strategy":        0.85,
    "alt_bank_offer":           0.75,
    "renewal_offer":            0.85,
    "keep_as_is":               0.90,
    "partial_prepay":           0.80,
    "full_prepay":              0.70,
    "refinance":                0.75,
    "fixation_renewal":         0.85,
    "extend_term":              0.70,
}

# Causal spine shared by all branches (CAUSES + TRIGGERS + PRECONDITION_OF spine)
_SPINE: list[str] = [
    "mortgage_active",
    "fixation_ending_soon",
    "monthly_income",
    "savings_reserve",
    "rate_review_event",
    "financial_viability_gate",
    "mortgage_strategy",
]

# Per-branch: spine nodes + ENABLES predecessors + branch task (deduplicated)
BRANCH_PATH_NODES: dict[str, list[str]] = {
    "keep_as_is":       _SPINE + ["keep_as_is"],
    # savings_reserve is already in spine; no extra enabler needed
    "partial_prepay":   _SPINE + ["partial_prepay"],
    "full_prepay":      _SPINE + ["full_prepay"],
    "refinance":        _SPINE + ["alt_bank_offer", "refinance"],
    "fixation_renewal": _SPINE + ["renewal_offer", "fixation_renewal"],
    "extend_term":      _SPINE + ["renewal_offer", "extend_term"],
}


def path_probability(branch_id: str, node_certainties: dict[str, float]) -> float:
    """P(branch) = Π certainties of all nodes on the causal path to this branch."""
    p = 1.0
    for nid in BRANCH_PATH_NODES[branch_id]:
        p *= node_certainties.get(nid, 1.0)
    return p


def all_path_probabilities(node_certainties: dict[str, float]) -> dict[str, float]:
    return {bid: path_probability(bid, node_certainties) for bid in BRANCH_IDS}


def monte_carlo(
    n: int = 10_000,
    seed: int = 42,
    sigma: float = 0.05,
    node_certainties: dict[str, float] | None = None,
) -> dict[str, dict]:
    """
    Simulate path probabilities with Gaussian noise on declared certainties.

    Each node's certainty is sampled as:
        c_sampled = clip(N(c_declared, sigma * c_declared), 0, 1)

    Args:
        n:                 Number of Monte Carlo runs.
        seed:              RNG seed for reproducibility.
        sigma:             Noise scale (fraction of declared certainty).
        node_certainties:  Override DEFAULT_CERTAINTIES if provided.

    Returns:
        {branch_id: {"mean_prob": float, "std_prob": float, "n": int}}
    """
    certs = node_certainties if node_certainties is not None else get_registry_certainties()
    rng = random.Random(seed)

    # All nodes that appear in any branch path
    all_nodes = {nid for path in BRANCH_PATH_NODES.values() for nid in path}

    acc: dict[str, list[float]] = {bid: [] for bid in BRANCH_IDS}

    for _ in range(n):
        sampled: dict[str, float] = {}
        for nid in all_nodes:
            c = certs.get(nid, 1.0)
            sampled[nid] = min(1.0, max(0.0, c + rng.gauss(0.0, sigma * c)))
        for bid in BRANCH_IDS:
            acc[bid].append(path_probability(bid, sampled))

    result: dict[str, dict] = {}
    for bid in BRANCH_IDS:
        samples = acc[bid]
        mean = sum(samples) / n
        variance = sum((x - mean) ** 2 for x in samples) / n
        result[bid] = {
            "mean_prob": mean,
            "std_prob":  variance ** 0.5,
            "n":         n,
        }
    return result


def get_registry_certainties() -> dict[str, float]:
    """Read declared certainties from the forge runtime registry if populated."""
    try:
        from forge.runtime import _REGISTRY  # noqa: PLC0415
        reg = {
            nid: cls._certainty
            for nid, (_, cls) in _REGISTRY.items()
            if hasattr(cls, "_certainty")
        }
        if reg:
            return reg
    except Exception:
        pass
    return dict(DEFAULT_CERTAINTIES)
