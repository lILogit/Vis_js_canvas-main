"""
forge/diff.py — semantic and textual diff between chain versions.
"""
from __future__ import annotations

import difflib
import re

# Lines whose content changes every forge run regardless of chain mutations
_VOLATILE_PATTERNS = (
    re.compile(r'^\s*"source_hash"'),
    re.compile(r'^\s*"timestamp"'),
)


def diff_chains(before: dict, after: dict) -> dict:
    """
    Return a semantic summary of what changed between two chain dicts.

    Returns:
        {
            "changed_nodes": [{"id", "field", "before", "after"}],
            "new_evidence":  [evidence_entry, ...],
            "scenario_changes": {"key": {"before": v, "after": v}},
        }
    """
    before_nodes = {n["id"]: n for n in before.get("nodes", [])}
    after_nodes  = {n["id"]: n for n in after.get("nodes",  [])}

    changed_nodes = []
    for nid, an in after_nodes.items():
        bn = before_nodes.get(nid, {})
        for field in ("confidence", "_status", "_evidence_ref"):
            bv = bn.get(field)
            av = an.get(field)
            if bv != av:
                changed_nodes.append({"id": nid, "field": field, "before": bv, "after": av})

    before_ev_ids = {e["id"] for e in before.get("evidence", [])}
    new_evidence  = [e for e in after.get("evidence", []) if e["id"] not in before_ev_ids]

    before_ovr = before.get("meta", {}).get("scenario_overrides", {})
    after_ovr  = after.get("meta",  {}).get("scenario_overrides", {})
    scenario_changes = {}
    all_keys = set(before_ovr) | set(after_ovr)
    for k in all_keys:
        bv = before_ovr.get(k)
        av = after_ovr.get(k)
        if bv != av:
            scenario_changes[k] = {"before": bv, "after": av}

    return {
        "changed_nodes":    changed_nodes,
        "new_evidence":     new_evidence,
        "scenario_changes": scenario_changes,
    }


def diff_forge_output(before_src: str, after_src: str) -> list[str]:
    """
    Unified diff of two forge outputs.

    Volatile lines (source_hash, timestamp) are stripped before comparison
    so only meaningful mutations appear in the diff.
    """
    def _strip_volatile(src: str) -> list[str]:
        return [
            ln for ln in src.splitlines(keepends=True)
            if not any(p.search(ln) for p in _VOLATILE_PATTERNS)
        ]

    a = _strip_volatile(before_src)
    b = _strip_volatile(after_src)
    return list(difflib.unified_diff(a, b, fromfile="before", tofile="after"))


def format_diff(diff: dict) -> str:
    """Human-readable text summary of a semantic chain diff."""
    lines: list[str] = []

    if diff["scenario_changes"]:
        lines.append("Scenario overrides:")
        for k, ch in diff["scenario_changes"].items():
            bv = f"{ch['before']:.4f}" if isinstance(ch["before"], float) else str(ch["before"])
            av = f"{ch['after']:.4f}"  if isinstance(ch["after"],  float) else str(ch["after"])
            lines.append(f"  {k}: {bv} → {av}")

    if diff["new_evidence"]:
        lines.append("New evidence:")
        for ev in diff["new_evidence"]:
            lines.append(
                f"  [{ev['id']}] {ev['class']} {ev['target_node_id']} "
                f"via {ev['source']} (conf {ev['extraction_confidence']:.2f})"
            )

    if diff["changed_nodes"]:
        lines.append("Changed nodes:")
        for ch in diff["changed_nodes"]:
            lines.append(f"  {ch['id']}.{ch['field']}: {ch['before']!r} → {ch['after']!r}")

    if not lines:
        lines.append("No changes.")

    return "\n".join(lines)
