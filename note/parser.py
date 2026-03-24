"""
note/parser.py — parse YAML front matter + free text into NoteInput.

Supported formats:
  1. YAML code block:
       ```yaml
       type: hypothesis
       ...
       ```
       <free text>

  2. --- fences:
       ---
       type: hypothesis
       ...
       ---
       <free text>

  3. Plain text fallback: entire input becomes `text`, type defaults to "observation".
"""
import re
from note.schema import NoteInput, NOTE_TYPES


def _parse_simple_yaml(yaml_text: str) -> dict:
    """Parse flat key-value YAML (no nesting beyond simple lists) using stdlib only."""
    result = {}
    current_key = None
    list_items = []

    for line in yaml_text.splitlines():
        # Skip comments and empty lines
        if not line.strip() or line.strip().startswith("#"):
            continue

        # List item under current key
        if line.startswith("  - ") or line.startswith("- "):
            item = line.lstrip("- ").strip()
            # Remove inline quotes
            item = item.strip('"\'')
            if current_key:
                list_items.append(item)
            continue

        # Key: value
        if ":" in line:
            # Save previous list key if any
            if current_key and list_items:
                result[current_key] = list_items
                list_items = []

            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            # Strip inline quotes and YAML block scalars (> or |)
            value = value.lstrip(">|").strip().strip('"\'')

            current_key = key
            if value:
                result[key] = value
            # else: wait for list items or multi-line value

    # Flush any remaining list
    if current_key and list_items:
        result[current_key] = list_items

    return result


def _extract_yaml_and_text(raw: str):
    """Return (yaml_str, body_text) or (None, raw) if no front matter found."""

    # Format 1: ```yaml ... ``` block
    m = re.match(r"^\s*```yaml\s*\n(.*?)```\s*\n?(.*)", raw, re.DOTALL)
    if m:
        return m.group(1), m.group(2).strip()

    # Format 2: --- ... --- fences
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)", raw, re.DOTALL)
    if m:
        return m.group(1), m.group(2).strip()

    return None, raw.strip()


def parse_note(raw: str) -> NoteInput:
    """Parse raw note text into a NoteInput. Tolerant of missing fields."""
    yaml_str, body = _extract_yaml_and_text(raw)

    if yaml_str is None:
        # Plain text fallback
        return NoteInput(type="observation", text=body)

    data = _parse_simple_yaml(yaml_str)

    # Merge inline `text` field with body text
    inline_text = data.get("text", "")
    if isinstance(inline_text, str):
        inline_text = inline_text.strip()
    text = (inline_text + "\n" + body).strip() if inline_text else body

    # Parse seed_entities — can be list from YAML or comma-separated string
    seeds = data.get("seed_entities", [])
    if isinstance(seeds, str):
        seeds = [s.strip() for s in seeds.split(",") if s.strip()]

    # Parse numeric fields safely
    def _float(val, default):
        try:
            return max(0.0, min(1.0, float(val)))
        except (TypeError, ValueError):
            return default

    note_type = data.get("type", "observation").lower()
    if note_type not in NOTE_TYPES:
        note_type = "observation"

    return NoteInput(
        type=note_type,
        text=text,
        seed_entities=seeds,
        confidence=_float(data.get("confidence"), 0.5),
        urgency=_float(data.get("urgency"), 0.3),
    )


def w_score(note: NoteInput) -> float:
    """Compute priority W-score from confidence and urgency."""
    return round(note.confidence * 0.6 + note.urgency * 0.4, 3)
