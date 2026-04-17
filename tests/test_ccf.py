"""CCF v1 test suite — TST-01 through TST-07."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow importing from src/ccf without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ccf import compress, restore  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_graph(
    nodes: list[dict],
    edges: list[dict] | None = None,
) -> dict:
    """Wrap nodes/edges in a minimal valid graph envelope."""
    return {
        "meta": {
            "id": "aabbccdd",
            "name": "Test Chain",
            "domain": "test",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "version": 1,
            "author": "",
            "description": "",
        },
        "nodes": nodes,
        "edges": edges or [],
        "history": [],
        "summaries": [],
    }


def _node(
    idx: str,
    label: str,
    *,
    ntype: str = "state",
    archetype: str = "mechanism",
    description: str = "",
    confidence: float = 0.7,
    flagged: bool = False,
    deprecated: bool = False,
    tags: list[str] | None = None,
    chain_link: str | None = None,
) -> dict:
    return {
        "id": idx,
        "label": label,
        "description": description,
        "type": ntype,
        "archetype": archetype,
        "tags": tags or [],
        "confidence": confidence,
        "created_at": "2026-01-01T00:00:00",
        "source": "user",
        "deprecated": deprecated,
        "flagged": flagged,
        "chain_link": chain_link,
    }


def _edge(
    idx: str,
    from_id: str,
    to_id: str,
    relation: str = "CAUSES",
    *,
    weight: float = 0.5,
    confidence: float = 0.5,
) -> dict:
    return {
        "id": idx,
        "from": from_id,
        "to": to_id,
        "relation": relation,
        "weight": weight,
        "confidence": confidence,
        "direction": "forward",
        "condition": None,
        "evidence": "",
        "deprecated": False,
        "flagged": False,
        "version": 1,
        "created_at": "2026-01-01T00:00:00",
        "source": "user",
    }


def _structural_fields_node(n: dict) -> dict:
    """Return node fields that must survive roundtrip (exclude id, created_at)."""
    return {k: v for k, v in n.items() if k not in {"id", "created_at"}}


def _structural_fields_edge(e: dict, alias_map: dict[str, str]) -> dict:
    """Return edge fields normalised for comparison (remap from/to to aliases)."""
    out = {k: v for k, v in e.items() if k not in {"id", "created_at"}}
    out["from"] = alias_map.get(str(e["from"]), e["from"])
    out["to"] = alias_map.get(str(e["to"]), e["to"])
    return out


# ---------------------------------------------------------------------------
# TST-01 — Round-trip identity on fixture
# ---------------------------------------------------------------------------

def test_roundtrip_fixture() -> None:
    """restore(compress(g)) must equal g on all structural fields."""
    original = json.loads((FIXTURES / "sample.causal.json").read_text())
    restored = restore(compress(original))

    orig_nodes = original["nodes"]
    rest_nodes = restored["nodes"]
    assert len(orig_nodes) == len(rest_nodes), "node count mismatch"

    for orig, rest in zip(orig_nodes, rest_nodes):
        for field in ("label", "description", "type", "archetype", "tags",
                      "confidence", "source", "deprecated", "flagged", "chain_link"):
            assert orig[field] == rest[field], f"node field {field!r} mismatch: {orig[field]!r} != {rest[field]!r}"

    orig_edges = original["edges"]
    rest_edges = restored["edges"]
    assert len(orig_edges) == len(rest_edges), "edge count mismatch"

    # Build alias maps from both sides so we can compare from/to symbolically
    orig_id_to_alias = {n["id"]: f"n{i}" for i, n in enumerate(orig_nodes)}
    rest_id_to_alias = {n["id"]: f"n{i}" for i, n in enumerate(rest_nodes)}

    for orig_e, rest_e in zip(orig_edges, rest_edges):
        for field in ("relation", "weight", "confidence", "direction",
                      "condition", "evidence", "deprecated", "flagged"):
            assert orig_e[field] == rest_e[field], (
                f"edge field {field!r} mismatch: {orig_e[field]!r} != {rest_e[field]!r}"
            )
        assert orig_id_to_alias[orig_e["from"]] == rest_id_to_alias[rest_e["from"]]
        assert orig_id_to_alias[orig_e["to"]] == rest_id_to_alias[rest_e["to"]]


# ---------------------------------------------------------------------------
# TST-02 — Non-default node fields preserved
# ---------------------------------------------------------------------------

def test_non_default_node_fields() -> None:
    """confidence=0.9, flagged=True, tags=['trading','risk'], deprecated=True survive roundtrip."""
    n = _node("a1b2c3d4", "Risk Factor",
               confidence=0.9, flagged=True, tags=["trading", "risk"], deprecated=True)
    graph = _minimal_graph([n])
    restored = restore(compress(graph))
    r = restored["nodes"][0]
    assert r["confidence"] == 0.9
    assert r["flagged"] is True
    assert r["tags"] == ["trading", "risk"]
    assert r["deprecated"] is True


# ---------------------------------------------------------------------------
# TST-03 — Edge non-default weight/confidence
# ---------------------------------------------------------------------------

def test_edge_non_default_weight() -> None:
    """weight=0.8, confidence=0.9 produces ',0.8,0.9' suffix and restores correctly."""
    n0 = _node("n0000001", "A")
    n1 = _node("n0000002", "B")
    e = _edge("e0000001", "n0000001", "n0000002", "CAUSES", weight=0.8, confidence=0.9)
    graph = _minimal_graph([n0, n1], [e])

    ccf = compress(graph)
    assert "CAUSES,0.8,0.9" in ccf, f"Expected ',0.8,0.9' suffix in: {ccf!r}"

    restored = restore(ccf)
    re = restored["edges"][0]
    assert re["weight"] == 0.8
    assert re["confidence"] == 0.9


# ---------------------------------------------------------------------------
# TST-04 — chain_link round-trip
# ---------------------------------------------------------------------------

def test_chain_link_roundtrip() -> None:
    """chain_link='cluster-demo.causal.json' survives compress→restore."""
    n = _node("cccc1111", "Hub Node", chain_link="cluster-demo.causal.json")
    graph = _minimal_graph([n])
    restored = restore(compress(graph))
    assert restored["nodes"][0]["chain_link"] == "cluster-demo.causal.json"


# ---------------------------------------------------------------------------
# TST-05 — Compression ratio
# ---------------------------------------------------------------------------

def test_compress_ratio() -> None:
    """CCF output must be <15% of JSON size for a typical graph with all-default fields."""
    original = json.loads((FIXTURES / "sample.causal.json").read_text())
    ccf = compress(original)
    json_len = len(json.dumps(original))
    ccf_len = len(ccf)
    ratio = ccf_len / json_len
    assert ratio < 0.15, f"Compression ratio {ratio:.3f} >= 0.15 (ccf={ccf_len}, json={json_len})"


# ---------------------------------------------------------------------------
# TST-06 — Error cases
# ---------------------------------------------------------------------------

def test_error_compress_empty() -> None:
    """compress({}) raises ValueError."""
    with pytest.raises(ValueError):
        compress({})


def test_error_restore_bad_prefix() -> None:
    """restore('BADLINE:x') raises ValueError."""
    with pytest.raises(ValueError):
        restore("BADLINE:x")


def test_error_restore_unknown_alias() -> None:
    """E-line referencing unknown alias raises ValueError."""
    ccf = "GRAPH:Test|test|00000000\nN:n0=A[state/mechanism]\nE:n99->n0 CAUSES"
    with pytest.raises(ValueError, match="[Uu]nknown alias"):
        restore(ccf)


# ---------------------------------------------------------------------------
# TST-07 — History reconstruction
# ---------------------------------------------------------------------------

def test_history_reconstruction() -> None:
    """len(history) == len(nodes) + len(edges); first N entries are node_add."""
    original = json.loads((FIXTURES / "sample.causal.json").read_text())
    restored = restore(compress(original))

    history = restored["history"]
    nodes = restored["nodes"]
    edges = restored["edges"]

    assert len(history) == len(nodes) + len(edges)
    for entry in history[: len(nodes)]:
        assert entry["action"] == "node_add"
    for entry in history[len(nodes) :]:
        assert entry["action"] == "edge_add"
