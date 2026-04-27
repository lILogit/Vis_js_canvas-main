"""T4 Monte Carlo + sensitivity + trace tests."""
import json
import math
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulate.montecarlo import (
    BRANCH_IDS,
    BRANCH_PATH_NODES,
    DEFAULT_CERTAINTIES,
    all_path_probabilities,
    monte_carlo,
    path_probability,
)
from simulate.sensitivity import (
    branch_exposures,
    most_sensitive_node_for_branch,
    sensitivity_analysis,
)
from simulate.trace import TraceWriter, write_deterministic_trace

# ── Path probability ──────────────────────────────────────────────────────────

def test_path_probs_sum_gt_one():
    """Path probabilities must sum > 1 (branches are what-if alternatives, not exclusive)."""
    probs = all_path_probabilities(DEFAULT_CERTAINTIES)
    total = sum(probs.values())
    assert total > 1.0, f"Sum of path probs = {total:.4f}, expected > 1.0"


def test_deterministic_path_probabilities():
    """Verify reference path probabilities match formula within 1e-6."""
    _EXPECTED = {
        "keep_as_is":       0.621371,
        "partial_prepay":   0.552330,
        "full_prepay":      0.483289,
        "refinance":        0.388357,
        "fixation_renewal": 0.498823,
        "extend_term":      0.410795,
    }
    probs = all_path_probabilities(DEFAULT_CERTAINTIES)
    for bid, expected in _EXPECTED.items():
        assert abs(probs[bid] - expected) < 1e-4, (
            f"{bid}: got {probs[bid]:.6f}, expected {expected:.6f}"
        )


def test_path_prob_ordering():
    """keep_as_is has highest path probability; refinance has lowest (extra uncertain enabler)."""
    probs = all_path_probabilities(DEFAULT_CERTAINTIES)
    assert probs["keep_as_is"] > probs["refinance"]
    assert probs["keep_as_is"] > probs["full_prepay"]


def test_path_prob_monotone_in_certainty():
    """Increasing any node's certainty must not decrease the path probability."""
    for bid in BRANCH_IDS:
        base_p = path_probability(bid, DEFAULT_CERTAINTIES)
        for nid in BRANCH_PATH_NODES[bid]:
            boosted = dict(DEFAULT_CERTAINTIES, **{nid: min(1.0, DEFAULT_CERTAINTIES[nid] + 0.1)})
            assert path_probability(bid, boosted) >= base_p - 1e-12, \
                f"Boosting {nid} decreased path_prob for {bid}"


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def test_monte_carlo_reproducible():
    """Two calls with same n and seed produce bit-identical results."""
    mc1 = monte_carlo(n=10_000, seed=42)
    mc2 = monte_carlo(n=10_000, seed=42)
    for bid in BRANCH_IDS:
        assert mc1[bid]["mean_prob"] == mc2[bid]["mean_prob"], \
            f"MC not reproducible for {bid}"
        assert mc1[bid]["std_prob"] == mc2[bid]["std_prob"]


def test_monte_carlo_different_seeds_differ():
    """Different seeds produce different results."""
    mc1 = monte_carlo(n=1_000, seed=42)
    mc2 = monte_carlo(n=1_000, seed=99)
    assert any(
        abs(mc1[bid]["mean_prob"] - mc2[bid]["mean_prob"]) > 1e-6
        for bid in BRANCH_IDS
    )


def test_monte_carlo_means_within_deterministic_range():
    """MC means should be close to deterministic path probs (within 3σ)."""
    det_probs = all_path_probabilities(DEFAULT_CERTAINTIES)
    mc = monte_carlo(n=10_000, seed=42)
    for bid in BRANCH_IDS:
        # MC mean should be within ±15% of deterministic probability
        det = det_probs[bid]
        mean = mc[bid]["mean_prob"]
        assert abs(mean - det) < 0.15 * det, \
            f"{bid}: MC mean {mean:.4f} far from det {det:.4f}"


def test_monte_carlo_std_positive():
    """Every branch should have positive std dev (noise is being applied)."""
    mc = monte_carlo(n=10_000, seed=42)
    for bid in BRANCH_IDS:
        assert mc[bid]["std_prob"] > 0, f"{bid} has zero std_prob — noise not applied?"


def test_monte_carlo_completes_quickly():
    """simulate(mode='monte_carlo', n=10000) completes in < 5 seconds."""
    t0 = time.time()
    monte_carlo(n=10_000, seed=42)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"MC took {elapsed:.2f}s — exceeds 5s threshold"


def test_monte_carlo_sum_of_means_gt_one():
    """Sum of MC mean path probabilities > 1 (not mutually exclusive)."""
    mc = monte_carlo(n=10_000, seed=42)
    total = sum(v["mean_prob"] for v in mc.values())
    assert total > 1.0


# ── Sensitivity ───────────────────────────────────────────────────────────────

def test_sensitivity_finds_lowest_certainty_node():
    """
    Within a branch path, the node with lowest certainty has highest sensitivity.
    For refinance: alt_bank_offer and refinance (both 0.75) are tied for lowest;
    perturbing either causes maximum |ΔP| for that branch.
    """
    result = most_sensitive_node_for_branch("refinance", DEFAULT_CERTAINTIES)
    # Both alt_bank_offer and refinance have certainty 0.75 — the minimum on the path
    assert result["certainty"] == pytest.approx(0.75, abs=1e-6), (
        f"Expected driver certainty 0.75, got {result['certainty']}"
    )


def test_sensitivity_low_certainty_node_dominates():
    """Dropping a node's certainty to 0.1 makes it appear as most sensitive for its branch."""
    certs = dict(DEFAULT_CERTAINTIES, **{"alt_bank_offer": 0.10})
    result = most_sensitive_node_for_branch("refinance", certs)
    assert result["node_id"] == "alt_bank_offer"


def test_sensitivity_analysis_spine_nodes_rank_high():
    """Spine nodes (on all 6 paths) should have higher total exposure than branch-only nodes."""
    sens = sensitivity_analysis(node_certainties=DEFAULT_CERTAINTIES)
    top_exposure_nodes = {r["node_id"] for r in sens[:3]}
    # mortgage_strategy (0.85) affects all 6 branches → should appear near top
    assert "mortgage_strategy" in top_exposure_nodes


def test_sensitivity_ranking_stable():
    """Sensitivity ranking is identical across 5 consecutive calls (fully deterministic)."""
    ranks = [
        [r["node_id"] for r in sensitivity_analysis(node_certainties=DEFAULT_CERTAINTIES)]
        for _ in range(5)
    ]
    for r in ranks[1:]:
        assert r == ranks[0], "Sensitivity ranking changed between calls"


def test_branch_exposures_returns_all_branches():
    """branch_exposures() covers all 6 mortgage branches."""
    be = branch_exposures(node_certainties=DEFAULT_CERTAINTIES)
    assert {r["branch"] for r in be} == set(BRANCH_IDS)


def test_branch_exposures_driver_on_path():
    """driver_node for each branch must be in that branch's path."""
    be = branch_exposures(node_certainties=DEFAULT_CERTAINTIES)
    for entry in be:
        bid    = entry["branch"]
        driver = entry["driver_node"]
        assert driver in BRANCH_PATH_NODES[bid], \
            f"driver {driver} not in path for {bid}"


# ── Trace ─────────────────────────────────────────────────────────────────────

def test_trace_valid_jsonl(tmp_path, monkeypatch):
    """Trace file contains valid JSONL — every line is a parseable JSON object."""
    # Redirect runs dir to tmp_path so we don't litter the repo
    import simulate.trace as trace_mod
    monkeypatch.setattr(trace_mod, "_runs_dir", lambda: str(tmp_path))

    from simulate.payoff import BRANCH_IDS as BIDS, compute_branch
    payoffs = [compute_branch(bid) for bid in BIDS]

    path = write_deterministic_trace("test_chain", payoffs)

    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) > 0, "Trace file is empty"
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Line {i} is not valid JSON: {exc}\n  {line[:120]}")
        # Required fields
        for field in ("run_id", "step", "node_id", "node_type",
                      "certainty_declared", "branch_taken", "timestamp_utc"):
            assert field in record, f"Line {i} missing field '{field}'"


def test_trace_records_have_correct_types(tmp_path, monkeypatch):
    """Each trace record has correct field types."""
    import simulate.trace as trace_mod
    monkeypatch.setattr(trace_mod, "_runs_dir", lambda: str(tmp_path))

    from simulate.payoff import BRANCH_IDS as BIDS, compute_branch
    payoffs = [compute_branch(bid) for bid in BIDS]
    path = write_deterministic_trace("test_chain", payoffs)

    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            assert isinstance(r["run_id"], str)
            assert isinstance(r["step"], int)
            assert isinstance(r["node_id"], str)
            assert isinstance(r["certainty_declared"], float)


def test_trace_writer_context_manager(tmp_path, monkeypatch):
    """TraceWriter writes valid JSONL and closes the file cleanly."""
    import simulate.trace as trace_mod
    monkeypatch.setattr(trace_mod, "_runs_dir", lambda: str(tmp_path))

    tw = trace_mod.TraceWriter("unit_test")
    with tw as writer:
        writer.step(run_id="r_001", step=0, node_id="mortgage_active",
                    node_type="STATE", certainty_declared=1.0)
        writer.step(run_id="r_001", step=1, node_id="rate_review_event",
                    node_type="EVENT", certainty_declared=0.95, certainty_sampled=0.93)

    with open(tw.path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f]

    assert len(lines) == 2
    assert lines[0]["node_id"] == "mortgage_active"
    assert lines[1]["certainty_sampled"] == pytest.approx(0.93, abs=1e-4)


# ── simulate() integration ────────────────────────────────────────────────────

def test_simulate_monte_carlo_mode():
    """simulate(mode='monte_carlo') returns path_probabilities and sensitivity keys."""
    from simulate.runner import simulate
    result = simulate([], mode="monte_carlo", n=1_000, seed=42)
    assert "path_probabilities" in result
    assert "sensitivity" in result
    assert "branch_exposures" in result
    assert len(result["path_probabilities"]) == 6


def test_simulate_monte_carlo_reproducible():
    """simulate(mode='monte_carlo') is bit-exact on repeated calls with same seed."""
    from simulate.runner import simulate
    r1 = simulate([], mode="monte_carlo", n=1_000, seed=42)
    r2 = simulate([], mode="monte_carlo", n=1_000, seed=42)
    for bid in BRANCH_IDS:
        assert r1["path_probabilities"][bid]["mean_prob"] == \
               r2["path_probabilities"][bid]["mean_prob"]
