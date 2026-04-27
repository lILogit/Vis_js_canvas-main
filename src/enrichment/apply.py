"""
Apply an E1 event to the chain: write evidence ledger + scenario overrides.
E2-E6 events are routed to chain.pending_review (not auto-applied).
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

from .gate import GateResult, _TARGET_MAP


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_evidence_id(source: str, chain: dict) -> str:
    date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "_", source.lower()).strip("_")
    existing = len(chain.get("evidence", []))
    return f"ev_{date}_{slug}_{existing + 1:02d}"


def apply_event(
    chain: dict,
    event: dict,
    gate_result: GateResult,
    source: str,
    source_credibility: float,
) -> dict:
    """
    Mutate the chain with a validated E1 event.

    Returns a deep-copied, updated chain dict. Never mutates the input.
    E2-E6 events are added to chain.pending_review instead.
    """
    chain_out = copy.deepcopy(chain)
    ev_id     = _make_evidence_id(source, chain_out)

    info      = _TARGET_MAP.get(event.get("target_node_id", ""))
    scenario_key = info[0] if info else None
    node_id      = info[1] if info else None
    old_value    = gate_result.new_value  # gate computed this
    new_value    = gate_result.new_value

    # ── For non-E1: route to pending_review ──────────────────────────────────
    if not event.get("auto_apply"):
        pending = chain_out.setdefault("pending_review", [])
        pending.append({
            "id":       ev_id,
            "class":    event["class"],
            "event":    event,
            "source":   source,
            "added_at": _utcnow(),
        })
        return chain_out

    # ── E1: build evidence record ─────────────────────────────────────────────
    # Re-derive old value from current scenario
    from simulate.payoff import REFERENCE_SCENARIO  # noqa: PLC0415
    overrides = chain_out.get("meta", {}).get("scenario_overrides", {})
    old_value_actual = overrides.get(scenario_key, REFERENCE_SCENARIO.get(scenario_key))

    evidence_entry = {
        "id":                   ev_id,
        "timestamp":            _utcnow(),
        "source":               source,
        "source_credibility":   source_credibility,
        "extraction_confidence": event["extraction_confidence"],
        "text_span":            event.get("text_span", ""),
        "reasoning":            event.get("reasoning", ""),
        "class":                event["class"],
        "target_node_id":       event["target_node_id"],
        "old_value":            old_value_actual,
        "new_value":            new_value,
        "shift_proposed":       gate_result.shift_proposed,
        "shift_applied":        gate_result.shift_applied,
        "shift_capped_by_bounds": gate_result.shift_capped,
        "applied":              True,
    }

    chain_out.setdefault("evidence", []).append(evidence_entry)

    # ── Update scenario_overrides in meta ─────────────────────────────────────
    if scenario_key is not None and new_value is not None:
        meta = chain_out.setdefault("meta", {})
        meta.setdefault("scenario_overrides", {})[scenario_key] = new_value

    # ── Mark the affected node ────────────────────────────────────────────────
    if node_id:
        updated_nodes = []
        for n in chain_out.get("nodes", []):
            if n.get("id") == node_id:
                n = dict(n, _status="enriched", _evidence_ref=ev_id)
            updated_nodes.append(n)
        chain_out["nodes"] = updated_nodes

    return chain_out


def apply_pending_or_reject(
    chain: dict,
    event: dict,
    gate_result: GateResult,
    source: str,
    source_credibility: float,
) -> dict:
    """
    Convenience wrapper: apply if E1 + gates passed; route to pending otherwise.
    Returns the (possibly mutated) chain copy.
    """
    if gate_result.passed and event.get("auto_apply"):
        return apply_event(chain, event, gate_result, source, source_credibility)
    # Gate failed or non-E1
    chain_out = copy.deepcopy(chain)
    chain_out.setdefault("pending_review", []).append({
        "id":       _make_evidence_id(source, chain),
        "class":    event.get("class"),
        "event":    event,
        "source":   source,
        "gate_result": {
            "passed": gate_result.passed,
            "reason": gate_result.reason,
            "gate":   gate_result.gate,
        },
        "added_at": _utcnow(),
    })
    return chain_out
