#!/usr/bin/env python3
"""
cli.py — Causal Editor entry point
Usage: python cli.py <command> [args] [flags]
"""
import argparse
import json
import os
import sys
from datetime import datetime

# Ensure local packages are importable when run from project root
sys.path.insert(0, os.path.dirname(__file__))


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()


_load_dotenv()


# ── Helpers ───────────────────────────────────────────────────────────────

def _load(path: str):
    from chain.io import load
    if not os.path.exists(path):
        print(f"  Error: file not found: {path}")
        sys.exit(1)
    return load(path)


def _save(chain, path: str):
    from chain.io import save
    save(chain, path)


def _print_issues(issues: list):
    if not issues:
        print("  All checks passed.")
        return
    for iss in issues:
        icon = "✗" if iss["severity"] == "error" else "⚠"
        print(f"  {icon} [{iss['check']}] {iss['element_id']}: {iss['message']}")


def _confirm_changes(items: list, item_label: str) -> list:
    """Print numbered list of proposed changes. Return selected indices."""
    for i, item in enumerate(items, 1):
        print(f"\n  [{i}] {item_label(item)}")
    print()
    choice = input("  Apply changes? [A]ccept all  [S]elect  [R]eject all  [E]dit > ").strip().upper()
    if choice == "R":
        return []
    if choice == "A" or choice == "E":
        return list(range(len(items)))
    # Select
    raw = input("  Select (comma-separated numbers, or 'all'): ").strip()
    if raw.lower() == "all":
        return list(range(len(items)))
    try:
        return [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
    except ValueError:
        return []


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_new(args):
    from chain.schema import CausalChain, ChainMeta
    from chain.io import save

    name = args.name
    domain = args.domain or "custom"
    path = args.file or os.path.join("chains", name.lower().replace(" ", "-") + ".causal.json")

    chain = CausalChain(meta=ChainMeta(name=name, domain=domain))
    save(chain, path)
    print(f"  Created: {path}")

    if not args.no_editor:
        from editor.serve import start
        print(f"  Opening editor at http://localhost:{args.port}")
        start(path, port=args.port, open_browser=True)


def cmd_open(args):
    from editor.serve import start
    chain = _load(args.file)
    active_nodes = len([n for n in chain.nodes if not n.deprecated])
    active_edges = len([e for e in chain.edges if not e.deprecated])
    print(f"\n  Opening editor at http://localhost:{args.port}")
    print(f"  Chain: {chain.meta.name}  |  {active_nodes} nodes  |  {active_edges} edges")
    print(f"\n  Editor open in browser. Press Ctrl+C to quit.\n")
    start(args.file, port=args.port, open_browser=not args.no_browser, host=args.host)


def cmd_list(args):
    from chain.io import load
    directory = args.dir or "chains"
    if not os.path.isdir(directory):
        print(f"  Directory not found: {directory}")
        return
    files = [f for f in os.listdir(directory) if f.endswith(".causal.json")]
    if not files:
        print("  No chains found.")
        return
    print(f"\n  {'FILE':<40} {'NODES':>6} {'EDGES':>6}  UPDATED")
    print("  " + "-" * 72)
    for fname in sorted(files):
        path = os.path.join(directory, fname)
        try:
            c = load(path)
            nodes = len([n for n in c.nodes if not n.deprecated])
            edges = len([e for e in c.edges if not e.deprecated])
            updated = c.meta.updated_at[:16].replace("T", " ")
            print(f"  {fname:<40} {nodes:>6} {edges:>6}  {updated}")
        except Exception as exc:
            print(f"  {fname:<40} [error: {exc}]")


def cmd_info(args):
    from chain.validate import validate, check_cycles
    chain = _load(args.file)
    nodes = [n for n in chain.nodes if not n.deprecated]
    edges = [e for e in chain.edges if not e.deprecated]
    cycles = check_cycles(chain)
    issues = validate(chain)
    orphan_nodes = [i for i in issues if i["check"] == "orphan_node"]

    # Degree count
    from collections import Counter
    degree = Counter()
    for e in edges:
        degree[e.from_id] += 1
        degree[e.to_id] += 1
    top = degree.most_common(3)
    node_map = {n.id: n.label for n in nodes}

    print(f"\n  Chain:   {chain.meta.name}")
    print(f"  Domain:  {chain.meta.domain}")
    print(f"  Nodes:   {len(nodes)}  |  Edges: {len(edges)}")
    print(f"  Orphans: {len(orphan_nodes)}  |  Cycles: {len(cycles)}")
    print(f"  Updated: {chain.meta.updated_at[:16].replace('T', ' ')}")
    if top:
        print(f"  Top nodes: " + ", ".join(f"{node_map.get(nid, nid)} ({d})" for nid, d in top))
    print()


def cmd_validate(args):
    from chain.validate import validate, check_cycles
    chain = _load(args.file)
    issues = validate(chain)
    cycles = check_cycles(chain)
    print(f"\n  Validating: {args.file}")
    _print_issues(issues)
    if cycles:
        print(f"\n  Cycles found: {len(cycles)}")
        for cyc in cycles:
            print(f"    {' → '.join(cyc)}")
    if not issues and not cycles:
        print("  Chain is valid.")
    print()


def cmd_add_node(args):
    from chain.schema import Node
    from datetime import datetime
    chain = _load(args.file)
    node = Node(
        label=args.label,
        type=args.type or "state",
        description=args.description or "",
        source="user",
    )
    chain.nodes.append(node)
    chain.history.append({
        "timestamp": datetime.now().isoformat(),
        "action": "node_add",
        "actor": "cli",
        "payload": {"node_id": node.id, "label": node.label},
    })
    _save(chain, args.file)
    print(f"  Added node: {node.id} — {node.label}")


def cmd_add_edge(args):
    from chain.schema import Edge
    chain = _load(args.file)
    node_ids = {n.id for n in chain.nodes if not n.deprecated}
    if args.from_id not in node_ids:
        print(f"  Error: from node {args.from_id!r} not found")
        sys.exit(1)
    if args.to_id not in node_ids:
        print(f"  Error: to node {args.to_id!r} not found")
        sys.exit(1)
    edge = Edge(
        from_id=args.from_id,
        to_id=args.to_id,
        relation=args.relation or "CAUSES",
        weight=args.weight or 0.5,
        source="user",
    )
    chain.edges.append(edge)
    chain.history.append({
        "timestamp": datetime.now().isoformat(),
        "action": "edge_add",
        "actor": "cli",
        "payload": {"edge_id": edge.id},
    })
    _save(chain, args.file)
    print(f"  Added edge: {edge.id} — {args.from_id} -{edge.relation}→ {args.to_id}")


def cmd_remove(args):
    chain = _load(args.file)
    element_id = args.id
    found = False
    for node in chain.nodes:
        if node.id == element_id:
            node.deprecated = True
            found = True
    for edge in chain.edges:
        if edge.id == element_id:
            edge.deprecated = True
            found = True
    if not found:
        print(f"  Error: id {element_id!r} not found")
        sys.exit(1)
    chain.history.append({
        "timestamp": datetime.now().isoformat(),
        "action": "node_edit",
        "actor": "cli",
        "payload": {"id": element_id, "deprecated": True},
    })
    _save(chain, args.file)
    print(f"  Soft-deleted: {element_id}")


def cmd_enrich(args):
    from chain.io import backup, to_dict
    import json as _json
    chain = _load(args.file)

    # Backup before enrichment
    bak = backup(args.file)
    print(f"\n  Backup saved: {bak}")
    print(f"  Analyzing chain... ", end="", flush=True)

    mode = args.mode or "full"

    if mode in ("full", "gaps"):
        from llm.enrichment import enrich_gaps, apply_gaps
        try:
            gaps = enrich_gaps(chain, n=5)
            print(f"done\n\n  Found {len(gaps)} gaps:\n")

            def gap_label(g):
                mn = g.get("missing_node", {})
                return (f"MISSING INTERMEDIARY between {g['between_from']!r} → {g['between_to']!r}\n"
                        f"      Proposed: {mn.get('label')!r}  (type: {mn.get('type')})\n"
                        f"      Reasoning: {g.get('reasoning')}")

            if gaps:
                selected = _confirm_changes(gaps, gap_label)
                count = apply_gaps(chain, gaps, selected)
                _save(chain, args.file)
                print(f"\n  Applied {count} gap(s). Chain saved.")
            else:
                print("  No gaps found.")
        except Exception as exc:
            print(f"failed\n  Error: {exc}")

    if mode in ("full", "weights"):
        from llm.enrichment import enrich_weights, apply_weight_adjustments
        try:
            adjustments = enrich_weights(chain)
            print(f"\n  Found {len(adjustments)} weight adjustment(s).")
            if adjustments:
                def adj_label(a):
                    return f"Edge {a['edge_id']}: {a['current_weight']} → {a['suggested_weight']}  ({a['reasoning']})"
                selected = _confirm_changes(adjustments, adj_label)
                count = apply_weight_adjustments(chain, adjustments, selected)
                _save(chain, args.file)
                print(f"  Applied {count} weight adjustment(s). Chain saved.")
        except Exception as exc:
            print(f"  Weight enrichment error: {exc}")


def cmd_explain(args):
    from chain.io import to_dict
    import json as _json
    chain = _load(args.file)
    from llm import client as llm_client
    from llm.prompts import EXPLAIN_CHAIN, EXPLAIN_NODE

    chain_json = _json.dumps(to_dict(chain), indent=2)
    lang = args.lang or "en"

    if args.node:
        node = next((n for n in chain.nodes if n.id == args.node and not n.deprecated), None)
        if not node:
            print(f"  Node {args.node!r} not found")
            sys.exit(1)
        prompt = EXPLAIN_NODE.format(context_json=chain_json, node_label=node.label, lang=lang)
        result = llm_client.call(prompt)
        print(f"\n  {result.get('explanation', '')}\n")
    else:
        prompt = EXPLAIN_CHAIN.format(chain_json=chain_json, lang=lang)
        result = llm_client.call(prompt)
        print(f"\n  {result.get('explanation', '')}\n")


def cmd_ask(args):
    from chain.io import to_dict
    import json as _json
    chain = _load(args.file)
    from llm import client as llm_client
    from llm.prompts import ASK_CHAIN

    chain_json = _json.dumps(to_dict(chain), indent=2)
    prompt = ASK_CHAIN.format(chain_json=chain_json, question=args.question, lang="en")
    result = llm_client.call(prompt)
    print(f"\n  {result.get('answer', '')}\n")


def cmd_critique(args):
    from chain.io import to_dict
    import json as _json
    chain = _load(args.file)
    from llm import client as llm_client
    from llm.prompts import CRITIQUE_CHAIN

    chain_json = _json.dumps(to_dict(chain), indent=2)
    prompt = CRITIQUE_CHAIN.format(chain_json=chain_json)
    result = llm_client.call(prompt)
    issues = result.get("issues", [])
    if not issues:
        print("  No issues found.")
        return

    print(f"\n  Found {len(issues)} issue(s):\n")
    for i, iss in enumerate(issues, 1):
        print(f"  [{i}] {iss['severity'].upper()} — {iss['type']}")
        print(f"       {iss['description']}")
        print(f"       Fix: {iss['suggested_fix']}\n")


def cmd_export(args):
    from chain.io import to_dict
    import json as _json
    chain = _load(args.file)
    fmt = args.format or "json"
    out = args.output

    if fmt == "json":
        data = to_dict(chain)
        # Strip history and deprecated
        data["nodes"] = [n for n in data["nodes"] if not n.get("deprecated")]
        data["edges"] = [e for e in data["edges"] if not e.get("deprecated")]
        data.pop("history", None)
        content = _json.dumps(data, indent=2, ensure_ascii=False)
        ext = ".json"

    elif fmt == "mermaid":
        lines = ["flowchart TD"]
        for n in chain.nodes:
            if not n.deprecated:
                lines.append(f'    {n.id}["{n.label}"]')
        for e in chain.edges:
            if not e.deprecated:
                lines.append(f'    {e.from_id} -->|{e.relation}| {e.to_id}')
        content = "\n".join(lines)
        ext = ".md"

    elif fmt == "dot":
        lines = ["digraph causal {", "  rankdir=TB;"]
        for n in chain.nodes:
            if not n.deprecated:
                lines.append(f'  {n.id} [label="{n.label}"];')
        for e in chain.edges:
            if not e.deprecated:
                lines.append(f'  {e.from_id} -> {e.to_id} [label="{e.relation}"];')
        lines.append("}")
        content = "\n".join(lines)
        ext = ".dot"

    elif fmt == "markdown":
        lines = [f"# {chain.meta.name}\n"]
        lines.append("## Nodes\n")
        for n in chain.nodes:
            if not n.deprecated:
                lines.append(f"- **{n.label}** (`{n.type}`, conf={n.confidence}): {n.description}")
        lines.append("\n## Edges\n")
        for e in chain.edges:
            if not e.deprecated:
                from_node = next((n.label for n in chain.nodes if n.id == e.from_id), e.from_id)
                to_node = next((n.label for n in chain.nodes if n.id == e.to_id), e.to_id)
                lines.append(f"- {from_node} **{e.relation}** {to_node} (w={e.weight})")
        content = "\n".join(lines)
        ext = ".md"

    else:
        print(f"  Unknown format: {fmt}")
        sys.exit(1)

    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Exported to: {out}")
    else:
        print(content)


def cmd_history(args):
    chain = _load(args.file)
    entries = chain.history
    n = args.last or 20
    shown = entries[-n:]
    print(f"\n  Last {len(shown)} entries (of {len(entries)} total):\n")
    for entry in shown:
        ts = entry.get("timestamp", "")[:16].replace("T", " ")
        action = entry.get("action", "?")
        actor = entry.get("actor", "?")
        print(f"  {ts}  [{actor}] {action}")
    print()


def cmd_backup(args):
    from chain.io import backup
    dest = backup(args.file)
    print(f"  Backup saved: {dest}")


def cmd_diff(args):
    from chain.diff import diff
    chain_a = _load(args.file1)
    chain_b = _load(args.file2)
    d = diff(chain_a, chain_b)
    print(f"\n  Diff: {args.file1} vs {args.file2}\n")
    print(f"  Added nodes:   {len(d['added_nodes'])}")
    print(f"  Removed nodes: {len(d['removed_nodes'])}")
    print(f"  Added edges:   {len(d['added_edges'])}")
    print(f"  Removed edges: {len(d['removed_edges'])}")
    print(f"  Changed edges: {len(d['changed_edges'])}")
    for c in d["changed_edges"]:
        print(f"    Edge {c['edge_id']}: {c['changes']}")
    print()


def cmd_parse_note(args):
    """Phase 1: Parse note YAML front matter, show W-score."""
    import json as _json
    from note.parser import parse_note, w_score
    text = open(args.file).read() if args.file != "-" else sys.stdin.read()
    note = parse_note(text)
    ws = w_score(note)
    print(f"\n  Note parsed:")
    print(f"    type:          {note.type}")
    print(f"    confidence:    {note.confidence}")
    print(f"    urgency:       {note.urgency}")
    print(f"    W-score:       {ws}  ({'high' if ws >= 0.7 else 'medium' if ws >= 0.4 else 'low'} priority)")
    print(f"    seed_entities: {note.seed_entities or '(none)'}")
    print(f"    text:          {note.text[:120]}{'...' if len(note.text) > 120 else ''}")
    print()


def cmd_classify(args):
    """Phase 2: Classify note against chain — known vs. ΔDATA split."""
    from chain.io import backup
    from note.parser import parse_note, w_score
    from note.classifier import classify_note

    chain = _load(args.file)
    text = open(args.note).read() if args.note != "-" else sys.stdin.read()
    note = parse_note(text)
    ws = w_score(note)

    print(f"\n  W-score: {ws} ({'high' if ws >= 0.7 else 'medium' if ws >= 0.4 else 'low'} priority)")
    print(f"  Classifying against chain... ", end="", flush=True)
    try:
        result = classify_note(chain, note)
        print("done\n")
        print(f"  Structural role: {result['structural_role']}")
        print(f"  Reasoning: {result['reasoning']}\n")
        print(f"  KNOWN ({len(result['known'])}):")
        for k in result["known"]:
            print(f"    [{k.get('node_id', '?')}] {k.get('entity')}  (similarity: {k.get('similarity', '?')})")
        print(f"\n  ΔDATA — new to graph ({len(result['delta'])}):")
        for d in result["delta"]:
            print(f"    {d.get('entity')}  ({d.get('suggested_type', 'state')})  — {d.get('description', '')}")
        print()
    except Exception as exc:
        print(f"failed\n  Error: {exc}")


def cmd_ingest(args):
    """Phase 3: Full ingestion pipeline — parse → classify → evolve → apply."""
    from chain.io import backup
    from chain.schema import Node, Edge
    from note.parser import parse_note, w_score
    from note.ingest import ingest_note
    from datetime import datetime

    chain = _load(args.file)
    text = open(args.note).read() if args.note != "-" else sys.stdin.read()

    bak = backup(args.file)
    print(f"\n  Backup saved: {bak}")

    note = parse_note(text)
    ws = w_score(note)
    print(f"  W-score: {ws} ({'high' if ws >= 0.7 else 'medium' if ws >= 0.4 else 'low'} priority)")
    print(f"  Running ingestion pipeline... ", end="", flush=True)

    try:
        result = ingest_note(chain, text)
        suggestions = result["suggestions"]
        classification = result["classification"]
        print("done\n")

        print(f"  Structural role: {classification['structural_role']}")
        print(f"  Known entities: {len(classification['known'])} | ΔDATA: {len(classification['delta'])}\n")

        if not suggestions:
            print("  No new nodes or edges to add.")
            return

        # Show and confirm suggestions
        node_sug = [s for s in suggestions if s["kind"] == "import_node"]
        edge_sug = [s for s in suggestions if s["kind"] == "import_edge"]

        def sug_label(s):
            if s["kind"] == "import_node":
                return f"NODE  [{s.get('archetype', '?')}]  {s['label']}  — {s.get('description', '')}"
            return f"EDGE  {s['label']}  ({s.get('relation', 'CAUSES')}, w={s.get('weight', 0.5):.2f})"

        print(f"  Proposed additions ({len(suggestions)}):")
        selected = _confirm_changes(suggestions, sug_label)

        if not selected:
            print("  Nothing selected.")
            return

        now = datetime.now().isoformat()
        label_to_id = {}

        # Apply nodes first
        for i in selected:
            s = suggestions[i]
            if s["kind"] != "import_node":
                continue
            node = Node(
                label=s["label"],
                description=s.get("description", ""),
                type=s.get("node_type", "state"),
                archetype=s.get("archetype"),
                confidence=ws,
                source="llm",
            )
            chain.nodes.append(node)
            chain.history.append({"timestamp": now, "action": "node_add", "actor": "ingest",
                                   "payload": {"node_id": node.id, "label": node.label}})
            label_to_id[node.label] = node.id

        # Build label→id map for existing nodes as fallback
        existing_label_to_id = {n.label: n.id for n in chain.nodes if not n.deprecated}

        # Apply edges
        for i in selected:
            s = suggestions[i]
            if s["kind"] != "import_edge":
                continue
            # Resolve: 1) new node label, 2) existing node label, 3) raw node_id ref
            from_id = (label_to_id.get(s["connects_from_label"])
                       or existing_label_to_id.get(s["connects_from_label"])
                       or s.get("_from_ref", ""))
            to_id   = (label_to_id.get(s["connects_to_label"])
                       or existing_label_to_id.get(s["connects_to_label"])
                       or s.get("_to_ref", ""))
            if not from_id or not to_id:
                print(f"  Skipped edge (unresolved ref): {s['label']}")
                continue
            edge = Edge(
                from_id=from_id, to_id=to_id,
                relation=s.get("relation", "CAUSES"),
                weight=s.get("weight", ws),
                confidence=ws,
                source="llm",
                evidence=s.get("reasoning", ""),
            )
            chain.edges.append(edge)
            chain.history.append({"timestamp": now, "action": "edge_add", "actor": "ingest",
                                   "payload": {"edge_id": edge.id}})

        _save(chain, args.file)
        print(f"\n  Applied {len(selected)} item(s). Chain saved.")

    except Exception as exc:
        print(f"failed\n  Error: {exc}")


def cmd_forge(args):
    """Emit deterministic Python from a chain."""
    import chain.io as chain_io
    src_path = os.path.join(os.path.dirname(__file__), "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from forge.emit import forge_chain, ForgeError
    chain = _load(args.file)
    data  = chain_io.to_dict(chain)
    try:
        code = forge_chain(data)
    except ForgeError as exc:
        print(f"  Forge error: {exc}")
        sys.exit(1)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"  Forged: {args.out}")
    else:
        print(code)


def cmd_reset_demo(args):
    """Restore demo chain(s) to their pristine seed state."""
    import shutil
    chains_dir = os.path.join(os.path.dirname(__file__), "chains")
    seeds = [f for f in os.listdir(chains_dir) if f.endswith("-seed.causal.json")]
    if not seeds:
        print("  No seed files found (expected *-seed.causal.json in chains/).")
        return
    for seed_name in sorted(seeds):
        target_name = seed_name.replace("-seed.causal.json", ".causal.json")
        seed_path   = os.path.join(chains_dir, seed_name)
        target_path = os.path.join(chains_dir, target_name)
        # Backup current state first
        if os.path.exists(target_path):
            from chain.io import backup
            bak = backup(target_path)
            print(f"  Backed up {target_name} → {os.path.basename(bak)}")
        shutil.copy2(seed_path, target_path)
        print(f"  Reset {target_name} ← {seed_name}")
    print()


# ── Argument parser ───────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(prog="causal", description="Causal Editor CLI")
    sub = p.add_subparsers(dest="command")

    # new
    s = sub.add_parser("new", help="Create a new chain")
    s.add_argument("name")
    s.add_argument("--domain", default="custom")
    s.add_argument("--file")
    s.add_argument("--port", type=int, default=7331)
    s.add_argument("--no-editor", action="store_true")

    # open
    s = sub.add_parser("open", help="Open chain in browser editor")
    s.add_argument("file")
    s.add_argument("--port", type=int, default=7331)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--no-browser", action="store_true")

    # list
    s = sub.add_parser("list", help="List chains")
    s.add_argument("--dir", default="chains")

    # info
    s = sub.add_parser("info", help="Chain summary")
    s.add_argument("file")

    # validate
    s = sub.add_parser("validate", help="Validate chain structure")
    s.add_argument("file")

    # add-node
    s = sub.add_parser("add-node", help="Add a node")
    s.add_argument("file")
    s.add_argument("--label", required=True)
    s.add_argument("--type", default="state")
    s.add_argument("--description", default="")

    # add-edge
    s = sub.add_parser("add-edge", help="Add an edge")
    s.add_argument("file")
    s.add_argument("--from", dest="from_id", required=True)
    s.add_argument("--to", dest="to_id", required=True)
    s.add_argument("--relation", default="CAUSES")
    s.add_argument("--weight", type=float, default=0.5)

    # remove
    s = sub.add_parser("remove", help="Soft-delete a node or edge")
    s.add_argument("file")
    s.add_argument("--id", required=True)

    # enrich
    s = sub.add_parser("enrich", help="LLM enrichment pass")
    s.add_argument("file")
    s.add_argument("--mode", choices=["full", "gaps", "weights", "scope"], default="full")

    # explain
    s = sub.add_parser("explain", help="LLM explanation")
    s.add_argument("file")
    s.add_argument("--node")
    s.add_argument("--lang", default="en")

    # ask
    s = sub.add_parser("ask", help="Free-form question about chain")
    s.add_argument("file")
    s.add_argument("question")

    # critique
    s = sub.add_parser("critique", help="LLM chain critique")
    s.add_argument("file")

    # export
    s = sub.add_parser("export", help="Export chain")
    s.add_argument("file")
    s.add_argument("--format", choices=["json", "csv", "dot", "mermaid", "markdown"], default="json")
    s.add_argument("--output")

    # history
    s = sub.add_parser("history", help="Show action history")
    s.add_argument("file")
    s.add_argument("--last", type=int, default=20)

    # backup
    s = sub.add_parser("backup", help="Manual backup")
    s.add_argument("file")

    # diff
    s = sub.add_parser("diff", help="Diff two chains")
    s.add_argument("file1")
    s.add_argument("file2")

    # parse-note
    s = sub.add_parser("parse-note", help="Parse note YAML front matter, show W-score")
    s.add_argument("file", help="Note file path or - for stdin")

    # classify
    s = sub.add_parser("classify", help="Classify note against chain (known vs. ΔDATA)")
    s.add_argument("file", help="Chain .causal.json path")
    s.add_argument("note", help="Note file path or - for stdin")

    # ingest
    s = sub.add_parser("ingest", help="Full ingestion pipeline: parse → classify → evolve → apply")
    s.add_argument("file", help="Chain .causal.json path")
    s.add_argument("note", help="Note file path or - for stdin")

    # forge
    s = sub.add_parser("forge", help="Emit deterministic Python from a chain")
    s.add_argument("file", help="Chain .causal.json path")
    s.add_argument("--out", help="Output .py path (default: stdout)")

    # reset-demo
    sub.add_parser("reset-demo", help="Restore demo chains to pristine seed state")

    return p


COMMANDS = {
    "new": cmd_new,
    "open": cmd_open,
    "list": cmd_list,
    "info": cmd_info,
    "validate": cmd_validate,
    "add-node": cmd_add_node,
    "add-edge": cmd_add_edge,
    "remove": cmd_remove,
    "enrich": cmd_enrich,
    "explain": cmd_explain,
    "ask": cmd_ask,
    "critique": cmd_critique,
    "export": cmd_export,
    "history": cmd_history,
    "backup": cmd_backup,
    "diff": cmd_diff,
    "parse-note": cmd_parse_note,
    "classify": cmd_classify,
    "ingest": cmd_ingest,
    "forge": cmd_forge,
    "reset-demo": cmd_reset_demo,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    fn = COMMANDS.get(args.command)
    if not fn:
        print(f"Unknown command: {args.command}")
        sys.exit(1)
    fn(args)


if __name__ == "__main__":
    main()
