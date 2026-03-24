from chain.schema import CausalChain

VALID_NODE_TYPES = {
    "state", "event", "decision", "concept", "question", "blackbox",
    "goal", "task", "asset", "gate",
}

VALID_RELATIONS = {
    "CAUSES", "ENABLES", "BLOCKS", "TRIGGERS", "REDUCES", "REQUIRES", "AMPLIFIES",
    "PRECONDITION_OF", "RESOLVES", "FRAMES", "INSTANTIATES", "DIVERGES_TO",
}


def validate(chain: CausalChain) -> list:
    """
    Returns list of issues. Empty list = valid.
    Each issue: {severity, check, element_id, message}
    """
    issues = []
    node_ids = {n.id for n in chain.nodes if not n.deprecated}

    for edge in chain.edges:
        if edge.deprecated:
            continue
        if edge.from_id not in node_ids:
            issues.append({
                "severity": "error",
                "check": "orphan_edge",
                "element_id": edge.id,
                "message": f"from_id {edge.from_id!r} not found"
            })
        if edge.to_id not in node_ids:
            issues.append({
                "severity": "error",
                "check": "orphan_edge",
                "element_id": edge.id,
                "message": f"to_id {edge.to_id!r} not found"
            })
        if not (0.0 <= edge.weight <= 1.0):
            issues.append({
                "severity": "error",
                "check": "weight_range",
                "element_id": edge.id,
                "message": f"weight {edge.weight} out of range"
            })
        if edge.relation not in VALID_RELATIONS:
            issues.append({
                "severity": "warning",
                "check": "unknown_relation",
                "element_id": edge.id,
                "message": f"relation {edge.relation!r} not in vocabulary"
            })

    # Duplicate edges (same from/to/relation, both active)
    seen = {}
    for edge in chain.edges:
        if edge.deprecated:
            continue
        key = (edge.from_id, edge.to_id, edge.relation)
        if key in seen:
            issues.append({
                "severity": "warning",
                "check": "duplicate_edge",
                "element_id": edge.id,
                "message": f"duplicate of {seen[key]}"
            })
        seen[key] = edge.id

    # Orphan nodes (no edges at all)
    connected = {e.from_id for e in chain.edges if not e.deprecated}
    connected |= {e.to_id for e in chain.edges if not e.deprecated}
    for node in chain.nodes:
        if node.deprecated:
            continue
        if node.id not in connected:
            issues.append({
                "severity": "warning",
                "check": "orphan_node",
                "element_id": node.id,
                "message": f"node {node.label!r} has no edges"
            })

    # Unknown node types
    for node in chain.nodes:
        if node.deprecated:
            continue
        if node.type not in VALID_NODE_TYPES:
            issues.append({
                "severity": "warning",
                "check": "unknown_node_type",
                "element_id": node.id,
                "message": f"node type {node.type!r} not in taxonomy"
            })

    # GOAL: at most one active GOAL node per chain
    goal_nodes = [n for n in chain.nodes if not n.deprecated and n.type == "goal"]
    if len(goal_nodes) > 1:
        for g in goal_nodes[1:]:
            issues.append({
                "severity": "warning",
                "check": "multiple_goals",
                "element_id": g.id,
                "message": "chain has more than one active GOAL node; GOAL should be the single terminal anchor"
            })

    # ASSET: should connect to TASK via REQUIRES or ENABLES only
    asset_ids = {n.id for n in chain.nodes if not n.deprecated and n.type == "asset"}
    causal_from_asset = {
        e.id for e in chain.edges
        if not e.deprecated
        and e.from_id in asset_ids
        and e.relation not in ("REQUIRES", "ENABLES")
    }
    for eid in causal_from_asset:
        issues.append({
            "severity": "warning",
            "check": "asset_causal_edge",
            "element_id": eid,
            "message": "ASSET should connect to TASK via REQUIRES or ENABLES, not a causal relation"
        })

    # GATE: should have at least one DIVERGES_TO outbound edge
    gate_ids = {n.id for n in chain.nodes if not n.deprecated and n.type == "gate"}
    gate_diverges = {e.from_id for e in chain.edges if not e.deprecated and e.relation == "DIVERGES_TO"}
    for gid in gate_ids:
        if gid not in gate_diverges:
            issues.append({
                "severity": "warning",
                "check": "gate_no_divergence",
                "element_id": gid,
                "message": "GATE node has no DIVERGES_TO edges; add scored fork branches"
            })

    return issues


def check_cycles(chain: CausalChain) -> list:
    """Returns list of cycles found in the graph as lists of node ids."""
    adj = {n.id: [] for n in chain.nodes if not n.deprecated}
    for edge in chain.edges:
        if edge.deprecated:
            continue
        if edge.from_id in adj:
            adj[edge.from_id].append(edge.to_id)

    cycles = []
    visited = set()
    rec_stack = set()
    path = []

    def dfs(node):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
        path.pop()
        rec_stack.discard(node)

    for node in list(adj.keys()):
        if node not in visited:
            dfs(node)

    return cycles
