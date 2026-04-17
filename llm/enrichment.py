import json
from datetime import datetime

from chain.schema import CausalChain, Node, Edge
from chain.io import to_dict, save
from llm import client
from llm.prompts import ENRICH_GAPS, ENRICH_WEIGHTS, ENRICH_SCOPE, CAUSAL_RULES


def _chain_json(chain: CausalChain) -> str:
    return json.dumps(to_dict(chain), indent=2)


def enrich_gaps(chain: CausalChain, n: int = 5) -> list:
    """Find missing intermediary nodes. Returns list of gap dicts."""
    prompt = ENRICH_GAPS.format(chain_json=_chain_json(chain), n=n, rules=CAUSAL_RULES)
    result = client.call(prompt)
    return result.get("gaps", [])


def enrich_weights(chain: CausalChain) -> list:
    """Suggest weight adjustments. Returns list of adjustment dicts."""
    prompt = ENRICH_WEIGHTS.format(chain_json=_chain_json(chain))
    result = client.call(prompt)
    return result.get("weight_adjustments", [])


def enrich_scope(chain: CausalChain) -> list:
    """Find edges that need condition nodes. Returns list of condition dicts."""
    prompt = ENRICH_SCOPE.format(chain_json=_chain_json(chain))
    result = client.call(prompt)
    return result.get("conditions", [])


def apply_gaps(chain: CausalChain, gaps: list, selected: list = None) -> int:
    """
    Apply gap suggestions to chain. selected = list of 0-based indices to apply.
    If selected is None, apply all. Returns count of applied items.
    """
    to_apply = [gaps[i] for i in selected] if selected is not None else gaps
    count = 0
    for gap in to_apply:
        mn = gap.get("missing_node", {})
        node = Node(
            label=mn.get("label", ""),
            description=mn.get("description", ""),
            type=mn.get("type", "state"),
            archetype=mn.get("archetype") or None,
            source="llm",
        )
        chain.nodes.append(node)

        from_id = gap.get("between_from", "")
        to_id = gap.get("between_to", "")

        # Insert node between from and to: from→node, node→to
        if from_id and to_id:
            e1 = Edge(from_id=from_id, to_id=node.id, relation=gap.get("relation_in", "CAUSES"), source="llm")
            e2 = Edge(from_id=node.id, to_id=to_id, relation=gap.get("relation_out", "CAUSES"), source="llm")
            chain.edges.append(e1)
            chain.edges.append(e2)

        chain.history.append({
            "timestamp": datetime.now().isoformat(),
            "action": "enrich",
            "actor": "llm",
            "payload": {"type": "gap", "node_id": node.id, "gap": gap},
        })
        count += 1
    return count


def apply_weight_adjustments(chain: CausalChain, adjustments: list, selected: list = None) -> int:
    """Apply weight adjustments. Appends new edge version, deprecates old."""
    to_apply = [adjustments[i] for i in selected] if selected is not None else adjustments
    edge_map = {e.id: e for e in chain.edges}
    count = 0
    for adj in to_apply:
        eid = adj.get("edge_id", "")
        old = edge_map.get(eid)
        if not old or old.deprecated:
            continue
        old.deprecated = True
        new_edge = Edge(
            from_id=old.from_id,
            to_id=old.to_id,
            relation=old.relation,
            weight=adj.get("suggested_weight", old.weight),
            confidence=old.confidence,
            direction=old.direction,
            condition=old.condition,
            evidence=old.evidence,
            version=old.version + 1,
            source="llm",
        )
        chain.edges.append(new_edge)
        chain.history.append({
            "timestamp": datetime.now().isoformat(),
            "action": "edge_edit",
            "actor": "llm",
            "payload": {"type": "weight_adjustment", "old_id": eid, "new_id": new_edge.id},
        })
        count += 1
    return count
