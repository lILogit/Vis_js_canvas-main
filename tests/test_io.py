import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chain.schema import CausalChain, ChainMeta, Node, Edge
from chain.io import save, load, to_dict, backup


def _make_chain():
    n1 = Node(id="n1", label="Cause", type="state", confidence=0.8)
    n2 = Node(id="n2", label="Effect", type="event", confidence=0.6)
    e1 = Edge(id="e1", from_id="n1", to_id="n2", relation="CAUSES", weight=0.7)
    c = CausalChain(
        meta=ChainMeta(name="Test Chain", domain="science"),
        nodes=[n1, n2],
        edges=[e1],
    )
    return c


# ── to_dict ───────────────────────────────────────────────────────────────

def test_to_dict_structure():
    c = _make_chain()
    d = to_dict(c)
    assert "meta" in d
    assert "nodes" in d
    assert "edges" in d
    assert "history" in d


def test_to_dict_edge_keys():
    c = _make_chain()
    d = to_dict(c)
    edge = d["edges"][0]
    assert "from" in edge   # serialised as "from", not "from_id"
    assert "to" in edge
    assert "from_id" not in edge


def test_to_dict_meta():
    c = _make_chain()
    d = to_dict(c)
    assert d["meta"]["name"] == "Test Chain"
    assert d["meta"]["domain"] == "science"


# ── save / load roundtrip ─────────────────────────────────────────────────

def test_save_load_roundtrip():
    c = _make_chain()
    with tempfile.NamedTemporaryFile(suffix=".causal.json", delete=False) as f:
        path = f.name
    try:
        save(c, path)
        loaded = load(path)
        assert loaded.meta.name == "Test Chain"
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1
        assert loaded.edges[0].from_id == "n1"
        assert loaded.edges[0].to_id == "n2"
        assert loaded.edges[0].weight == 0.7
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)


def test_save_creates_backup():
    c = _make_chain()
    with tempfile.NamedTemporaryFile(suffix=".causal.json", delete=False) as f:
        path = f.name
    try:
        save(c, path)  # first save (no backup yet, file empty from tempfile)
        save(c, path)  # second save → should create .bak
        assert os.path.exists(path + ".bak")
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)


def test_save_blocks_on_error():
    from chain.schema import CausalChain, Node, Edge
    n = Node(id="n1", label="X")
    e = Edge(id="e1", from_id="MISSING", to_id="n1")  # orphan edge → error
    c = CausalChain(nodes=[n], edges=[e])
    with tempfile.NamedTemporaryFile(suffix=".causal.json", delete=False) as f:
        path = f.name
    try:
        raised = False
        try:
            save(c, path)
        except ValueError:
            raised = True
        assert raised, "save() should raise on validation errors"
    finally:
        os.unlink(path)


# ── backup ────────────────────────────────────────────────────────────────

def test_backup_creates_file():
    c = _make_chain()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.causal.json")
        save(c, path)
        bak_dir = os.path.join(tmpdir, "bak")
        dest = backup(path, backup_dir=bak_dir)
        assert os.path.exists(dest)
        assert dest.endswith(".causal.json")
        assert "test" in os.path.basename(dest)
