"""
forge/emit.py — forge_chain(chain: dict) → str

Converts a .causal.json dict into a deterministic Python module.
Two calls on the same chain produce byte-identical output (modulo timestamp).
"""
from __future__ import annotations

from datetime import datetime, timezone

from .canonical import chain_hash

FORGE_VERSION = "1.0.0"

# node_id → (dataclass_field_name, scenario_key) for nodes that carry numeric values
_NODE_FIELDS: dict[str, tuple[str, str]] = {
    "alt_bank_offer":  ("rate",        "alt_rate"),
    "renewal_offer":   ("rate",        "renewal_rate"),
    "mortgage_active": ("annual_rate", "annual_rate"),
}

# Node type → section banner name
_SECTION_FOR: dict[str, str] = {
    "state":    "STATES",
    "asset":    "ASSETS",
    "event":    "EVENTS",
    "gate":     "GATES",
    "decision": "DECISIONS",
    "task":     "TASKS",
    "goal":     "TERMINALS",
    "blackbox": "TERMINALS",
}

# Canonical section order (matches spec)
_SECTION_ORDER = ["STATES", "ASSETS", "EVENTS", "GATES", "DECISIONS", "TASKS", "TERMINALS"]

# Node type → runtime decorator name
_DECORATOR_FOR: dict[str, str] = {
    "state":    "STATE",
    "asset":    "ASSET",
    "event":    "EVENT",
    "gate":     "GATE",
    "decision": "DECISION",
    "task":     "TASK",
    "goal":     "GOAL",
    "blackbox": "BLACKBOX",
}

# Edge relation → runtime function name
_RELATION_FN: dict[str, str] = {
    "CAUSES":          "causes",
    "ENABLES":         "enables",
    "TRIGGERS":        "triggers",
    "REDUCES":         "reduces",
    "FRAMES":          "frames",
    "INSTANTIATES":    "instantiates",
    "PRECONDITION_OF": "precondition_of",
    "DIVERGES_TO":     "diverges_to",
    "BLOCKS":          "blocks",
    "AMPLIFIES":       "amplifies",
    "RESOLVES":        "resolves",
    "REQUIRES":        "requires",
}


class ForgeError(Exception):
    """Raised when the chain cannot be forged due to a structural problem."""


def _to_pascal(snake: str) -> str:
    return "".join(w.capitalize() for w in snake.split("_"))


def _banner(section: str) -> str:
    fill = "─" * (74 - len(section))
    return f"# ─── {section} {fill}"


def forge_chain(chain: dict) -> str:
    """
    Emit a deterministic Python module from a .causal.json dict.

    Raises ForgeError on structural problems (missing fields, unknown types).
    Never emits best-effort output — all-or-nothing.
    """
    meta   = chain.get("meta", {})
    nodes  = [n for n in chain.get("nodes", []) if not n.get("deprecated")]
    edges  = [e for e in chain.get("edges", []) if not e.get("deprecated")]

    # ── Validation pass ──────────────────────────────────────────────────────
    for n in nodes:
        nid = n.get("id", "")
        if not nid:
            raise ForgeError(f"Node missing 'id': {n}")
        if not n.get("type"):
            raise ForgeError(f"Node '{nid}' missing 'type'")
        if n["type"] not in _SECTION_FOR:
            raise ForgeError(f"Node '{nid}' has unknown type '{n['type']}'")

    for e in edges:
        eid = e.get("id", "?")
        if not e.get("from") or not e.get("to"):
            raise ForgeError(f"Edge '{eid}' missing 'from' or 'to'")
        if e.get("relation") not in _RELATION_FN:
            raise ForgeError(f"Edge '{eid}' has unknown relation '{e.get('relation')}'")

    # ── Metadata ─────────────────────────────────────────────────────────────
    chain_name       = meta.get("name", "Untitled")
    chain_id         = meta.get("id", "unknown")
    src_hash         = chain_hash(chain)
    timestamp        = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scenario_ovr     = meta.get("scenario_overrides", {})
    evidence_list    = chain.get("evidence", [])
    last_enrichment  = evidence_list[-1]["id"] if evidence_list else None

    # ── Collect used symbols for imports ─────────────────────────────────────
    used_decorators = sorted({_DECORATOR_FOR[n["type"]] for n in nodes})
    used_relations  = sorted({_RELATION_FN[e["relation"]] for e in edges})

    # ── Group and sort nodes by section ──────────────────────────────────────
    sections: dict[str, list] = {s: [] for s in _SECTION_ORDER}
    for n in sorted(nodes, key=lambda x: x["id"]):
        sections[_SECTION_FOR[n["type"]]].append(n)

    # ── Sort edges deterministically ─────────────────────────────────────────
    sorted_edges = sorted(edges, key=lambda e: (e["relation"], e["from"], e["to"]))

    # ── Emit ──────────────────────────────────────────────────────────────────
    L: list[str] = []

    def line(s: str = "") -> None:
        L.append(s)

    # Module docstring + future import (must be first non-comment lines)
    line(f'"""{chain_name} — forged from chains/{chain_id}.causal.json"""')
    line("from __future__ import annotations")
    line()

    # Sys-path setup so generated file is runnable from project root without install
    line("import sys as _sys, os as _os")
    line("_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))")
    line("from dataclasses import dataclass")

    # Runtime imports
    dec_str = ", ".join(used_decorators)
    rel_str = ", ".join(used_relations + ["simulate"])
    line("from forge.runtime import (")
    line(f"    {dec_str},")
    line(f"    {rel_str},")
    line(")")
    line()

    # _forge_meta
    line("_forge_meta = {")
    line(f'    "source_chain":  "{chain_id}",')
    line(f'    "source_hash":   "{src_hash}",')
    line(f'    "forge_version": "{FORGE_VERSION}",')
    line(f'    "timestamp":     "{timestamp}",')
    if last_enrichment:
        line(f'    "last_enrichment": "{last_enrichment}",')
    line("}")
    line()

    # Node sections
    for sec_name in _SECTION_ORDER:
        sec_nodes = sections[sec_name]
        if not sec_nodes:
            continue
        line(_banner(sec_name))
        line()
        for node in sec_nodes:
            _emit_node(L, node, scenario_overrides=scenario_ovr)

    # CHAIN section
    line(_banner("CHAIN"))
    line()
    line("CHAIN = [")
    for e in sorted_edges:
        fn  = _RELATION_FN[e["relation"]]
        line(f'    {fn}("{e["from"]}", "{e["to"]}"),')
    line("]")
    line()

    # ENTRY POINT section
    line(_banner("ENTRY POINT"))
    line()
    line('if __name__ == "__main__":')
    line(f'    print("Chain : {chain_name}")')
    line(f'    print("Source: chains/{chain_id}.causal.json")')
    line(f'    print("Hash  : {src_hash}")')
    line('    result = simulate(CHAIN, mode="monte_carlo", n=10_000, seed=42)')
    line('    print(f"Simulation result: {result}")')
    line()

    return "\n".join(L)


def _emit_node(L: list[str], node: dict, *, scenario_overrides: dict | None = None) -> None:
    nid        = node["id"]
    ntype      = node["type"]
    confidence = node.get("confidence", 0.7)
    archetype  = node.get("archetype")
    desc       = (node.get("description") or "").strip().replace('"""', "'''")
    class_name = _to_pascal(nid)
    decorator  = _DECORATOR_FOR[ntype]

    # Collect extra decorator kwargs
    arch_arg = f', archetype="{archetype}"' if archetype else ""
    evidence_ref = node.get("_evidence_ref")
    ev_arg = f', _evidence_refs=["{evidence_ref}"]' if evidence_ref else ""

    L.append(f'@{decorator}(rcde_id="{nid}", certainty={confidence:.4f}{arch_arg}{ev_arg})')
    L.append("@dataclass")
    L.append(f"class {class_name}:")
    if desc:
        L.append(f'    """{desc}"""')

    # Emit numeric field when a scenario override exists for this node
    field_info = _NODE_FIELDS.get(nid)
    if field_info and scenario_overrides:
        field_name, scenario_key = field_info
        value = scenario_overrides.get(scenario_key)
        if value is not None:
            L.append(f"    {field_name}: float = {value!r}")
            L.append("")
            return

    if ntype == "blackbox":
        safe = desc.replace('"', '\\"')
        L.append(f'    symptom: str = "{safe}"')
    else:
        L.append("    pass")
    L.append("")
