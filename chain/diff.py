from chain.schema import CausalChain


def diff(chain_a: CausalChain, chain_b: CausalChain) -> dict:
    """Compare two chains and return a structured diff."""
    a_nodes = {n.id: n for n in chain_a.nodes if not n.deprecated}
    b_nodes = {n.id: n for n in chain_b.nodes if not n.deprecated}
    a_edges = {e.id: e for e in chain_a.edges if not e.deprecated}
    b_edges = {e.id: e for e in chain_b.edges if not e.deprecated}

    added_nodes = [b_nodes[nid] for nid in b_nodes if nid not in a_nodes]
    removed_nodes = [a_nodes[nid] for nid in a_nodes if nid not in b_nodes]
    added_edges = [b_edges[eid] for eid in b_edges if eid not in a_edges]
    removed_edges = [a_edges[eid] for eid in a_edges if eid not in b_edges]

    changed_edges = []
    for eid in a_edges:
        if eid in b_edges:
            ea, eb = a_edges[eid], b_edges[eid]
            changes = {}
            if ea.weight != eb.weight:
                changes["weight"] = {"from": ea.weight, "to": eb.weight}
            if ea.relation != eb.relation:
                changes["relation"] = {"from": ea.relation, "to": eb.relation}
            if changes:
                changed_edges.append({"edge_id": eid, "changes": changes})

    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "changed_edges": changed_edges,
    }
