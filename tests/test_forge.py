"""T2 forge tests — determinism, section ordering, anti-patterns, error handling."""
import json
import os
import re
import sys

import pytest

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from forge.emit import ForgeError, forge_chain

# ── Fixtures ──────────────────────────────────────────────────────────────────

CHAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "chains", "mortgage-mvp.causal.json")


def _load_chain():
    with open(CHAIN_PATH, encoding="utf-8") as f:
        return json.load(f)


SECTION_ORDER = ["STATES", "ASSETS", "EVENTS", "GATES", "DECISIONS", "TASKS", "TERMINALS", "CHAIN", "ENTRY POINT"]

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_byte_identical_reforge():
    """Two consecutive forge calls produce byte-identical output (modulo timestamp line)."""
    chain = _load_chain()
    out1 = forge_chain(chain)
    out2 = forge_chain(chain)

    def strip_timestamp(code: str) -> str:
        return "\n".join(
            line for line in code.splitlines()
            if '"timestamp"' not in line
        )

    assert strip_timestamp(out1) == strip_timestamp(out2)


def test_section_ordering():
    """Sections appear in canonical order: STATES < ASSETS < ... < CHAIN < ENTRY POINT."""
    chain = _load_chain()
    code = forge_chain(chain)
    positions = {sec: code.find(f"# ─── {sec}") for sec in SECTION_ORDER}

    # Every section that appears must follow the previous one
    present = [(sec, pos) for sec, pos in positions.items() if pos != -1]
    for i in range(1, len(present)):
        prev_sec, prev_pos = present[i - 1]
        curr_sec, curr_pos = present[i]
        assert prev_pos < curr_pos, (
            f"Section '{curr_sec}' (pos {curr_pos}) appears before '{prev_sec}' (pos {prev_pos})"
        )


def test_forge_meta_present():
    """Generated module contains a _forge_meta dict with required keys."""
    chain = _load_chain()
    code = forge_chain(chain)
    assert "_forge_meta" in code
    for key in ("source_chain", "source_hash", "forge_version", "timestamp"):
        assert f'"{key}"' in code, f"Missing _forge_meta key: {key}"


def test_source_hash_format():
    """source_hash starts with 'sha256:' and is 71 chars long."""
    chain = _load_chain()
    code = forge_chain(chain)
    match = re.search(r'"source_hash":\s*"(sha256:[0-9a-f]{64})"', code)
    assert match, "source_hash not found or malformed"


def test_blackbox_has_symptom():
    """Every BLACKBOX class body contains a symptom attribute, not just 'pass'."""
    chain = _load_chain()
    code = forge_chain(chain)
    # Find all @BLACKBOX blocks
    for match in re.finditer(r'@BLACKBOX\(.*?\)\n@dataclass\nclass (\w+):(.*?)(?=\n@|\nif |\Z)',
                             code, re.DOTALL):
        class_name = match.group(1)
        body = match.group(2)
        assert "symptom" in body, f"BLACKBOX class {class_name} missing 'symptom' attribute"
        assert "pass" not in body, f"BLACKBOX class {class_name} should not have 'pass' body"


def test_no_anti_patterns():
    """Scan forged output for forbidden patterns."""
    chain = _load_chain()
    code = forge_chain(chain)

    # Certainty must be in decorator, never in docstrings / comments
    # (check no bare float like '= 0.75' or 'certainty 0.75' appears in docstrings)
    for m in re.finditer(r'""".*?"""', code, re.DOTALL):
        docstring = m.group()
        assert not re.search(r'certainty\s*[=:]\s*[\d.]+', docstring, re.IGNORECASE), \
            f"Certainty value found inside docstring: {docstring[:80]}"

    # No 'return dict(...)' — GOAL must be a class
    assert "return dict(" not in code, "GOAL emitted as return dict(...) — must be a class"

    # Edges must NOT appear inside if __name__ block
    main_block = code.split('if __name__ == "__main__":')[-1] if '__name__' in code else ""
    assert "causes(" not in main_block and "enables(" not in main_block, \
        "Edge declarations found inside __main__ block"

    # _forge_meta must be present
    assert "_forge_meta" in code


def test_nodes_sorted_within_section():
    """Within each section, class definitions appear in alphabetical order by rcde_id."""
    chain = _load_chain()
    code = forge_chain(chain)

    rcde_ids = re.findall(r'rcde_id="([^"]+)"', code)
    # Group by section: collect ids in order they appear
    # Verify they are sorted within each section banner
    current_section_ids: list[str] = []
    current_section = None

    for line in code.splitlines():
        sec_match = re.match(r"# ─── (\w+)", line)
        if sec_match:
            if current_section and current_section_ids:
                assert current_section_ids == sorted(current_section_ids), \
                    f"Section {current_section} nodes not alphabetically sorted: {current_section_ids}"
            current_section = sec_match.group(1)
            current_section_ids = []
        id_match = re.search(r'rcde_id="([^"]+)"', line)
        if id_match:
            current_section_ids.append(id_match.group(1))


def test_forge_error_missing_type():
    """forge_chain raises ForgeError when a node is missing its type field."""
    chain = _load_chain()
    bad_node = {
        "id": "orphan_x", "label": "Bad", "description": "",
        "deprecated": False,
    }
    chain_copy = dict(chain, nodes=chain["nodes"] + [bad_node])
    with pytest.raises(ForgeError, match="missing 'type'"):
        forge_chain(chain_copy)


def test_forge_error_unknown_type():
    """forge_chain raises ForgeError for an unknown node type."""
    chain = _load_chain()
    bad_node = {
        "id": "weird_x", "label": "Weird", "description": "",
        "type": "unicorn", "deprecated": False,
    }
    chain_copy = dict(chain, nodes=chain["nodes"] + [bad_node])
    with pytest.raises(ForgeError, match="unknown type"):
        forge_chain(chain_copy)


def test_forge_error_unknown_relation():
    """forge_chain raises ForgeError for an unknown edge relation."""
    chain = _load_chain()
    bad_edge = {
        "id": "e_bad", "from": "mortgage_active", "to": "monthly_income",
        "relation": "TELEPORTS", "deprecated": False,
    }
    chain_copy = dict(chain, edges=chain["edges"] + [bad_edge])
    with pytest.raises(ForgeError, match="unknown relation"):
        forge_chain(chain_copy)


def test_chain_edges_sorted():
    """CHAIN list edges are sorted by (relation, from, to)."""
    chain = _load_chain()
    code = forge_chain(chain)

    chain_block = re.search(r"CHAIN = \[(.*?)\]", code, re.DOTALL)
    assert chain_block, "CHAIN list not found"
    edge_calls = re.findall(r'(\w+)\("([^"]+)",\s*"([^"]+)"\)', chain_block.group(1))
    # edge_calls is list of (fn_name, src, dst)
    from forge.runtime import _REGISTRY  # noqa
    # Map fn name back to relation for sort key
    fn_to_rel = {
        "causes": "CAUSES", "enables": "ENABLES", "triggers": "TRIGGERS",
        "reduces": "REDUCES", "frames": "FRAMES", "instantiates": "INSTANTIATES",
        "precondition_of": "PRECONDITION_OF", "diverges_to": "DIVERGES_TO",
        "blocks": "BLOCKS", "amplifies": "AMPLIFIES", "resolves": "RESOLVES",
        "requires": "REQUIRES",
    }
    keys = [(fn_to_rel.get(fn, fn), src, dst) for fn, src, dst in edge_calls]
    assert keys == sorted(keys), "CHAIN edges are not sorted by (relation, from, to)"
