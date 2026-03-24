"""
note/ingest.py — Full ingestion pipeline orchestrator.

Pipeline: parse → classify → evolve → return suggestions + metadata
"""
from chain.schema import CausalChain
from note.parser import parse_note, w_score
from note.classifier import classify_note
from note.evolution import evolve_graph


def ingest_note(chain: CausalChain, note_text: str) -> dict:
    """
    Full pipeline: parse note text → classify against chain → generate suggestions.

    Returns:
      {
        "note": NoteInput as dict,
        "w_score": float,
        "classification": {known, delta, structural_role, reasoning, seed_nodes},
        "suggestions": [...],  # import_node / import_edge format
      }
    """
    note = parse_note(note_text)
    classification = classify_note(chain, note)
    suggestions = evolve_graph(chain, classification, note)

    return {
        "note": {
            "type": note.type,
            "text": note.text,
            "seed_entities": note.seed_entities,
            "confidence": note.confidence,
            "urgency": note.urgency,
        },
        "w_score": w_score(note),
        "classification": classification,
        "suggestions": suggestions,
    }
