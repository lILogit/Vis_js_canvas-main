"""
T6 re-forge tests: post-enrichment chain forges correctly with provenance + diff.

All tests are unit tests — no LLM calls required.
The enriched chain is produced deterministically using the canned E1 fixture.
"""
import copy
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enrichment.classify import classify_event
from enrichment.gate import run_gates, get_source_credibility
from enrichment.apply import apply_event
from forge.emit import forge_chain
from forge.diff import diff_chains, diff_forge_output, format_diff
from simulate.payoff import compute_branch, REFERENCE_SCENARIO
from simulate.recommend import recommend

_CHAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "chains", "mortgage-mvp-seed.causal.json"
)

_E1_KOMERCKA = {
    "class":               "E1",
    "target_node_id":      "AltBankOffer.rate",
    "direction":           "down",
    "magnitude":           0.025,
    "new_value_hint":      0.0395,
    "extraction_confidence": 0.92,
    "text_span":           "Komerční banka snížila hypoteční sazbu na 3.95 %",
    "reasoning":           "Specific numeric claim from named institution; conditional on LTV<80%",
}


def _load_chain() -> dict:
    with open(_CHAIN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _make_enriched_chain() -> tuple[dict, dict]:
    """Return (before_chain, after_chain) by applying the canned E1 event."""
    before = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    gr = run_gates(classified, before, source="hn.cz")
    assert gr.passed, f"Gate failed in fixture setup: {gr.reason}"
    sc = get_source_credibility("hn.cz")
    after = apply_event(before, classified, gr, source="hn.cz", source_credibility=sc)
    return before, after


# ── Forge determinism ─────────────────────────────────────────────────────────

def test_byte_identical_after_enrichment():
    """Forging the post-enrichment chain twice gives identical output (excluding timestamp/hash)."""
    _, enriched = _make_enriched_chain()
    src_a = forge_chain(enriched)
    src_b = forge_chain(enriched)

    # Strip volatile lines before comparing
    _volatile = re.compile(r'"(?:source_hash|timestamp)"')
    lines_a = [l for l in src_a.splitlines() if not _volatile.search(l)]
    lines_b = [l for l in src_b.splitlines() if not _volatile.search(l)]
    assert lines_a == lines_b


def test_forge_emits_last_enrichment_key():
    """_forge_meta contains last_enrichment key after enrichment."""
    _, enriched = _make_enriched_chain()
    src = forge_chain(enriched)
    assert '"last_enrichment"' in src


def test_forge_emits_evidence_refs_on_enriched_node():
    """The AltBankOffer decorator includes _evidence_refs after an E1 is applied."""
    _, enriched = _make_enriched_chain()
    src = forge_chain(enriched)
    assert "_evidence_refs" in src


def test_forge_emits_rate_field_for_alt_bank_offer():
    """AltBankOffer gets a `rate` field with the enriched value (0.0395)."""
    _, enriched = _make_enriched_chain()
    src = forge_chain(enriched)
    # Should contain the override value
    assert "rate: float = 0.0395" in src


def test_forge_pre_enrichment_has_no_rate_field():
    """Before enrichment, AltBankOffer has no rate field (no scenario override)."""
    before = _load_chain()
    src = forge_chain(before)
    assert "rate: float = " not in src
    assert '"last_enrichment"' not in src


# ── Diff utilities ────────────────────────────────────────────────────────────

def test_diff_chains_detects_scenario_change():
    before, after = _make_enriched_chain()
    diff = diff_chains(before, after)
    assert "alt_rate" in diff["scenario_changes"]
    ch = diff["scenario_changes"]["alt_rate"]
    assert ch["before"] is None  # was not overridden before
    assert abs(ch["after"] - 0.0395) < 1e-9


def test_diff_chains_detects_new_evidence():
    before, after = _make_enriched_chain()
    diff = diff_chains(before, after)
    assert len(diff["new_evidence"]) == 1
    ev = diff["new_evidence"][0]
    assert ev["class"] == "E1"
    assert ev["target_node_id"] == "AltBankOffer.rate"


def test_diff_chains_detects_node_status_change():
    before, after = _make_enriched_chain()
    diff = diff_chains(before, after)
    status_changes = [c for c in diff["changed_nodes"] if c["field"] == "_status"]
    assert any(c["id"] == "alt_bank_offer" and c["after"] == "enriched"
               for c in status_changes)


def test_diff_forge_output_shows_only_meaningful_changes():
    """diff_forge_output filters timestamp/hash; real changes remain."""
    before, after = _make_enriched_chain()
    src_before = forge_chain(before)
    src_after  = forge_chain(after)
    diff_lines = diff_forge_output(src_before, src_after)
    unified = "".join(diff_lines)
    # Volatile lines should not appear as changes
    assert '"source_hash"' not in unified
    assert '"timestamp"'   not in unified
    # But meaningful additions should be present
    assert "last_enrichment" in unified or "_evidence_refs" in unified


def test_format_diff_is_human_readable():
    before, after = _make_enriched_chain()
    diff = diff_chains(before, after)
    text = format_diff(diff)
    assert "alt_rate" in text
    assert "→" in text


# ── Post-enrichment recommendation ────────────────────────────────────────────

def test_recommendation_changes_after_e1():
    """After E1 sets alt_rate=0.0395, refinance score increases vs reference."""
    _, enriched = _make_enriched_chain()
    ovr = enriched["meta"].get("scenario_overrides", {})
    assert "alt_rate" in ovr

    ref_scenario = dict(REFERENCE_SCENARIO)
    enr_scenario = dict(REFERENCE_SCENARIO, **ovr)

    branch_ids = ["keep_as_is", "partial_prepay", "full_prepay", "refinance",
                  "fixation_renewal", "extend_term"]
    ref_results = [compute_branch(bid, ref_scenario) for bid in branch_ids]
    enr_results = [compute_branch(bid, enr_scenario) for bid in branch_ids]

    ref_refinance = next(r for r in ref_results if r["branch"] == "refinance")
    enr_refinance = next(r for r in enr_results if r["branch"] == "refinance")

    # Refinance total_interest should be lower after enrichment
    assert enr_refinance["total_interest"] < ref_refinance["total_interest"]

    ref_recs = recommend(ref_results, ref_scenario)
    enr_recs = recommend(enr_results, enr_scenario)

    # Refinance should rank #1 in both (lower rate = better savings)
    assert enr_recs[0]["branch"] == "refinance"

    # Score should be higher after enrichment
    ref_refinance_score = next(r["score"] for r in ref_recs if r["branch"] == "refinance")
    enr_refinance_score = next(r["score"] for r in enr_recs if r["branch"] == "refinance")
    assert enr_refinance_score > ref_refinance_score


def test_simulation_interest_savings_increase_after_e1():
    """Enriched alt_rate (3.95%) → more interest saved vs reference (4.20%)."""
    _, enriched = _make_enriched_chain()
    ovr = enriched["meta"].get("scenario_overrides", {})
    ref_branch = compute_branch("refinance", REFERENCE_SCENARIO)
    enr_branch = compute_branch("refinance", dict(REFERENCE_SCENARIO, **ovr))
    assert enr_branch["interest_saved"] > ref_branch["interest_saved"]
    # Improvement should be at least 20 000 CZK
    improvement = enr_branch["interest_saved"] - ref_branch["interest_saved"]
    assert improvement > 20_000


# ── Provenance completeness ───────────────────────────────────────────────────

def test_provenance_chain_complete():
    """Every node with _status='enriched' has _evidence_ref pointing to a valid evidence id."""
    _, enriched = _make_enriched_chain()
    valid_ids = {ev["id"] for ev in enriched.get("evidence", [])}
    for node in enriched.get("nodes", []):
        if node.get("_status") == "enriched":
            ref = node.get("_evidence_ref")
            assert ref is not None, f"Node {node['id']} is enriched but missing _evidence_ref"
            assert ref in valid_ids, (
                f"Node {node['id']} references unknown evidence id '{ref}'"
            )


def test_evidence_ledger_has_full_provenance():
    """Evidence entry contains all required provenance fields."""
    _, enriched = _make_enriched_chain()
    assert len(enriched["evidence"]) == 1
    ev = enriched["evidence"][0]
    for field in ("id", "timestamp", "source", "source_credibility",
                  "extraction_confidence", "class", "target_node_id",
                  "old_value", "new_value", "applied"):
        assert field in ev, f"Evidence entry missing field '{field}'"
    assert ev["applied"] is True
    assert ev["source"] == "hn.cz"


def test_evidence_old_and_new_values_differ():
    """Evidence ledger records both old and new values, and they are different."""
    _, enriched = _make_enriched_chain()
    ev = enriched["evidence"][0]
    assert ev["old_value"] != ev["new_value"]
    assert abs(ev["new_value"] - 0.0395) < 1e-9
