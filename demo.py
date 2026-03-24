#!/usr/bin/env python3
"""
demo.py — Interactive manual test harness for the Causal Adaptive Ingestion pipeline.

Usage:
    python3 demo.py                  # interactive menu
    python3 demo.py --chain <file> --note <file>   # non-interactive
    python3 demo.py --chain <file> --note -        # read note from stdin
"""
import argparse
import json
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(__file__))

# ── ANSI colours (auto-disabled when not a tty) ───────────────────────────

_USE_COLOUR = sys.stdout.isatty()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

def bold(t):    return _c("1", t)
def dim(t):     return _c("2", t)
def green(t):   return _c("32", t)
def yellow(t):  return _c("33", t)
def red(t):     return _c("31", t)
def cyan(t):    return _c("36", t)
def magenta(t): return _c("35", t)
def blue(t):    return _c("34", t)

# ── Predefined notes ──────────────────────────────────────────────────────

PREDEFINED_NOTES = {
    "cold_swim": {
        "title": "Cold swim → focus observation",
        "domain": "health",
        "text": """\
---
type: observation
confidence: 0.75
urgency: 0.5
seed_entities:
  - cold swim
  - focus
  - cortisol
---
I've noticed that on days I do a 3-minute cold swim in the morning, my focus is
noticeably sharper for the first 3 hours. This might be because cold exposure
acutely lowers cortisol and triggers a norepinephrine spike that primes
attention circuits.
""",
    },
    "caffeine_loop": {
        "title": "Caffeine-sleep feedback loop hypothesis",
        "domain": "health",
        "text": """\
---
type: hypothesis
confidence: 0.6
urgency: 0.4
seed_entities:
  - Poor sleep quality
  - Reduced focus
---
High caffeine intake late in the day (after 2pm) worsens sleep quality the
following night, creating a feedback loop where poor focus leads to more
caffeine consumption which further degrades sleep. This loop may be broken by
enforcing a caffeine cutoff time.
""",
    },
    "deadline_stress": {
        "title": "Deadline stress → sleep fragmentation (plain text)",
        "domain": "health",
        "text": (
            "Stress from deadlines appears to cause sleep fragmentation even when "
            "total hours look adequate. The perceived urgency keeps the nervous system "
            "activated at bedtime."
        ),
    },
    "custom": {
        "title": "[ Enter your own note ]",
        "domain": None,
        "text": None,
    },
}

# ── Predefined chains ─────────────────────────────────────────────────────

def _discover_chains():
    chains_dir = os.path.join(os.path.dirname(__file__), "chains")
    result = {}
    if os.path.isdir(chains_dir):
        for fname in sorted(os.listdir(chains_dir)):
            if fname.endswith(".causal.json"):
                path = os.path.join(chains_dir, fname)
                try:
                    with open(path) as f:
                        meta = json.load(f).get("meta", {})
                    name = meta.get("name", fname)
                    domain = meta.get("domain", "")
                    nodes = len(json.load(open(path)).get("nodes", []))
                except Exception:
                    name, domain, nodes = fname, "", 0
                # reload properly
                try:
                    data = json.load(open(path))
                    nodes = sum(1 for n in data.get("nodes", []) if not n.get("deprecated"))
                    edges = sum(1 for e in data.get("edges", []) if not e.get("deprecated"))
                    name = data.get("meta", {}).get("name", fname)
                    domain = data.get("meta", {}).get("domain", "")
                except Exception:
                    edges = 0
                result[fname] = {"path": path, "name": name, "domain": domain,
                                 "nodes": nodes, "edges": edges}
    return result

# ── Render helpers ────────────────────────────────────────────────────────

def _rule(char="─", width=70):
    print(dim(char * width))

def _header(title):
    print()
    _rule("═")
    print(bold(f"  {title}"))
    _rule("═")

def _section(title):
    print()
    _rule()
    print(bold(f"  {title}"))
    _rule()

def _wscore_str(ws):
    ws = round(ws, 2)
    label = "high" if ws >= 0.7 else "medium" if ws >= 0.4 else "low"
    colour = green if ws >= 0.7 else yellow if ws >= 0.4 else red
    return colour(f"{ws:.2f}") + dim(f"  ({label} priority)")

def _render_parse(note):
    from note.parser import w_score
    ws = w_score(note)
    print(f"  {bold('type')}:          {cyan(note.type)}")
    print(f"  {bold('confidence')}:    {note.confidence:.2f}  |  "
          f"{bold('urgency')}: {note.urgency:.2f}")
    print(f"  {bold('W-score')}:       {_wscore_str(ws)}")
    seeds = ", ".join(note.seed_entities) if note.seed_entities else dim("(none)")
    print(f"  {bold('seed entities')}: {seeds}")
    preview = note.text[:160].replace("\n", " ")
    if len(note.text) > 160:
        preview += "…"
    print(f"  {bold('text')}:          {dim(preview)}")
    return ws

def _render_classification(result):
    role = result.get("structural_role", "?")
    reasoning = result.get("reasoning", "")
    known = result.get("known", [])
    delta = result.get("delta", [])

    print(f"  {bold('Structural role')}: {magenta(role)}")
    if reasoning:
        wrapped = textwrap.fill(reasoning, width=66, initial_indent="  ", subsequent_indent="  ")
        print(dim(wrapped))
    print()
    print(f"  {bold(f'KNOWN  ({len(known)})')}  — already in graph:")
    if known:
        for k in known:
            sim = k.get("similarity", "?")
            sim_str = f"{sim:.2f}" if isinstance(sim, float) else str(sim)
            print(f"    {green('✓')}  [{k.get('node_id', '?')[:8]}]  {k.get('entity', '?')}  "
                  f"{dim(f'similarity={sim_str}')}")
    else:
        print(f"    {dim('(no known entities matched)')}")

    print()
    print(f"  {bold(f'ΔDATA  ({len(delta)})')}  — new to graph:")
    if delta:
        for d in delta:
            stype = d.get('suggested_type', 'state')
            print(f"    {yellow('+')}  {d.get('entity', '?')}  {dim(f'({stype})')}")
            if d.get("description"):
                desc = textwrap.fill(d["description"], width=62,
                                     initial_indent="       ", subsequent_indent="       ")
                print(dim(desc))
    else:
        print(f"    {dim('(all entities already represented in graph)')}")

def _render_suggestions(suggestions, ws):
    nodes = [s for s in suggestions if s["kind"] == "import_node"]
    edges = [s for s in suggestions if s["kind"] == "import_edge"]

    if nodes:
        print(f"\n  {bold(f'Proposed nodes  ({len(nodes)})')}:")
        for i, s in enumerate(nodes, 1):
            arch = s.get("archetype", "?")
            arch_col = {
                "root_cause": red, "mechanism": yellow, "effect": blue,
                "moderator": cyan, "evidence": green, "question": magenta,
            }.get(arch, dim)
            print(f"    [{i:2}] {arch_col(f'[{arch}]'):20}  {bold(s['label'])}")
            if s.get("description"):
                desc = textwrap.fill(s["description"], width=60,
                                     initial_indent="         ", subsequent_indent="         ")
                print(dim(desc))

    if edges:
        print(f"\n  {bold(f'Proposed edges  ({len(edges)})')}:")
        for i, s in enumerate(edges, len(nodes) + 1):
            rel = s.get("relation", "CAUSES")
            w = s.get("weight", ws)
            print(f"    [{i:2}]  {s.get('connects_from_label', '?')}  "
                  f"{cyan(f'─{rel}→')}  {s.get('connects_to_label', '?')}  "
                  f"{dim(f'w={w:.2f}')}")

# ── Interactive menu helpers ───────────────────────────────────────────────

def _pick(prompt, options: dict, allow_back=True):
    """Print numbered menu, return selected key."""
    keys = list(options.keys())
    for i, k in enumerate(keys, 1):
        print(f"  {dim(str(i))}.  {options[k]}")
    if allow_back:
        print(f"  {dim('0')}.  {dim('(back)')}")
    while True:
        try:
            raw = input(f"\n  {prompt} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if raw == "0" and allow_back:
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print(dim("  Invalid choice."))

def _get_note_text(key):
    entry = PREDEFINED_NOTES[key]
    if entry["text"] is not None:
        return entry["text"]
    # custom — open editor or multiline input
    print(dim("\n  Enter note text. Type END on a blank line to finish."))
    print(dim("  (You may include YAML front matter between --- fences)\n"))
    lines = []
    try:
        while True:
            line = input("  ")
            if line.strip() == "END":
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        print()
    return "\n".join(lines)

# ── Stage runners ──────────────────────────────────────────────────────────

def stage_parse(note_text):
    from note.parser import parse_note
    _section("Stage 0 — Parse note")
    note = parse_note(note_text)
    ws = _render_parse(note)
    return note, ws

def stage_classify(chain, note):
    from note.classifier import classify_note
    _section("Stage 1 — Classify (known vs. ΔDATA)")
    print(dim("  Calling Claude API…"), end="", flush=True)
    try:
        result = classify_note(chain, note)
        print(green("  done"))
        _render_classification(result)
        return result
    except Exception as exc:
        print(red(f"  FAILED: {exc}"))
        return None

def stage_evolve(chain, classification, note, ws):
    from note.evolution import evolve_graph
    _section("Stage 2 — Graph evolution (ΔDATA → nodes/edges)")
    if not classification or not classification.get("delta"):
        print(dim("  No ΔDATA — nothing to evolve."))
        return []
    print(dim("  Calling Claude API…"), end="", flush=True)
    try:
        suggestions = evolve_graph(chain, classification, note)
        print(green("  done"))
        if suggestions:
            _render_suggestions(suggestions, ws)
        else:
            print(dim("  No suggestions returned."))
        return suggestions
    except Exception as exc:
        print(red(f"  FAILED: {exc}"))
        return []

def stage_apply(chain, suggestions, chain_path, ws, dry_run):
    from chain.schema import Node, Edge
    from chain.io import backup, save
    from datetime import datetime

    _section("Stage 3 — Apply")

    if not suggestions:
        print(dim("  Nothing to apply."))
        return

    if dry_run:
        print(yellow("  DRY RUN — no changes written."))
        return

    total = len(suggestions)
    print(f"  {total} item(s) proposed.")
    print(f"\n  Options:  {bold('A')}ccept all   {bold('S')}elect   {bold('R')}eject all")
    try:
        choice = input("  > ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        print(); return

    if choice == "R":
        print(dim("  Rejected."))
        return

    if choice == "A":
        selected = list(range(total))
    elif choice == "S":
        raw = input("  Comma-separated numbers (e.g. 1,3,5): ").strip()
        try:
            selected = [int(x.strip()) - 1 for x in raw.split(",") if x.strip()]
            selected = [i for i in selected if 0 <= i < total]
        except ValueError:
            print(dim("  Invalid input — rejected."))
            return
    else:
        print(dim("  Unrecognised choice — rejected."))
        return

    if not selected:
        print(dim("  Nothing selected."))
        return

    bak = backup(chain_path)
    print(dim(f"  Backup: {bak}"))

    now = datetime.now().isoformat()
    label_to_id = {}
    existing_label_to_id = {n.label: n.id for n in chain.nodes if not n.deprecated}

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
        chain.history.append({"timestamp": now, "action": "node_add", "actor": "demo",
                               "payload": {"node_id": node.id, "label": node.label}})
        label_to_id[node.label] = node.id
        print(f"  {green('+')} node  {node.label}")

    for i in selected:
        s = suggestions[i]
        if s["kind"] != "import_edge":
            continue
        from_id = (label_to_id.get(s["connects_from_label"])
                   or existing_label_to_id.get(s["connects_from_label"])
                   or s.get("_from_ref", ""))
        to_id   = (label_to_id.get(s["connects_to_label"])
                   or existing_label_to_id.get(s["connects_to_label"])
                   or s.get("_to_ref", ""))
        if not from_id or not to_id:
            print(f"  {yellow('~')} skipped edge (unresolved): {s['label']}")
            continue
        edge = Edge(from_id=from_id, to_id=to_id,
                    relation=s.get("relation", "CAUSES"),
                    weight=s.get("weight", ws),
                    confidence=ws, source="llm")
        chain.edges.append(edge)
        chain.history.append({"timestamp": now, "action": "edge_add", "actor": "demo",
                               "payload": {"edge_id": edge.id}})
        print(f"  {green('+')} edge  {s.get('connects_from_label','?')} → {s.get('connects_to_label','?')}")

    save(chain, chain_path)
    print(green(f"\n  Saved {chain_path}"))

# ── Main interactive flow ──────────────────────────────────────────────────

def run_interactive(dry_run=False):
    from chain.io import load

    _header("Causal Ingestion Pipeline — Demo Harness")

    # 1. Pick chain
    chains = _discover_chains()
    if not chains:
        print(red("  No .causal.json files found in chains/"))
        sys.exit(1)

    _section("Select chain")
    chain_menu = {k: "{name}  {info}".format(
                      name=v['name'],
                      info=dim(f"({v['nodes']}n / {v['edges']}e | {v['domain']})"))
                  for k, v in chains.items()}
    chain_key = _pick("Chain", chain_menu, allow_back=False)
    if chain_key is None:
        return
    chain_path = chains[chain_key]["path"]
    chain = load(chain_path)
    active_nodes = [n for n in chain.nodes if not n.deprecated]
    print(f"\n  Loaded: {bold(chain.meta.name)}  "
          f"{dim(f'({len(active_nodes)} active nodes)')}")

    # 2. Pick note
    _section("Select note")
    note_menu = {k: v["title"] for k, v in PREDEFINED_NOTES.items()}
    note_key = _pick("Note", note_menu, allow_back=False)
    if note_key is None:
        return
    note_text = _get_note_text(note_key)
    if not note_text.strip():
        print(red("  Empty note — aborting."))
        return

    # 3. Run pipeline
    note, ws = stage_parse(note_text)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(yellow("\n  ANTHROPIC_API_KEY not set — skipping Stages 1-3 (LLM calls)."))
        print(dim("  Set the key in .env to run the full pipeline."))
        return

    classification = stage_classify(chain, note)
    suggestions = stage_evolve(chain, classification, note, ws)
    stage_apply(chain, suggestions, chain_path, ws, dry_run)

    _header("Done")

def run_non_interactive(chain_path, note_arg, dry_run=False):
    from chain.io import load
    from note.parser import parse_note

    if note_arg == "-":
        note_text = sys.stdin.read()
    else:
        with open(note_arg) as f:
            note_text = f.read()

    chain = load(chain_path)
    print(f"\n  Chain: {chain.meta.name}  ({len([n for n in chain.nodes if not n.deprecated])} active nodes)")

    note, ws = stage_parse(note_text)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(yellow("\n  ANTHROPIC_API_KEY not set — parse-only mode."))
        return

    classification = stage_classify(chain, note)
    suggestions = stage_evolve(chain, classification, note, ws)
    stage_apply(chain, suggestions, chain_path, ws, dry_run)

# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Interactive demo harness for the Causal Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
          Examples:
            python3 demo.py                                         # interactive
            python3 demo.py --chain chains/sleep-cognition.causal.json --note notes/note_cold_swim.yaml
            python3 demo.py --chain chains/sleep-cognition.causal.json --note - --dry-run
        """),
    )
    p.add_argument("--chain", help="Path to .causal.json chain file")
    p.add_argument("--note",  help="Path to note file, or - for stdin")
    p.add_argument("--dry-run", action="store_true",
                   help="Run all stages but skip writing to the chain file")
    args = p.parse_args()

    # Load .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    if args.chain and args.note:
        run_non_interactive(args.chain, args.note, dry_run=args.dry_run)
    elif args.chain or args.note:
        p.error("Provide both --chain and --note, or neither for interactive mode.")
    else:
        run_interactive(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
