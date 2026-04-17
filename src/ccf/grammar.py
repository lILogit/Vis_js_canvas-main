"""CCF v1 grammar constants — valid enum values for node types, archetypes, and edge relations."""

VALID_TYPES: frozenset[str] = frozenset({
    "state", "event", "decision", "concept", "question",
    "blackbox", "goal", "task", "asset", "gate",
})

# Union of spec archetypes + project-specific values
VALID_ARCHETYPES: frozenset[str] = frozenset({
    "root_cause", "mechanism", "effect", "question",
    "amplifier", "inhibitor", "mediator", "moderator",
    "confounder", "proxy", "evidence",
})

# Project-specific edge relations (causal-editor schema)
VALID_RELATIONS: frozenset[str] = frozenset({
    "CAUSES", "ENABLES", "BLOCKS", "TRIGGERS", "REDUCES",
    "REQUIRES", "AMPLIFIES", "PRECONDITION_OF", "RESOLVES",
    "FRAMES", "INSTANTIATES", "DIVERGES_TO",
})
