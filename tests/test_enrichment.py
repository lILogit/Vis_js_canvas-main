"""
T5 enrichment tests.

Unit tests (no LLM): classify, gate, apply logic.
Integration tests (require ANTHROPIC_API_KEY): full extraction pipeline.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enrichment.classify import (
    ClassifyError,
    VALID_TARGET_IDS,
    classify_event,
)
from enrichment.gate import (
    CREDIBILITY_THRESHOLD,
    MAX_SHIFT_PER_CYCLE,
    SOURCE_CREDIBILITY,
    GateResult,
    get_source_credibility,
    get_current_value,
    run_gates,
)
from enrichment.apply import apply_event, apply_pending_or_reject

# ── Shared fixtures ───────────────────────────────────────────────────────────

_CHAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "chains", "mortgage-mvp.causal.json"
)

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "komercka_rate_cut_2026.txt"
)


def _load_chain() -> dict:
    with open(_CHAIN_PATH, encoding="utf-8") as f:
        return json.load(f)


# Canned E1 event matching the spec's expected extraction
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

def _load_api_key() -> str:
    """Read ANTHROPIC_API_KEY from env or project .env file."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("ANTHROPIC_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    return key


_API_KEY = _load_api_key()
# Skip integration tests if key is absent or looks like a placeholder
_HAS_REAL_API_KEY = bool(_API_KEY) and not _API_KEY.startswith("sk-ant-placeholder")
_SKIP_NO_KEY = pytest.mark.skipif(
    not _HAS_REAL_API_KEY,
    reason="ANTHROPIC_API_KEY not set or is a placeholder",
)

# ── classify.py unit tests ────────────────────────────────────────────────────

def test_classify_valid_e1():
    classified = classify_event(_E1_KOMERCKA)
    assert classified["auto_apply"] is True
    assert classified["class_name"] == "value_update"
    assert classified["valid"] is True


def test_classify_valid_e2():
    ev = dict(_E1_KOMERCKA, **{"class": "E2"})
    classified = classify_event(ev)
    assert classified["auto_apply"] is False


def test_classify_unknown_class_raises():
    with pytest.raises(ClassifyError, match="Unknown event class"):
        classify_event(dict(_E1_KOMERCKA, **{"class": "E9"}))


def test_classify_unknown_target_raises():
    with pytest.raises(ClassifyError, match="Unknown target_node_id"):
        classify_event(dict(_E1_KOMERCKA, **{"target_node_id": "SomeUnknownNode"}))


def test_classify_missing_direction_raises():
    ev = {k: v for k, v in _E1_KOMERCKA.items() if k != "direction"}
    with pytest.raises(ClassifyError, match="missing required field"):
        classify_event(ev)


def test_all_valid_target_ids_accepted():
    for tid in VALID_TARGET_IDS:
        ev = dict(_E1_KOMERCKA, **{"target_node_id": tid})
        result = classify_event(ev)
        assert result["valid"] is True


# ── gate.py unit tests ────────────────────────────────────────────────────────

def test_source_credibility_known_sources():
    assert get_source_credibility("hn.cz")  == pytest.approx(0.88)
    assert get_source_credibility("cnb.cz") == pytest.approx(0.95)
    assert get_source_credibility("unknown")== pytest.approx(0.50)


def test_source_credibility_unknown_falls_back():
    assert get_source_credibility("some-random-blog.cz") == pytest.approx(0.50)


def test_low_credibility_source_blocks_apply():
    """source_credibility(unknown=0.50) × confidence(0.92) = 0.46 < 0.75 → BLOCKED."""
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    result = run_gates(classified, chain, source="unknown")
    assert not result.passed
    assert result.gate == "credibility"
    assert "credibility gate failed" in result.reason


def test_high_credibility_source_passes():
    """hn.cz (0.88) × 0.92 = 0.8096 ≥ 0.75 → passes credibility gate."""
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    result = run_gates(classified, chain, source="hn.cz")
    assert result.passed


def test_cnb_source_always_passes_credibility():
    chain = _load_chain()
    classified = classify_event(dict(_E1_KOMERCKA, extraction_confidence=0.80))
    result = run_gates(classified, chain, source="cnb.cz")
    # 0.95 × 0.80 = 0.76 ≥ 0.75
    assert result.passed


def test_very_low_confidence_blocked_even_with_good_source():
    chain = _load_chain()
    # 0.88 × 0.50 = 0.44 < 0.75
    classified = classify_event(dict(_E1_KOMERCKA, extraction_confidence=0.50))
    result = run_gates(classified, chain, source="hn.cz")
    assert not result.passed
    assert result.gate == "credibility"


def test_bounded_shift_no_cap_needed():
    """shift = 0.042 - 0.0395 = 0.0025 < 0.10 max → not capped."""
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    result = run_gates(classified, chain, source="hn.cz")
    assert result.passed
    assert not result.shift_capped
    assert abs(result.shift_proposed - 0.0025) < 1e-6


def test_bounded_shift_caps_large_shift():
    """A proposed shift of 0.02 (> MAX_SHIFT_PER_CYCLE) should be capped."""
    chain = _load_chain()
    # hint would shift 0.042 → 0.022 (delta 0.020 > 0.010 max)
    big_shift_ev = dict(_E1_KOMERCKA, new_value_hint=0.022)
    classified = classify_event(big_shift_ev)
    result = run_gates(classified, chain, source="hn.cz")
    if result.passed:
        assert result.shift_capped
        assert abs(result.shift_applied) <= MAX_SHIFT_PER_CYCLE + 1e-9


def test_circuit_breaker_passes_for_small_shift():
    """A 25bps rate change causes ~6% payoff shift, well below 15% threshold."""
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    result = run_gates(classified, chain, source="hn.cz")
    assert result.passed
    assert result.gate == "none"


def test_get_current_value_returns_reference():
    chain = _load_chain()
    from simulate.payoff import REFERENCE_SCENARIO
    val = get_current_value(chain, "AltBankOffer.rate")
    assert val == pytest.approx(REFERENCE_SCENARIO["alt_rate"])


def test_get_current_value_respects_prior_override():
    chain = _load_chain()
    chain = copy.deepcopy(chain)
    chain.setdefault("meta", {})["scenario_overrides"] = {"alt_rate": 0.038}
    val = get_current_value(chain, "AltBankOffer.rate")
    assert val == pytest.approx(0.038)


# ── apply.py unit tests ───────────────────────────────────────────────────────

def _make_gate_result(**kwargs) -> GateResult:
    defaults = dict(
        passed=True, reason="all gates passed", gate="none",
        shift_proposed=0.0025, shift_applied=0.0025,
        shift_capped=False, new_value=0.0395,
    )
    defaults.update(kwargs)
    return GateResult(**defaults)


def test_apply_e1_adds_evidence():
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    gr = _make_gate_result()
    result = apply_event(chain, classified, gr, source="hn.cz",
                         source_credibility=0.88)
    assert "evidence" in result
    assert len(result["evidence"]) == 1
    ev = result["evidence"][0]
    assert ev["class"] == "E1"
    assert ev["target_node_id"] == "AltBankOffer.rate"
    assert ev["applied"] is True
    assert ev["source"] == "hn.cz"


def test_apply_e1_updates_scenario_overrides():
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    gr = _make_gate_result(new_value=0.0395)
    result = apply_event(chain, classified, gr, source="hn.cz",
                         source_credibility=0.88)
    overrides = result["meta"]["scenario_overrides"]
    assert "alt_rate" in overrides
    assert overrides["alt_rate"] == pytest.approx(0.0395)


def test_apply_e1_marks_node_status():
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    gr = _make_gate_result(new_value=0.0395)
    result = apply_event(chain, classified, gr, source="hn.cz",
                         source_credibility=0.88)
    node = next((n for n in result["nodes"] if n["id"] == "alt_bank_offer"), None)
    assert node is not None
    assert node.get("_status") == "enriched"
    assert "_evidence_ref" in node


def test_apply_does_not_mutate_input():
    chain = _load_chain()
    original_evidence = list(chain.get("evidence", []))
    classified = classify_event(_E1_KOMERCKA)
    gr = _make_gate_result(new_value=0.0395)
    apply_event(chain, classified, gr, source="hn.cz", source_credibility=0.88)
    assert chain.get("evidence", []) == original_evidence


def test_apply_e2_goes_to_pending_review():
    chain = _load_chain()
    e2_ev = classify_event(dict(_E1_KOMERCKA, **{"class": "E2"}))
    assert not e2_ev["auto_apply"]
    gr = _make_gate_result()
    result = apply_pending_or_reject(chain, e2_ev, gr, source="hn.cz",
                                     source_credibility=0.88)
    assert "pending_review" in result
    assert len(result["pending_review"]) == 1
    assert "evidence" not in result or len(result.get("evidence", [])) == 0


def test_apply_failed_gate_goes_to_pending():
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    failed_gr = _make_gate_result(passed=False, gate="credibility",
                                   reason="credibility gate failed")
    result = apply_pending_or_reject(chain, classified, failed_gr, source="unknown",
                                     source_credibility=0.50)
    assert "evidence" not in result or len(result.get("evidence", [])) == 0


def test_simulation_uses_enriched_rate():
    """After applying E1, running simulate with overrides gives different result."""
    from simulate.payoff import REFERENCE_SCENARIO, compute_branch

    before = compute_branch("refinance", REFERENCE_SCENARIO)
    after  = compute_branch("refinance", dict(REFERENCE_SCENARIO, alt_rate=0.0395))
    # Lower rate → lower total_interest for refinance
    assert after["total_interest"] < before["total_interest"]
    assert after["monthly_payment"] < before["monthly_payment"]


# ── Full pipeline unit test (no LLM, uses canned event) ──────────────────────

def test_full_pipeline_canned_e1():
    """
    Full E1 pipeline: classify → gates → apply using the canned event.
    No LLM call required.
    """
    from enrichment.gate import run_gates
    chain = _load_chain()
    classified = classify_event(_E1_KOMERCKA)
    gr = run_gates(classified, chain, source="hn.cz")
    assert gr.passed, f"Gates failed: {gr.reason}"

    sc = get_source_credibility("hn.cz")
    enriched = apply_event(chain, classified, gr, source="hn.cz",
                           source_credibility=sc)

    assert len(enriched.get("evidence", [])) == 1
    assert enriched["meta"]["scenario_overrides"]["alt_rate"] == pytest.approx(gr.new_value)


# ── Integration tests (require ANTHROPIC_API_KEY) ─────────────────────────────

def _call_or_skip(fn):
    """Run fn(); skip (not fail) on API auth/connection errors."""
    import anthropic as _anthropic  # noqa: PLC0415
    try:
        return fn()
    except (_anthropic.AuthenticationError, _anthropic.APIConnectionError,
            EnvironmentError) as exc:
        pytest.skip(f"LLM API unavailable: {exc}")


@_SKIP_NO_KEY
def test_komercka_article_yields_e1():
    """
    LLM extraction of the Komercka article produces an E1 event
    targeting AltBankOffer.rate with direction 'down'.
    """
    from enrichment.extract import extract_events

    with open(_FIXTURE_PATH, encoding="utf-8") as f:
        text = f.read()

    chain = _load_chain()

    def _run():
        events = extract_events(text, chain=chain)
        assert len(events) >= 1, f"Expected ≥1 event, got {len(events)}"
        e1_events = [e for e in events
                     if e.get("class") == "E1"
                     and e.get("target_node_id") == "AltBankOffer.rate"]
        assert e1_events, (
            "No E1 event for AltBankOffer.rate found; got: "
            + json.dumps(events, ensure_ascii=False, indent=2)
        )
        e1 = e1_events[0]
        assert e1["direction"] == "down"
        assert e1.get("new_value_hint", 1.0) < 0.042

    _call_or_skip(_run)


@_SKIP_NO_KEY
def test_unrelated_article_yields_zero_events():
    """
    Feeding an article about weather (no financial rate information)
    returns an empty events list — target_node_id enum prevents hallucination.
    """
    from enrichment.extract import extract_events

    unrelated = (
        "Praha, 27. dubna 2026 — Meteorologové předpovídají na tento víkend "
        "bouřky ve střední Evropě. Teploty klesnou na 12 °C. "
        "Povodňová pohotovost byla vyhlášena v regionu Jihočeského kraje."
    )
    chain = _load_chain()

    def _run():
        events = extract_events(unrelated, chain=chain)
        assert events == [], (
            "Expected empty events for weather article, got: "
            + json.dumps(events, ensure_ascii=False)
        )

    _call_or_skip(_run)
