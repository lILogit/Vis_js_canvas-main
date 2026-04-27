import json
import os
import shutil
from datetime import datetime

from chain.schema import CausalChain, ChainMeta, Node, Edge


def load(path: str) -> CausalChain:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta_data = data.get("meta", {})
    meta = ChainMeta(
        id=meta_data.get("id", ""),
        name=meta_data.get("name", "Untitled Chain"),
        domain=meta_data.get("domain", "custom"),
        created_at=meta_data.get("created_at", datetime.now().isoformat()),
        updated_at=meta_data.get("updated_at", datetime.now().isoformat()),
        version=meta_data.get("version", 1),
        author=meta_data.get("author", ""),
        description=meta_data.get("description", ""),
        scenario_overrides=meta_data.get("scenario_overrides", {}),
    )

    nodes = []
    for n in data.get("nodes", []):
        nodes.append(Node(
            id=n.get("id", ""),
            label=n.get("label", ""),
            description=n.get("description", ""),
            type=n.get("type", "state"),
            archetype=n.get("archetype"),
            tags=n.get("tags", []),
            confidence=n.get("confidence", 0.7),
            created_at=n.get("created_at", datetime.now().isoformat()),
            source=n.get("source", "user"),
            deprecated=n.get("deprecated", False),
            flagged=n.get("flagged", False),
            chain_link=n.get("chain_link", None),
            enrichment_status=n.get("_status"),
            evidence_ref=n.get("_evidence_ref"),
        ))

    edges = []
    for e in data.get("edges", []):
        edges.append(Edge(
            id=e.get("id", ""),
            from_id=e.get("from", ""),
            to_id=e.get("to", ""),
            relation=e.get("relation", "CAUSES"),
            weight=e.get("weight", 0.5),
            confidence=e.get("confidence", 0.5),
            direction=e.get("direction", "forward"),
            condition=e.get("condition"),
            evidence=e.get("evidence", ""),
            deprecated=e.get("deprecated", False),
            flagged=e.get("flagged", False),
            version=e.get("version", 1),
            created_at=e.get("created_at", datetime.now().isoformat()),
            source=e.get("source", "user"),
        ))

    return CausalChain(
        meta=meta, nodes=nodes, edges=edges,
        history=data.get("history", []),
        summaries=data.get("summaries", []),
        evidence=data.get("evidence", []),
        pending_review=data.get("pending_review", []),
    )


def from_dict(data: dict) -> "CausalChain":
    """Construct a CausalChain from a plain dict (same logic as load, without file I/O)."""
    import io as _io  # noqa: PLC0415
    import tempfile, json as _json  # noqa: PLC0415, E401
    # Reuse load() by round-tripping through a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False, encoding="utf-8") as tf:
        _json.dump(data, tf)
        tmp_path = tf.name
    try:
        return load(tmp_path)
    finally:
        import os as _os  # noqa: PLC0415
        _os.unlink(tmp_path)


def to_dict(chain: CausalChain) -> dict:
    nodes = []
    for n in chain.nodes:
        nd = {
            "id": n.id,
            "label": n.label,
            "description": n.description,
            "type": n.type,
            "archetype": n.archetype,
            "tags": n.tags,
            "confidence": n.confidence,
            "created_at": n.created_at,
            "source": n.source,
            "deprecated": n.deprecated,
            "flagged": n.flagged,
            "chain_link": n.chain_link,
        }
        if n.enrichment_status is not None:
            nd["_status"] = n.enrichment_status
        if n.evidence_ref is not None:
            nd["_evidence_ref"] = n.evidence_ref
        nodes.append(nd)

    edges = []
    for e in chain.edges:
        edges.append({
            "id": e.id,
            "from": e.from_id,
            "to": e.to_id,
            "relation": e.relation,
            "weight": e.weight,
            "confidence": e.confidence,
            "direction": e.direction,
            "condition": e.condition,
            "evidence": e.evidence,
            "deprecated": e.deprecated,
            "flagged": e.flagged,
            "version": e.version,
            "created_at": e.created_at,
            "source": e.source,
        })

    meta_dict = {
        "id": chain.meta.id,
        "name": chain.meta.name,
        "domain": chain.meta.domain,
        "created_at": chain.meta.created_at,
        "updated_at": chain.meta.updated_at,
        "version": chain.meta.version,
        "author": chain.meta.author,
        "description": chain.meta.description,
    }
    if chain.meta.scenario_overrides:
        meta_dict["scenario_overrides"] = chain.meta.scenario_overrides

    result = {
        "meta": meta_dict,
        "nodes": nodes,
        "edges": edges,
        "history": chain.history,
        "summaries": chain.summaries,
    }
    if chain.evidence:
        result["evidence"] = chain.evidence
    if chain.pending_review:
        result["pending_review"] = chain.pending_review
    return result


def save(chain: CausalChain, path: str) -> None:
    from chain.validate import validate

    issues = validate(chain)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        msgs = "; ".join(i["message"] for i in errors)
        raise ValueError(f"Validation errors prevented save: {msgs}")

    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")

    chain.meta.updated_at = datetime.now().isoformat()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_dict(chain), f, indent=2, ensure_ascii=False)


def backup(path: str, backup_dir: str = None) -> str:
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(backup_dir, f"{base}_{timestamp}.causal.json")
    shutil.copy2(path, dest)
    return dest
