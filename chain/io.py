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

    return CausalChain(meta=meta, nodes=nodes, edges=edges, history=data.get("history", []))


def to_dict(chain: CausalChain) -> dict:
    nodes = []
    for n in chain.nodes:
        nodes.append({
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
        })

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

    return {
        "meta": {
            "id": chain.meta.id,
            "name": chain.meta.name,
            "domain": chain.meta.domain,
            "created_at": chain.meta.created_at,
            "updated_at": chain.meta.updated_at,
            "version": chain.meta.version,
            "author": chain.meta.author,
            "description": chain.meta.description,
        },
        "nodes": nodes,
        "edges": edges,
        "history": chain.history,
    }


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
