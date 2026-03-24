"""
note/evolution.py — Graph evolution from ΔDATA.

Converts classification output into new nodes/edges (as suggestions array
compatible with the existing enrich-preview / applyPreviewSuggestions flow).
"""
import json

from chain.schema import CausalChain
from chain.io import to_dict
from note.schema import NoteInput
from llm import client
from llm.prompts import NOTE_TO_GRAPH


def evolve_graph(chain: CausalChain, classification: dict, note: NoteInput) -> list:
    """
    Call Claude to generate nodes/edges for ΔDATA entities.
    Returns a suggestions list in import_node / import_edge format.
    """
    delta = classification.get("delta", [])
    if not delta:
        return []

    # Build context: known nodes only (seed nodes + all active nodes for reference)
    chain_data = to_dict(chain)
    active_nodes = [n for n in chain_data["nodes"] if not n.get("deprecated")]
    active_edges = [e for e in chain_data["edges"] if not e.get("deprecated")]

    # Provide known node map so LLM can reference IDs
    known_map = {n["id"]: n["label"] for n in active_nodes}
    context = {
        "nodes": active_nodes,
        "edges": active_edges,
        "known": classification.get("known", []),
    }

    prompt = NOTE_TO_GRAPH.format(
        context_json=json.dumps(context, indent=2),
        delta_json=json.dumps(delta, indent=2),
        structural_role=classification.get("structural_role", "mechanism"),
        w_score=round(classification.get("w_score", 0.5), 3),
    )

    result = client.call(prompt, max_tokens=1500)

    raw_nodes = result.get("nodes", [])
    raw_edges = result.get("edges", [])

    # Build delta-label set for validation
    delta_labels = {d.get("entity", "") for d in delta}

    suggestions = []

    # Nodes first (import_node kind)
    for n in raw_nodes:
        suggestions.append({
            "kind": "import_node",
            "label": n.get("label", ""),
            "node_type": n.get("type", "state"),
            "description": n.get("description", ""),
            "archetype": n.get("archetype", classification.get("structural_role", "mechanism")),
            "reasoning": "",
        })

    # Edges (import_edge kind) — resolve from_ref / to_ref
    for e in raw_edges:
        from_ref = e.get("from_ref", "")
        to_ref = e.get("to_ref", "")

        # Determine if ref is existing node_id or ΔDATA label
        from_label = known_map.get(from_ref, from_ref)  # if it's an id, get label; else use as label
        to_label = known_map.get(to_ref, to_ref)

        suggestions.append({
            "kind": "import_edge",
            "label": f"{from_label} → {to_label}",
            "connects_from_label": from_label,
            "connects_to_label": to_label,
            "relation": e.get("relation", "CAUSES"),
            "weight": e.get("weight", classification.get("w_score", 0.5)),
            "reasoning": e.get("evidence", ""),
            # Store original refs for the apply step to also handle known node IDs
            "_from_ref": from_ref,
            "_to_ref": to_ref,
            "_known_map": known_map,
        })

    return suggestions
