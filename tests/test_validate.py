import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chain.schema import CausalChain, ChainMeta, Node, Edge
from chain.validate import validate, check_cycles


def _chain(*nodes, **kw):
    c = CausalChain()
    c.nodes = list(nodes)
    c.edges = kw.get("edges", [])
    return c


def _node(id_, label="n"):
    return Node(id=id_, label=label)


def _edge(id_, from_id, to_id, weight=0.5, relation="CAUSES"):
    return Edge(id=id_, from_id=from_id, to_id=to_id, weight=weight, relation=relation)


# ── Orphan edge ───────────────────────────────────────────────────────────

def test_orphan_edge_missing_from():
    n = _node("n1")
    e = _edge("e1", "MISSING", "n1")
    c = _chain(n, edges=[e])
    issues = validate(c)
    assert any(i["check"] == "orphan_edge" for i in issues)


def test_orphan_edge_missing_to():
    n = _node("n1")
    e = _edge("e1", "n1", "MISSING")
    c = _chain(n, edges=[e])
    issues = validate(c)
    assert any(i["check"] == "orphan_edge" for i in issues)


def test_valid_edge_no_orphan():
    n1, n2 = _node("n1"), _node("n2")
    e = _edge("e1", "n1", "n2")
    c = _chain(n1, n2, edges=[e])
    issues = validate(c)
    assert not any(i["check"] == "orphan_edge" for i in issues)


# ── Weight range ──────────────────────────────────────────────────────────

def test_weight_out_of_range_high():
    n1, n2 = _node("n1"), _node("n2")
    e = _edge("e1", "n1", "n2", weight=1.5)
    c = _chain(n1, n2, edges=[e])
    issues = validate(c)
    assert any(i["check"] == "weight_range" for i in issues)


def test_weight_out_of_range_low():
    n1, n2 = _node("n1"), _node("n2")
    e = _edge("e1", "n1", "n2", weight=-0.1)
    c = _chain(n1, n2, edges=[e])
    issues = validate(c)
    assert any(i["check"] == "weight_range" for i in issues)


def test_weight_boundary_valid():
    n1, n2 = _node("n1"), _node("n2")
    for w in (0.0, 0.5, 1.0):
        e = _edge("e1", "n1", "n2", weight=w)
        c = _chain(n1, n2, edges=[e])
        issues = validate(c)
        assert not any(i["check"] == "weight_range" for i in issues)


# ── Duplicate edges ───────────────────────────────────────────────────────

def test_duplicate_edge_warning():
    n1, n2 = _node("n1"), _node("n2")
    e1 = _edge("e1", "n1", "n2")
    e2 = _edge("e2", "n1", "n2")
    c = _chain(n1, n2, edges=[e1, e2])
    issues = validate(c)
    assert any(i["check"] == "duplicate_edge" for i in issues)


def test_deprecated_duplicate_ignored():
    n1, n2 = _node("n1"), _node("n2")
    e1 = _edge("e1", "n1", "n2")
    e2 = _edge("e2", "n1", "n2")
    e2.deprecated = True
    c = _chain(n1, n2, edges=[e1, e2])
    issues = validate(c)
    assert not any(i["check"] == "duplicate_edge" for i in issues)


# ── Orphan nodes ──────────────────────────────────────────────────────────

def test_orphan_node_warning():
    n1, n2 = _node("n1"), _node("n2")
    e = _edge("e1", "n1", "n1")  # self-loop, n2 is orphan
    # Make a valid edge to avoid orphan_edge
    e2 = _edge("e2", "n1", "n2")
    c_only_n1 = _chain(n1, n2, edges=[])  # both orphans without edges
    issues = validate(c_only_n1)
    assert any(i["check"] == "orphan_node" for i in issues)


def test_deprecated_node_not_orphan_checked():
    n1, n2 = _node("n1"), _node("n2")
    n2.deprecated = True
    e = _edge("e1", "n1", "n1")
    # n1 has self-loop, n2 is deprecated → no orphan warning for n2
    c = _chain(n1, n2, edges=[e])
    issues = validate(c)
    orphans = [i for i in issues if i["check"] == "orphan_node"]
    assert all(i["element_id"] != "n2" for i in orphans)


# ── Cycles ────────────────────────────────────────────────────────────────

def test_no_cycle():
    n1, n2, n3 = _node("n1"), _node("n2"), _node("n3")
    edges = [_edge("e1", "n1", "n2"), _edge("e2", "n2", "n3")]
    c = _chain(n1, n2, n3, edges=edges)
    cycles = check_cycles(c)
    assert cycles == []


def test_cycle_detected():
    n1, n2, n3 = _node("n1"), _node("n2"), _node("n3")
    edges = [_edge("e1", "n1", "n2"), _edge("e2", "n2", "n3"), _edge("e3", "n3", "n1")]
    c = _chain(n1, n2, n3, edges=edges)
    cycles = check_cycles(c)
    assert len(cycles) >= 1


# ── Clean chain ───────────────────────────────────────────────────────────

def test_clean_chain_no_errors():
    n1, n2 = _node("n1", "Cause"), _node("n2", "Effect")
    e = _edge("e1", "n1", "n2", weight=0.7)
    c = _chain(n1, n2, edges=[e])
    issues = validate(c)
    errors = [i for i in issues if i["severity"] == "error"]
    assert errors == []
