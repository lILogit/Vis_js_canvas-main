"""
Sensitivity analysis: for each node, Δpath_prob per unit Δcertainty.

Two entry points:
  sensitivity_analysis()      — per-node global exposure across all affected branches
  most_sensitive_node_for_branch() — within a single branch path, find the weakest link
"""
from __future__ import annotations

from .montecarlo import BRANCH_IDS, BRANCH_PATH_NODES, DEFAULT_CERTAINTIES, path_probability


def sensitivity_analysis(
    delta: float = 0.10,
    node_certainties: dict[str, float] | None = None,
) -> list[dict]:
    """
    For each node, compute total |Δpath_prob| across all branches it affects
    when certainty is perturbed by +delta.

    Returns a list sorted by exposure (descending):
      [{"node_id", "certainty", "exposure", "branches_affected"}, ...]
    """
    certs = node_certainties if node_certainties is not None else dict(DEFAULT_CERTAINTIES)

    # Only consider nodes that appear in at least one branch path
    path_membership: dict[str, list[str]] = {}
    for bid, path in BRANCH_PATH_NODES.items():
        for nid in path:
            path_membership.setdefault(nid, []).append(bid)

    base_probs = {bid: path_probability(bid, certs) for bid in BRANCH_IDS}

    results = []
    for nid, affected_branches in path_membership.items():
        c = certs.get(nid, 1.0)
        c_up = min(1.0, c + delta)
        certs_up = dict(certs, **{nid: c_up})
        # |Δpath_prob| / delta summed over affected branches
        total_delta = sum(
            abs(path_probability(bid, certs_up) - base_probs[bid])
            for bid in affected_branches
        )
        exposure = total_delta / delta
        results.append({
            "node_id":          nid,
            "certainty":        c,
            "exposure":         round(exposure, 6),
            "branches_affected": affected_branches,
        })

    results.sort(key=lambda x: x["exposure"], reverse=True)
    return results


def most_sensitive_node_for_branch(
    branch_id: str,
    node_certainties: dict[str, float] | None = None,
    delta: float = 0.10,
) -> dict:
    """
    Within the path to branch_id, return the node with the highest |ΔP/Δc|.

    For a path product P = Π c_i, ∂P/∂c_i = P / c_i, so the node with the
    smallest certainty has the largest marginal sensitivity.

    Returns {"node_id", "certainty", "sensitivity"}.
    """
    certs = node_certainties if node_certainties is not None else dict(DEFAULT_CERTAINTIES)
    path  = BRANCH_PATH_NODES[branch_id]

    base_p = path_probability(branch_id, certs)
    best   = None

    for nid in path:
        c    = certs.get(nid, 1.0)
        c_up = min(1.0, c + delta)
        p_up = path_probability(branch_id, dict(certs, **{nid: c_up}))
        sensitivity = abs(p_up - base_p) / delta
        if best is None or sensitivity > best["sensitivity"]:
            best = {"node_id": nid, "certainty": c, "sensitivity": round(sensitivity, 6)}

    return best  # type: ignore[return-value]


def branch_exposures(
    node_certainties: dict[str, float] | None = None,
    delta: float = 0.10,
) -> list[dict]:
    """
    Per-branch exposure: sum of |ΔP_b| across all nodes in that branch's path.

    Returns list sorted by exposure descending:
      [{"branch", "exposure", "driver_node", "driver_certainty"}, ...]
    """
    certs = node_certainties if node_certainties is not None else dict(DEFAULT_CERTAINTIES)

    result = []
    for bid in BRANCH_IDS:
        path     = BRANCH_PATH_NODES[bid]
        base_p   = path_probability(bid, certs)
        total_dp = 0.0
        min_cert_node = min(path, key=lambda n: certs.get(n, 1.0))

        for nid in path:
            c    = certs.get(nid, 1.0)
            c_up = min(1.0, c + delta)
            p_up = path_probability(bid, dict(certs, **{nid: c_up}))
            total_dp += abs(p_up - base_p)

        result.append({
            "branch":           bid,
            "base_prob":        round(base_p, 6),
            "exposure":         round(total_dp / delta, 6),
            "driver_node":      min_cert_node,
            "driver_certainty": certs.get(min_cert_node, 1.0),
        })

    result.sort(key=lambda x: x["exposure"], reverse=True)
    return result
