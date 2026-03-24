import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from note.schema import NoteInput, ARCHETYPES, NOTE_TYPES
from note.parser import parse_note, w_score


# ── Schema tests ──────────────────────────────────────────────────────────

def test_note_input_defaults():
    n = NoteInput(text="hello")
    assert n.type == "observation"
    assert n.confidence == 0.5
    assert n.urgency == 0.3
    assert n.seed_entities == []

def test_archetype_constants():
    assert "root_cause" in ARCHETYPES
    assert "mechanism" in ARCHETYPES
    assert "effect" in ARCHETYPES
    assert "moderator" in ARCHETYPES
    assert "evidence" in ARCHETYPES
    assert "question" in ARCHETYPES

def test_note_types_set():
    assert "hypothesis" in NOTE_TYPES
    assert "observation" in NOTE_TYPES


# ── W-score tests ─────────────────────────────────────────────────────────

def test_w_score_formula():
    n = NoteInput(text="x", confidence=1.0, urgency=1.0)
    assert w_score(n) == 1.0

def test_w_score_zero():
    n = NoteInput(text="x", confidence=0.0, urgency=0.0)
    assert w_score(n) == 0.0

def test_w_score_weighted():
    n = NoteInput(text="x", confidence=0.6, urgency=0.5)
    expected = round(0.6 * 0.6 + 0.5 * 0.4, 3)
    assert w_score(n) == expected


# ── Parser: plain text fallback ───────────────────────────────────────────

def test_parse_plain_text():
    note = parse_note("My cold swim improves focus.")
    assert note.text == "My cold swim improves focus."
    assert note.type == "observation"
    assert note.seed_entities == []
    assert note.confidence == 0.5
    assert note.urgency == 0.3

def test_parse_empty():
    note = parse_note("")
    assert note.text == ""
    assert note.type == "observation"


# ── Parser: YAML front matter (--- fences) ────────────────────────────────

YAML_FENCED = """---
type: hypothesis
seed_entities:
  - morning_routine
  - focus_quality
confidence: 0.6
urgency: 0.3
---
I think my focus is worse on days I skip the cold swim.
"""

def test_parse_yaml_fenced_type():
    note = parse_note(YAML_FENCED)
    assert note.type == "hypothesis"

def test_parse_yaml_fenced_seeds():
    note = parse_note(YAML_FENCED)
    assert "morning_routine" in note.seed_entities
    assert "focus_quality" in note.seed_entities

def test_parse_yaml_fenced_confidence():
    note = parse_note(YAML_FENCED)
    assert note.confidence == 0.6

def test_parse_yaml_fenced_text():
    note = parse_note(YAML_FENCED)
    assert "cold swim" in note.text


# ── Parser: ```yaml code block ────────────────────────────────────────────

YAML_BLOCK = """```yaml
type: observation
confidence: 0.8
urgency: 0.5
```
Sleep deprivation causes cognitive fatigue.
"""

def test_parse_yaml_block():
    note = parse_note(YAML_BLOCK)
    assert note.type == "observation"
    assert note.confidence == 0.8
    assert note.urgency == 0.5
    assert "cognitive fatigue" in note.text


# ── Parser: unknown type falls back to observation ────────────────────────

def test_parse_unknown_type():
    raw = "---\ntype: rant\n---\nI hate Mondays."
    note = parse_note(raw)
    assert note.type == "observation"


# ── Parser: missing fields use defaults ───────────────────────────────────

def test_parse_partial_yaml():
    raw = "---\ntype: decision\n---\nWe chose option B."
    note = parse_note(raw)
    assert note.type == "decision"
    assert note.confidence == 0.5
    assert note.urgency == 0.3

def test_parse_confidence_clamped():
    raw = "---\nconfidence: 1.5\n---\nOver-confident claim."
    note = parse_note(raw)
    assert note.confidence == 1.0
