"""
Schema-bound LLM extraction: text → list of E1-E6 evidence events.
Uses the TEXT_EXTRACT prompt from llm/prompts.py.
"""
from __future__ import annotations

import sys
import os

# Ensure project root is on path so llm/ and simulate/ are importable
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from llm.prompts import TEXT_EXTRACT
from simulate.payoff import REFERENCE_SCENARIO

from .classify import VALID_TARGET_IDS, classify_event


def extract_events(
    article_text: str,
    chain: dict | None = None,
    scenario_overrides: dict | None = None,
) -> list[dict]:
    """
    Call the LLM to extract evidence events from article_text.

    Returns a list of classified event dicts (may be empty).
    Only events with valid target_node_id and E-class are returned.
    Malformed events are silently dropped (schema validation gate 1).
    """
    from llm.client import call  # noqa: PLC0415

    # Resolve current scenario values for the prompt context
    overrides = scenario_overrides or (
        (chain or {}).get("meta", {}).get("scenario_overrides", {})
    )
    scenario = dict(REFERENCE_SCENARIO, **overrides)

    prompt = TEXT_EXTRACT.format(
        alt_rate=scenario.get("alt_rate", REFERENCE_SCENARIO["alt_rate"]),
        renewal_rate=scenario.get("renewal_rate", REFERENCE_SCENARIO["renewal_rate"]),
        annual_rate=scenario.get("annual_rate", REFERENCE_SCENARIO["annual_rate"]),
        article_text=article_text.strip(),
    )

    system = (
        "You are a financial evidence extractor for a causal risk model. "
        "Return only valid JSON. No preamble. No markdown."
    )

    raw = call(prompt, system=system, max_tokens=800)
    raw_events = raw.get("events", []) if isinstance(raw, dict) else []

    # Gate 1: schema validation — drop any event that fails classify
    classified = []
    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        try:
            classified.append(classify_event(ev))
        except Exception:
            pass  # malformed event dropped

    return classified
