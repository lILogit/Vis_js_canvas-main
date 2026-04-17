"""CCF v1 — Causal Compact Format compress and restore."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

log = logging.getLogger(__name__)

from .defaults import EDGE_DEFAULTS, META_DEFAULTS, NODE_DEFAULTS
from .grammar import VALID_ARCHETYPES, VALID_RELATIONS, VALID_TYPES

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ALIAS_RE = re.compile(r"^(n\d+)=")
_CONF_RE = re.compile(r"^~(\d+(?:\.\d+)?)")


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _fresh_id() -> str:
    return uuid4().hex[:8]


def _parse_node_line(line: str, alias_to_id: dict[str, str]) -> dict[str, Any]:
    """Parse a single N: line and register the alias."""
    rest = line[2:]  # strip "N:"

    m = _ALIAS_RE.match(rest)
    if not m:
        raise ValueError(f"Malformed N-line (no alias): {line!r}")
    alias = m.group(1)
    rest = rest[m.end():]

    # label up to '['
    bracket = rest.find("[")
    if bracket == -1:
        raise ValueError(f"Malformed N-line (no '[' for type/archetype): {line!r}")
    label = rest[:bracket]
    rest = rest[bracket:]

    # [type/archetype]
    close = rest.find("]")
    if close == -1:
        raise ValueError(f"Malformed N-line (no ']'): {line!r}")
    inner = rest[1:close]
    if "/" not in inner:
        raise ValueError(f"Malformed N-line (type/archetype missing '/'): {line!r}")
    type_str, arch_str = inner.split("/", 1)
    rest = rest[close + 1:]

    # Optional: "description"
    description = ""
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            raise ValueError(f"Malformed N-line (unclosed description quote): {line!r}")
        description = rest[1:end]
        rest = rest[end + 1:]

    # Optional: @chain_link  (read until next ~, {, !, or EOL)
    chain_link: str | None = None
    if rest.startswith("@"):
        m2 = re.match(r"@([^~{!\s]+)", rest)
        if m2:
            chain_link = m2.group(1)
            rest = rest[m2.end():]

    # Optional: ~confidence  (must NOT be "~dep")
    confidence: float = float(NODE_DEFAULTS["confidence"])
    if rest.startswith("~") and not rest.startswith("~dep"):
        cm = _CONF_RE.match(rest)
        if cm:
            confidence = float(cm.group(1))
            rest = rest[cm.end():]

    # Optional: {tag1,tag2,...}
    tags: list[str] = []
    if rest.startswith("{"):
        close_b = rest.find("}")
        if close_b == -1:
            raise ValueError(f"Malformed N-line (unclosed '{{' for tags): {line!r}")
        raw = rest[1:close_b]
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        rest = rest[close_b + 1:]

    # Optional: ! (flagged)
    flagged = False
    if rest.startswith("!"):
        flagged = True
        rest = rest[1:]

    # Optional: ~dep (deprecated)
    deprecated = False
    if rest.startswith("~dep"):
        deprecated = True

    node_id = _fresh_id()
    alias_to_id[alias] = node_id
    ts = _now()

    return {
        "id": node_id,
        "label": label,
        "description": description,
        "type": type_str,
        "archetype": arch_str,
        "tags": tags,
        "confidence": confidence,
        "created_at": ts,
        "source": str(NODE_DEFAULTS["source"]),
        "deprecated": deprecated,
        "flagged": flagged,
        "chain_link": chain_link,
    }


def _parse_edge_line(line: str, alias_to_id: dict[str, str]) -> dict[str, Any]:
    """Parse a single E: line."""
    rest = line[2:]  # strip "E:"

    arrow = rest.find("->")
    if arrow == -1:
        raise ValueError(f"Malformed E-line (no '->'): {line!r}")
    from_alias = rest[:arrow]
    rest = rest[arrow + 2:]

    space = rest.find(" ")
    if space == -1:
        raise ValueError(f"Malformed E-line (no space after to-alias): {line!r}")
    to_alias = rest[:space]
    rest = rest[space + 1:]

    if from_alias not in alias_to_id:
        raise ValueError(f"Unknown alias {from_alias!r} in E-line: {line!r}")
    if to_alias not in alias_to_id:
        raise ValueError(f"Unknown alias {to_alias!r} in E-line: {line!r}")

    parts = rest.split(",")
    relation = parts[0].strip()

    weight: float = float(EDGE_DEFAULTS["weight"])
    edge_conf: float = float(EDGE_DEFAULTS["confidence"])
    if len(parts) >= 3:
        weight = float(parts[1])
        edge_conf = float(parts[2])

    edge_id = _fresh_id()
    ts = _now()

    return {
        "id": edge_id,
        "from": alias_to_id[from_alias],
        "to": alias_to_id[to_alias],
        "relation": relation,
        "weight": weight,
        "confidence": edge_conf,
        "direction": str(EDGE_DEFAULTS["direction"]),
        "condition": EDGE_DEFAULTS["condition"],
        "evidence": str(EDGE_DEFAULTS["evidence"]),
        "deprecated": bool(EDGE_DEFAULTS["deprecated"]),
        "flagged": bool(EDGE_DEFAULTS["flagged"]),
        "version": int(EDGE_DEFAULTS["version"]),
        "created_at": ts,
        "source": str(EDGE_DEFAULTS["source"]),
    }


def _structural_diff(
    original: dict[str, Any],
    restored: dict[str, Any],
) -> list[str]:
    """Return list of structural differences, ignoring UUIDs and timestamps."""
    diffs: list[str] = []

    skip_meta = {"id", "created_at", "updated_at"}
    skip_node = {"id", "created_at"}
    skip_edge = {"id", "created_at"}

    orig_meta: dict[str, Any] = dict(original.get("meta", {}))
    rest_meta: dict[str, Any] = dict(restored.get("meta", {}))
    for k in set(orig_meta) | set(rest_meta):
        if k in skip_meta:
            continue
        if orig_meta.get(k) != rest_meta.get(k):
            diffs.append(f"meta.{k}: {orig_meta.get(k)!r} → {rest_meta.get(k)!r}")

    orig_nodes: list[dict[str, Any]] = list(original.get("nodes", []))
    rest_nodes: list[dict[str, Any]] = list(restored.get("nodes", []))
    if len(orig_nodes) != len(rest_nodes):
        diffs.append(f"node count: {len(orig_nodes)} → {len(rest_nodes)}")
    else:
        for i, (o, r) in enumerate(zip(orig_nodes, rest_nodes)):
            for k in set(o) | set(r):
                if k in skip_node:
                    continue
                if o.get(k) != r.get(k):
                    diffs.append(f"node[{i}].{k}: {o.get(k)!r} → {r.get(k)!r}")

    orig_edges: list[dict[str, Any]] = list(original.get("edges", []))
    rest_edges: list[dict[str, Any]] = list(restored.get("edges", []))
    if len(orig_edges) != len(rest_edges):
        diffs.append(f"edge count: {len(orig_edges)} → {len(rest_edges)}")
    else:
        orig_node_ids = [str(n["id"]) for n in orig_nodes]
        rest_node_ids = [str(n["id"]) for n in rest_nodes]
        id_to_alias: dict[str, str] = {nid: f"n{i}" for i, nid in enumerate(orig_node_ids)}
        rest_id_to_alias: dict[str, str] = {nid: f"n{i}" for i, nid in enumerate(rest_node_ids)}

        for i, (o, r) in enumerate(zip(orig_edges, rest_edges)):
            for k in set(o) | set(r):
                if k in skip_edge:
                    continue
                ov: Any = o.get(k)
                rv: Any = r.get(k)
                if k in ("from", "to"):
                    ov = id_to_alias.get(str(ov), ov)
                    rv = rest_id_to_alias.get(str(rv), rv)
                if ov != rv:
                    diffs.append(f"edge[{i}].{k}: {ov!r} → {rv!r}")

    return diffs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compress(graph: dict[str, Any]) -> str:
    """Compress a causal.json dict to a CCF v1 string.

    Raises ValueError on missing required fields, invalid enums, or dangling edges.
    """
    for key in ("meta", "nodes", "edges"):
        if key not in graph:
            raise ValueError(f"Missing required top-level key: {key!r}")

    meta: dict[str, Any] = graph["meta"]
    if not isinstance(meta, dict):
        raise ValueError("'meta' must be a dict")
    nodes: list[dict[str, Any]] = list(graph["nodes"])
    edges: list[dict[str, Any]] = list(graph["edges"])

    log.debug("compress: %r  nodes=%d  edges=%d", meta.get("name", ""), len(nodes), len(edges))

    # Build alias map and validate nodes
    alias_map: dict[str, str] = {}
    for i, node in enumerate(nodes):
        for req in ("id", "label", "type", "archetype"):
            if req not in node:
                raise ValueError(f"Node[{i}] missing required field: {req!r}")
        ntype = str(node["type"])
        arch = str(node["archetype"])
        if ntype not in VALID_TYPES:
            raise ValueError(f"Node[{i}] invalid type: {ntype!r}")
        if arch not in VALID_ARCHETYPES:
            raise ValueError(f"Node[{i}] invalid archetype: {arch!r}")
        alias_map[str(node["id"])] = f"n{i}"

    # Validate edges (dangling check)
    for i, edge in enumerate(edges):
        for req in ("from", "to", "relation"):
            if req not in edge:
                raise ValueError(f"Edge[{i}] missing required field: {req!r}")
        if str(edge["from"]) not in alias_map:
            raise ValueError(f"Edge[{i}] dangling 'from': {edge['from']!r}")
        if str(edge["to"]) not in alias_map:
            raise ValueError(f"Edge[{i}] dangling 'to': {edge['to']!r}")

    lines: list[str] = []

    # GRAPH header
    name = str(meta.get("name", ""))
    domain = str(meta.get("domain", ""))
    short_id = str(meta.get("id", ""))[:8]
    lines.append(f"GRAPH:{name}|{domain}|{short_id}")

    # N lines
    for i, node in enumerate(nodes):
        alias = f"n{i}"
        label = str(node["label"])
        ntype = str(node["type"])
        arch = str(node["archetype"])
        line = f"N:{alias}={label}[{ntype}/{arch}]"

        desc = str(node.get("description", ""))
        if desc:
            line += f'"{desc}"'

        chain_link = node.get("chain_link")
        if chain_link is not None:
            line += f"@{chain_link}"

        confidence = float(node.get("confidence", NODE_DEFAULTS["confidence"]))
        if confidence != float(NODE_DEFAULTS["confidence"]):
            line += f"~{confidence}"

        tags: list[str] = list(node.get("tags", []))
        if tags:
            line += "{" + ",".join(tags) + "}"

        if bool(node.get("flagged", False)):
            line += "!"

        if bool(node.get("deprecated", False)):
            line += "~dep"

        lines.append(line)

    # E lines
    for edge in edges:
        from_alias = alias_map[str(edge["from"])]
        to_alias = alias_map[str(edge["to"])]
        relation = str(edge["relation"])
        line = f"E:{from_alias}->{to_alias} {relation}"

        weight = float(edge.get("weight", EDGE_DEFAULTS["weight"]))
        econf = float(edge.get("confidence", EDGE_DEFAULTS["confidence"]))
        if weight != float(EDGE_DEFAULTS["weight"]) or econf != float(EDGE_DEFAULTS["confidence"]):
            line += f",{weight},{econf}"

        lines.append(line)

    result = "\n".join(lines)
    log.debug("compress: output %d chars", len(result))
    log.debug("compress output:\n%s", result)
    return result


def restore(ccf: str) -> dict[str, Any]:
    """Restore a CCF v1 string to a causal.json dict.

    Generates fresh UUIDs for all nodes and edges.
    Raises ValueError on malformed input or unknown aliases.
    """
    log.debug("restore: input %d chars", len(ccf))
    log.debug("restore input:\n%s", ccf)
    lines = [ln.strip() for ln in ccf.strip().splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("GRAPH:"):
        raise ValueError("CCF must start with a GRAPH: line")

    # Parse GRAPH header
    header = lines[0][6:]
    parts = header.split("|", 2)
    name = parts[0] if len(parts) > 0 else ""
    domain = parts[1] if len(parts) > 1 else ""

    alias_to_id: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for line in lines[1:]:
        if line.startswith("N:"):
            node = _parse_node_line(line, alias_to_id)
            nodes.append(node)
        elif line.startswith("E:"):
            edge = _parse_edge_line(line, alias_to_id)
            edges.append(edge)
        else:
            raise ValueError(f"Unknown line prefix: {line[:30]!r}")

    ts = _now()

    history: list[dict[str, Any]] = []
    for node in nodes:
        history.append({
            "timestamp": ts,
            "action": "node_add",
            "actor": "user",
            "payload": {"node_id": node["id"]},
        })
    for edge in edges:
        history.append({
            "timestamp": ts,
            "action": "edge_add",
            "actor": "user",
            "payload": {"edge_id": edge["id"]},
        })

    return {
        "meta": {
            "id": _fresh_id(),
            "name": name,
            "domain": domain,
            "created_at": ts,
            "updated_at": ts,
            "version": int(META_DEFAULTS["version"]),
            "author": str(META_DEFAULTS["author"]),
            "description": str(META_DEFAULTS["description"]),
        },
        "nodes": nodes,
        "edges": edges,
        "history": history,
        "summaries": list(META_DEFAULTS["summaries"]),
    }


def compress_file(path: Path) -> str:
    """Load a .causal.json file and return its CCF v1 string."""
    log.debug("compress_file: %s", path)
    return compress(json.loads(path.read_text(encoding="utf-8")))


def restore_file(path: Path) -> dict[str, Any]:
    """Load a .ccf file and return the restored causal.json dict."""
    log.debug("restore_file: %s", path)
    return restore(path.read_text(encoding="utf-8"))


def to_prompt(graph: dict[str, Any], task: str) -> str:
    """Return a Claude-ready prompt with the graph embedded as CCF v1."""
    ccf = compress(graph)
    prompt = f"[GRAPH CCF v1]\n{ccf}\n[/GRAPH]\n\n{task}"
    log.debug("to_prompt: task=%r  prompt_chars=%d", task[:60], len(prompt))
    log.debug("to_prompt output:\n%s", prompt)
    return prompt
