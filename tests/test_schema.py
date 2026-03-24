import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chain.schema import Node, Edge, ChainMeta, CausalChain, short_id


def test_short_id_length():
    assert len(short_id()) == 8

def test_short_id_unique():
    assert short_id() != short_id()

def test_node_defaults():
    n = Node(label="test")
    assert n.type == "state"
    assert n.confidence == 0.7
    assert n.source == "user"
    assert not n.deprecated
    assert not n.flagged
    assert len(n.id) == 8

def test_edge_defaults():
    e = Edge(from_id="a", to_id="b")
    assert e.relation == "CAUSES"
    assert e.weight == 0.5
    assert e.version == 1
    assert not e.deprecated

def test_chain_meta_defaults():
    m = ChainMeta()
    assert m.name == "Untitled Chain"
    assert m.domain == "custom"
    assert m.version == 1

def test_causal_chain_empty():
    c = CausalChain()
    assert c.nodes == []
    assert c.edges == []
    assert c.history == []
