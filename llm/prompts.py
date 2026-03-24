SYSTEM_BASE = """You are a causal graph analyst. You reason about causal relationships \
between states, events, decisions, goals, tasks, assets, and gates. \
You think in directed graphs: nodes are causal primitives, edges are typed causal links \
with direction and weight. \
Node types: state|event|decision|concept|question|blackbox|goal|task|asset|gate. \
Edge relations: CAUSES|ENABLES|BLOCKS|TRIGGERS|REDUCES|REQUIRES|AMPLIFIES|\
PRECONDITION_OF|RESOLVES|FRAMES|INSTANTIATES|DIVERGES_TO. \
Return only valid JSON. No preamble. No markdown."""

ENRICH_GAPS = """Given this causal chain:
{chain_json}

Find up to {n} missing intermediary nodes — places where the causal \
jump between two connected nodes skips an important step.

Return JSON:
{{
  "gaps": [
    {{
      "between_from": "<node_id>",
      "between_to": "<node_id>",
      "missing_node": {{"label": "...", "type": "state|event|decision|concept|question|blackbox|goal|task|asset|gate", "description": "..."}},
      "reasoning": "<one sentence why this node is missing>"
    }}
  ]
}}"""

ENRICH_WEIGHTS = """Given this causal chain:
{chain_json}

Review each edge weight (0.0–1.0). Identify edges whose weight seems \
poorly calibrated given the stated evidence and node types.

Return JSON:
{{
  "weight_adjustments": [
    {{
      "edge_id": "...",
      "current_weight": 0.0,
      "suggested_weight": 0.0,
      "reasoning": "<one sentence>"
    }}
  ]
}}"""

ENRICH_SCOPE = """Given this causal chain:
{chain_json}

Identify edges that hold only under specific conditions not yet represented \
in the graph. For each such edge, propose a condition node.

Return JSON:
{{
  "conditions": [
    {{
      "edge_id": "...",
      "condition_label": "...",
      "condition_type": "threshold | context | temporal | population",
      "reasoning": "<one sentence>"
    }}
  ]
}}"""

SUGGEST_NODES = """Given this causal chain:
{chain_json}

Suggest {n} new nodes or edges that would make this chain more complete, \
accurate, or actionable. Prioritize: missing causes, missing effects, \
unresolved black boxes, and nodes with no outbound edges.

Return JSON:
{{
  "suggestions": [
    {{
      "type": "node | edge",
      "node_type": "state|event|decision|concept|question|blackbox|goal|task|asset|gate",
      "label": "...",
      "description": "...",
      "connects_from": "<node_id or null>",
      "connects_to": "<node_id or null>",
      "relation": "CAUSES|ENABLES|BLOCKS|TRIGGERS|REDUCES|REQUIRES|AMPLIFIES|PRECONDITION_OF|RESOLVES|FRAMES|INSTANTIATES|DIVERGES_TO or null",
      "reasoning": "<one sentence>"
    }}
  ]
}}"""

EXPLAIN_CHAIN = """Given this causal chain:
{chain_json}

Write a plain-language explanation in {lang}. \
Structure: one paragraph summary, then walk through the main causal path \
from root causes to final effects. Max 300 words.

Return JSON: {{"explanation": "..."}}"""

EXPLAIN_NODE = """Given this causal chain context:
{context_json}

Explain this specific node: {node_label}
Cover: what it represents, what causes it, what it causes, and \
under what conditions it is active. Max 100 words. Language: {lang}.

Return JSON: {{"explanation": "..."}}"""

CRITIQUE_CHAIN = """Given this causal chain:
{chain_json}

Review it for quality problems. Check for:
1. Missing mechanism nodes (A → B with no explanation of how)
2. Overconfident edges (weight > 0.8 with no evidence field)
3. Scope violations (edge claims universal validity, probably context-specific)
4. Logical reversals (effect listed before cause)
5. Orphan nodes (no causal connections)
6. Vague relation types (AFFECTS used instead of specific verb)

Return JSON:
{{
  "issues": [
    {{
      "severity": "high | medium | low",
      "type": "missing_mechanism | overconfidence | scope | reversal | orphan | vague_relation",
      "element_id": "...",
      "description": "<one sentence>",
      "suggested_fix": "<one sentence>"
    }}
  ]
}}"""

CONTRADICT_CHECK = """Given this causal chain:
{chain_json}

And this new observation:
"{observation}"

Identify which edges in the chain this observation conflicts with. \
Classify each conflict.

Return JSON:
{{
  "conflicts": [
    {{
      "edge_id": "...",
      "conflict_type": "reversal | weakening | scope_violation | temporal_conflict",
      "current_weight": 0.0,
      "suggested_weight": 0.0,
      "reasoning": "<one sentence>"
    }}
  ],
  "no_conflict": true
}}"""

ASK_CHAIN = """Given this causal chain:
{chain_json}

Answer this question about the chain:
"{question}"

Be specific. Reference node ids and edge labels from the chain. \
Max 200 words. Language: {lang}.

Return JSON: {{"answer": "..."}}"""

NOTE_CLASSIFY = """Given this causal chain:
{chain_json}

And this note:
Type: {note_type}
Text: {note_text}
Seed entities: {seed_entities}

Classify each concept in the note against the existing chain.

Return JSON:
{{
  "known": [
    {{"entity": "...", "node_id": "...", "similarity": 0.0}}
  ],
  "delta": [
    {{"entity": "...", "description": "...", "suggested_type": "state|event|decision|concept|question|blackbox|goal|task|asset|gate"}}
  ],
  "structural_role": "root_cause|mechanism|effect|moderator|evidence|question",
  "reasoning": "<one sentence>"
}}

Rules:
- known: concepts already represented by non-deprecated nodes (match by label or semantic similarity ≥ 0.7)
- delta: concepts genuinely absent from the graph
- structural_role: the primary role this note plays relative to existing graph structure
- node_id must be an exact id from the chain JSON"""

NOTE_TO_GRAPH = """Given this causal chain context (known nodes):
{context_json}

New entities to integrate (ΔDATA):
{delta_json}

Structural role of this addition: {structural_role}
Note confidence W-score: {w_score}

Generate nodes and edges to integrate the ΔDATA into the graph.

Return JSON:
{{
  "nodes": [
    {{"label": "...", "type": "state|event|decision|concept|question|blackbox|goal|task|asset|gate",
      "archetype": "root_cause|mechanism|effect|moderator|evidence|question",
      "description": "one sentence"}}
  ],
  "edges": [
    {{"from_ref": "<existing node_id or ΔDATA label>",
      "to_ref": "<existing node_id or ΔDATA label>",
      "relation": "CAUSES|ENABLES|BLOCKS|TRIGGERS|REDUCES|REQUIRES|AMPLIFIES|PRECONDITION_OF|RESOLVES|FRAMES|INSTANTIATES|DIVERGES_TO",
      "weight": 0.7,
      "evidence": "..."}}
  ]
}}

Rules:
- from_ref/to_ref: use exact node_id for known nodes, exact label string for ΔDATA nodes
- archetype must be one of: root_cause|mechanism|effect|moderator|evidence|question
- weight should reflect the W-score confidence level
- connect ΔDATA nodes to the most relevant known nodes"""

TEXT_TO_CHAIN = """Decompose the following text into a causal chain using epistemic classification.

INPUT = PROMPT(known) + ΔDATA(unknown)
  PROMPT  = abstract mechanisms and causal patterns the model already encodes in weights.
            Contains: causal patterns, domain concepts. Never: proper nouns, dates, numbers.
  ΔDATA   = irreducible instance-level facts the model cannot reconstruct from weights.
            Contains: named entities, values, dates, direct quotes, outcomes.

Classify each node:
  KK — abstract mechanism/pattern reliably encoded in weights; no proper nouns or quantities.
       type=concept, confidence ≥ 0.75, archetype=mechanism|moderator.
  KU — known category but instance-level value (named entity, date, measured quantity).
       type=state|event|decision; include the concrete entity value in description.
  UU — post-cutoff entity, proprietary name, unknown namespace; flag for human review.
       type=blackbox, flagged=true, confidence ≤ 0.4.
  UK — structural pattern known in domain A, bridges to domain B.
       type=concept, archetype=moderator; description = "source_domain → target_domain bridge".

Text:
{text}

Return JSON:
{{
  "nodes": [
    {{
      "label": "short label",
      "type": "state|event|decision|concept|question|blackbox|goal|task|asset|gate",
      "description": "one sentence; for KU/UU include the concrete value",
      "klass": "KK|KU|UU|UK",
      "confidence": 0.0,
      "flagged": false,
      "archetype": "root_cause|mechanism|effect|moderator|evidence|null"
    }}
  ],
  "edges": [
    {{
      "from_label": "exact node label",
      "to_label": "exact node label",
      "relation": "CAUSES|ENABLES|BLOCKS|TRIGGERS|REDUCES|REQUIRES|AMPLIFIES|PRECONDITION_OF|RESOLVES|FRAMES|INSTANTIATES|DIVERGES_TO",
      "weight": 0.7,
      "evidence": "one-line rationale"
    }}
  ],
  "causal_prompt": "[abstract mechanism] → [{{slot}}] → [effect]",
  "metrics": {{
    "kk_count": 0,
    "ku_count": 0,
    "uu_count": 0,
    "compression_ratio": 0.0,
    "roundtrip_fidelity": 0.0
  }}
}}

Rules:
- Extract 4-12 nodes covering root causes, mechanisms, and effects
- from_label/to_label must exactly match a label in the nodes list
- compression_ratio = kk_count / total_nodes (fraction that is parametric knowledge)
- roundtrip_fidelity: 0.95 if compose(causal_prompt, ΔDATA) ≈ original text, else lower"""

MERGE_OVERLAP = """Given two causal chains:
Chain A: {chain_a_json}
Chain B: {chain_b_json}

Identify nodes in chain B that represent the same concept as nodes in chain A \
(even if labels differ). Also identify contradicting edges between the two chains.

Return JSON:
{{
  "overlaps": [
    {{"node_a_id": "...", "node_b_id": "...", "similarity": 0.0, "reasoning": "..."}}
  ],
  "contradictions": [
    {{"edge_a_id": "...", "edge_b_id": "...", "conflict_type": "..."}}
  ]
}}"""
