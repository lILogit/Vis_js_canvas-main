"""
note/classifier.py — Stage 1: Known/ΔDATA classifier.

Splits note content into:
  known  — entities already represented in the chain
  delta  — genuinely new entities not yet in the graph

Also determines the structural_role of the note relative to the graph.
"""
import json
import re

from chain.schema import CausalChain
from chain.io import to_dict
from note.schema import NoteInput
from note.parser import w_score
from llm import client
from llm.prompts import NOTE_CLASSIFY


def resolve_seed_entities(chain: CausalChain, note: NoteInput) -> list:
    """
    Return list of Node objects matching seed_entities labels/ids.
    If seed_entities is empty, extract capitalized noun phrases from text
    and match against node labels (case-insensitive).
    """
    active_nodes = [n for n in chain.nodes if not n.deprecated]

    if note.seed_entities:
        matched = []
        for seed in note.seed_entities:
            for node in active_nodes:
                if node.id == seed or node.label.lower() == seed.lower():
                    matched.append(node)
                    break
        return matched

    # Heuristic: extract capitalized words/phrases from text
    words = re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b', note.text)
    words += re.findall(r'\b[a-z_]+\b', note.text)  # also try snake_case
    words_lower = {w.lower() for w in words}

    return [n for n in active_nodes if n.label.lower() in words_lower]


def classify_note(chain: CausalChain, note: NoteInput) -> dict:
    """
    Call Claude to classify note concepts as known vs. ΔDATA.
    Returns: {known, delta, structural_role, reasoning, w_score, seed_nodes}
    """
    chain_data = to_dict(chain)
    # Only include non-deprecated nodes for context
    chain_data["nodes"] = [n for n in chain_data["nodes"] if not n.get("deprecated")]
    chain_data["edges"] = [e for e in chain_data["edges"] if not e.get("deprecated")]

    seed_nodes = resolve_seed_entities(chain, note)
    seed_labels = [n.label for n in seed_nodes] if seed_nodes else note.seed_entities

    prompt = NOTE_CLASSIFY.format(
        chain_json=json.dumps(chain_data, indent=2),
        note_type=note.type,
        note_text=note.text,
        seed_entities=", ".join(seed_labels) if seed_labels else "(none — infer from text)",
    )

    result = client.call(prompt, max_tokens=1500)

    return {
        "known": result.get("known", []),
        "delta": result.get("delta", []),
        "structural_role": result.get("structural_role", "mechanism"),
        "reasoning": result.get("reasoning", ""),
        "w_score": w_score(note),
        "seed_nodes": [{"id": n.id, "label": n.label} for n in seed_nodes],
    }
