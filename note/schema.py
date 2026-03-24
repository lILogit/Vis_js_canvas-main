from dataclasses import dataclass, field

# Structural archetype constants — the role a node plays in the causal graph
ROOT_CAUSE = "root_cause"    # originating factor with no significant precursors
MECHANISM  = "mechanism"     # intermediate node explaining how A causes B
EFFECT     = "effect"        # downstream outcome
MODERATOR  = "moderator"     # modulates strength or direction of an existing edge
EVIDENCE   = "evidence"      # factual support for an existing node or edge
QUESTION   = "question"      # unresolved gap or uncertainty

ARCHETYPES = {ROOT_CAUSE, MECHANISM, EFFECT, MODERATOR, EVIDENCE, QUESTION}

# Valid note types
NOTE_TYPES = {"hypothesis", "observation", "decision", "question", "evidence"}


@dataclass
class NoteInput:
    type: str = "observation"          # hypothesis|observation|decision|question|evidence
    text: str = ""                     # free-text body
    seed_entities: list = field(default_factory=list)  # labels or node IDs for context
    confidence: float = 0.5            # 0–1: user's certainty about the claim
    urgency: float = 0.3               # 0–1: how fast this should enter the graph
    # W-score = confidence * 0.6 + urgency * 0.4
