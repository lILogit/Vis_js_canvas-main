# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Causal Editor — Universal Visual Causal Chain Editor

Interactive causal graph editor with vis.js, Claude API enrichment, and JSON file storage.
MVP: single-user, local files, no database required.

## Stack

- Python 3.11 stdlib only — no frameworks, no ORMs
- vis.js Network 9.1.9 (standalone CDN) — graph editor in browser
- Claude API (`claude-sonnet-4-6`) — LLM enrichment layer
- JSON files — storage format (one file per chain)
- `http.server` + WebSocket — local dev server
- `anthropic` Python SDK

## Development commands

```bash
# Run the editor (opens browser automatically)
python3 cli.py open chains/<name>.causal.json

# Restart the server (kill existing, relaunch)
lsof -ti:7331 | xargs kill -9 2>/dev/null; python3 cli.py open chains/<name>.causal.json

# Create a new chain
python3 cli.py new "My Chain" --domain science

# Run tests
python3 -m pytest tests/ -v

# Run a single test file
python3 -m pytest tests/test_validate.py

# Validate a chain file
python3 cli.py validate chains/<name>.causal.json

# LLM commands (require ANTHROPIC_API_KEY in .env)
python3 cli.py ask chains/<name>.causal.json "question"
python3 cli.py enrich chains/<name>.causal.json --mode gaps
python3 cli.py critique chains/<name>.causal.json

# Chain inspection and editing
python3 cli.py list                                  # list all chains
python3 cli.py info chains/<name>.causal.json        # summary: nodes, edges, cycles, orphans
python3 cli.py add-node chains/<name>.causal.json --label "X" --type state
python3 cli.py add-edge chains/<name>.causal.json --from <id> --to <id> --relation CAUSES
python3 cli.py remove chains/<name>.causal.json --id <node-or-edge-id>

# Export (formats: json, dot, mermaid, markdown)
python3 cli.py export chains/<name>.causal.json --format mermaid --output out.md

# History, backup, diff
python3 cli.py history chains/<name>.causal.json --last 20
python3 cli.py backup chains/<name>.causal.json
python3 cli.py diff chains/a.causal.json chains/b.causal.json

# LLM explain
python3 cli.py explain chains/<name>.causal.json            # full chain
python3 cli.py explain chains/<name>.causal.json --node <id>

# Reset demo chains to seed state
python3 cli.py reset-demo

# Note ingestion pipeline (Phase 1-3)
python3 cli.py parse-note notes/<note>.yaml          # parse + W-score
python3 cli.py classify chains/<chain>.causal.json notes/<note>.yaml  # known vs. ΔDATA
python3 cli.py ingest chains/<chain>.causal.json notes/<note>.yaml    # full pipeline

# Interactive demo harness (all pipeline stages with predefined chains/notes)
python3 demo.py
python3 demo.py --chain chains/sleep-cognition.causal.json --note notes/note_cold_swim.yaml --dry-run
```

Environment: `ANTHROPIC_API_KEY` is loaded automatically from `.env` at project root via `_load_dotenv()` in `cli.py`.

## Architecture

```
cli.py                  ← entry point; dispatches subcommands; loads .env
demo.py                 ← interactive demo/test harness for ingestion pipeline
editor/
  serve.py              ← HTTPServer on port 7331; REST API + WebSocket upgrade
  template.html         ← vis.js editor UI (toolbar + graph + inspector + overlays)
  decompose.html        ← standalone Knowledge Decomposer page (/decompose route)
  grammar.html          ← standalone Chain Grammar System page (/grammar route)
  static/
    editor.js           ← vis-network init, visual encoding, enrich/import/ingest preview, RCDE cluster, summary save/history
    sync.js             ← fetch wrappers for /api/* and /llm/* endpoints (saveSummary, deleteSummary, etc.)
    style.css           ← dark theme
    decompose.js        ← Knowledge Decomposer vis-network; epistemic class coloring
    decompose.css       ← Decomposer layout + klass badge styles
llm/
  client.py             ← Claude API wrapper; strips markdown; parses JSON
  prompts.py            ← all prompt templates: ENRICH, GAP, TEXT_TO_CHAIN,
                           NOTE_CLASSIFY, NOTE_TO_GRAPH
  enrichment.py         ← gap/weight enrichment pipelines with apply helpers
note/
  schema.py             ← NoteInput dataclass; ARCHETYPES, NOTE_TYPES constants
  parser.py             ← parse_note(), w_score(); supports --- fences, ```yaml blocks, plain text
  classifier.py         ← classify_note() — calls NOTE_CLASSIFY; returns known/delta/role
  evolution.py          ← evolve_graph() — calls NOTE_TO_GRAPH; returns import_node/import_edge
  ingest.py             ← ingest_note() — orchestrates parse→classify→evolve
chain/
  schema.py             ← CausalChain, Node, Edge, ChainMeta dataclasses
  io.py                 ← load/save .causal.json with auto-backup (.bak)
  diff.py               ← structural diff between two chains
  validate.py           ← runs before every save; returns list of issues
chains/                 ← default storage directory
chains/backups/         ← timestamped backup destination
notes/                  ← sample note files for demo/testing
tests/                  ← pytest; 42 tests across schema, validate, io, note
.env                    ← ANTHROPIC_API_KEY (gitignored)
```

**Server API endpoints:**
- `GET /api/chain` — load current chain; auto-reloads from disk if mtime changed
- `GET /api/chains` — list all `.causal.json` files in `chains/` (excludes `*-seed.causal.json`)
- `POST /api/chain` — save chain from browser
- `POST /api/chain/switch` — hot-swap active chain without server restart; body: `{filename}`; rejects seed files
- `POST /api/demo/reset` — copies `*-seed.causal.json` over matching chain files, reloads if active; returns `{reset: [filenames], chain}`
- `POST /api/validate` — run structural validation
- `POST /api/summary/save` — append a summary snapshot to `chain.summaries` and persist; body: `{entry}`
- `POST /api/summary/delete` — remove a summary by id; body: `{id}`
- `POST /llm/ask` — free-form question
- `POST /llm/explain` — explain node or full chain
- `POST /llm/suggest` — suggest N new nodes/edges
- `POST /llm/critique` — quality review
- `POST /llm/contradict` — contradiction detection
- `POST /llm/enrich-preview` — gap/suggest candidates (no write); mode: `gaps|suggest`
- `POST /llm/import-text` — convert free text to nodes/edges (preview only)
- `POST /llm/ingest-note` — full note ingestion pipeline; body: NoteInput fields; returns `{suggestions, classification, w_score}`
- `POST /llm/summarize` — structured briefing; optional `node_ids` for selection scope

**Enrich/import/ingest preview flow (browser):**
Any LLM action that produces graph items → preview nodes/edges added with `_preview_*` ids (purple dashed, `⟨new⟩` label) → suggestions overlay with checkboxes and optional W-score badge → `Accept selected` → `applyPreviewSuggestions()` → `rerenderLayout()` → auto-save

## Note ingestion pipeline

**W-score** = `confidence × 0.6 + urgency × 0.4` — priority gating for ingestion.

**Stage 0 — parse** (`note/parser.py`): Splits YAML front matter (--- fences or ```yaml block) from free text. Falls back to plain text with defaults. Stdlib only.

**Stage 1 — classify** (`note/classifier.py`): Calls `NOTE_CLASSIFY` prompt. Returns `{known: [{entity, node_id, similarity}], delta: [{entity, suggested_type, description}], structural_role, reasoning}`. Seed entities resolve against existing node labels; unmatched text entities are extracted heuristically.

**Stage 2 — evolve** (`note/evolution.py`): Calls `NOTE_TO_GRAPH` prompt with known context + ΔDATA. Returns `import_node`/`import_edge` suggestions. `from_ref`/`to_ref` can be existing `node_id` or a ΔDATA label — resolved in Python, never in the LLM.

**Stage 3 — apply**: Two-pass: nodes first (building `label→id` map), then edges (remapping labels to real IDs). Same pattern used in both CLI (`cmd_ingest`) and browser (`applyPreviewSuggestions`).

**Note YAML format:**
```yaml
---
type: hypothesis          # hypothesis|observation|decision|question|evidence
confidence: 0.6           # 0–1
urgency: 0.4              # 0–1
seed_entities:
  - existing node label
---
Free text body.
```

**Archetype values** (set on nodes, string): `root_cause | mechanism | effect | moderator | evidence | question`

## Browser UI features

Toolbar buttons: `⎇ Chain` (chain switcher modal) | `＋ New` (create empty chain) | `↺ Reset demo` | `+ Node` | `+ Edge` | `Fit` | `Layout ↕` | `Find gaps` | `Suggest` | `Critique` | `📋 Summary` | `⬇ From text` | `📝 Note` | `⬡ Polygon` | `⊕ Decompose` | `📖 Grammar` | `⊞ Cluster` | `Save ⌘S`

**Chain switcher** — lists all non-seed chains from `GET /api/chains` as cards; clicking one calls `POST /api/chain/switch` and re-renders the graph without page reload. Hover a card to reveal a 🗑 delete button (backs up then removes the file; seed files are protected).

**New chain** — `＋ New` button opens a modal with Name + Domain fields; calls `POST /api/chain/new`, saves an empty chain and switches to it immediately.

**Reset demo** — `↺ Reset demo` button calls `POST /api/demo/reset`; backs up current chain then restores from `*-seed.causal.json`. Seed files are excluded from the chain switcher and cannot be switched to directly.

**Note modal** — type dropdown, text area, seed entities, confidence/urgency sliders with live W-score badge (green ≥0.7, yellow ≥0.4, red <0.4); "Load example" dropdown pre-fills with 3 predefined demo notes. Submit calls `/llm/ingest-note`, known entities highlighted via `network.selectNodes()`.

**Knowledge Decomposer** (`⊕ Decompose` → opens `/decompose` in new tab) — standalone page that runs the `TEXT_TO_CHAIN` pipeline on pasted text. Nodes are coloured by epistemic class instead of confidence: `KK` blue (abstract parametric mechanism), `KU` yellow (known category, specific instance value), `UU` red (post-cutoff/proprietary, flagged for human review), `UK` purple (cross-domain bridge pattern). Result can be saved as a new `.causal.json` chain via `Save as chain`.

**Summary modal** — `📋 Summary` opens a choice screen when saved summaries exist: `⚡ Generate new` (calls `POST /llm/summarize`) or `📂 Open from history`. When no history exists, generates immediately. Result is a structured briefing (headline, goal, critical path, tasks, decisions, risks, open questions) in colour-coded sections. `💾 Save` persists the snapshot to `chain.summaries` via `POST /api/summary/save`. `📂 History` lists all snapshots; each entry can be viewed, exported as `.md`, or deleted. Operates on selected nodes if any are selected, otherwise the full chain.

**RCDE Cluster view** — `⊞ Cluster` toggles a layer-snap layout. Nodes are assigned to RCDE roles (`root_cause` → top, `pathway`, `decision`, `effect`, `questions` → bottom) by `_nodeRole()` using type, archetype, and in/out degree. `_snapToLayers()` saves current positions to `_preclusterPositions` then moves all nodes to vertical columns at fixed Y bands; `_restorePositions()` reverts. `afterDrawing` draws labelled colour bands each frame. No `network.cluster()` API is used — pure `moveNode()`.

**Grammar System** — `📖 Grammar` (opens `/grammar` in new tab) — 4-tab reference: concept map SVG, node/edge compatibility matrix, grammar rules G1–G8 accordion, RCDE binding panel.

**Polygon lasso** — overlay canvas; click to place vertices, **double-click** or **Enter** to close polygon and select all enclosed nodes (persists selection); `Escape` cancels. Selection can then be used with Find gaps / Suggest / Summary (scoped to selected nodes) or deleted with `Delete`/`Backspace`. Multi-node selection also works with **Ctrl+click** (or **Cmd+click**).

**Selection-scoped LLM features** — `Find gaps`, `Suggest`, and `📋 Summary` check `network.getSelectedNodes()` before calling the server. If ≥1 real nodes are selected, only that subgraph (selected nodes + edges between them) is sent to the LLM; the loading message shows the count. Deselect all to revert to full-chain scope.

**Keyboard shortcuts:** `⌘S`/`Ctrl+S` save | `Delete`/`Backspace` soft-delete selected | `Escape` cancel lasso / close any overlay | `Enter` finish lasso polygon (≥3 points) | `Ctrl+click` / `Cmd+click` multi-select nodes

## Key invariants

- GOAL: at most one active GOAL node per chain; it is the terminal anchor
- ASSET: only connects to TASK via REQUIRES or ENABLES — never in the causal spine
- GATE: must have at least one DIVERGES_TO outbound edge
- NEVER overwrite nodes/edges — append new version, set old `deprecated: true`
- NEVER delete from `history` array — it is append-only
- NEVER call Claude API without a system prompt
- NEVER generate node/edge ids inside LLM responses — always generate in Python (`uuid4().hex[:8]`)
- ALWAYS run `validate()` before saving — not after
- ALWAYS backup `.causal.json` before any write (`.bak` sidecar)
- ALWAYS strip markdown from LLM responses before JSON parsing
- Preview nodes/edges use ids prefixed `_preview_` — never persisted to chainData or disk

## LLM enrichment

Model: `claude-sonnet-4-6` | Max tokens: 1000 per call
All prompts are named constants in `llm/prompts.py`. System prompt always includes: `"Return only valid JSON. No preamble. No markdown."`

CLI enrichment modes (`python3 cli.py enrich <file> --mode`): `full | gaps | weights | scope`
Browser enrichment: `Find gaps` (mode=gaps) | `Suggest` (mode=suggest) — both use preview flow. `📋 Summary` uses a separate read-only modal (no preview nodes). All three are selection-scoped when nodes are selected (`POST /llm/enrich-preview` and `POST /llm/summarize` accept optional `node_ids`; server calls `_subgraph()` to filter chain data).

## .causal.json format

```json
{
  "meta": { "id", "name", "domain", "created_at", "updated_at", "version", "author", "description" },
  "nodes": [{ "id", "label", "description", "type", "archetype", "tags", "confidence", "created_at", "source", "deprecated", "flagged" }],
  "edges": [{ "id", "from", "to", "relation", "weight", "confidence", "direction", "condition",
              "evidence", "deprecated", "flagged", "version", "created_at", "source" }],
  "history": [{ "timestamp", "action", "actor", "payload" }],
  "summaries": [{ "id", "created_at", "headline", "scope", "data" }]
}
```

Node types: `state | event | decision | concept | question | blackbox | goal | task | asset | gate`

RCDE extensions:
- `goal` — desired future STATE; terminal chain anchor; at most one per chain
- `task` — deliberate EVENT triggered by an agent; fires once ASSET requirements are met
- `gate` — scored DECISION fork; mutually exclusive paths; must have DIVERGES_TO edges
- `asset` — resource/capability consumed by a TASK; connects via REQUIRES/ENABLES only (never causal spine)

Edge relations: `CAUSES | ENABLES | BLOCKS | TRIGGERS | REDUCES | REQUIRES | AMPLIFIES | PRECONDITION_OF | RESOLVES | FRAMES | INSTANTIATES | DIVERGES_TO`

RCDE edge semantics:
- `PRECONDITION_OF` — must be true before target fires (STATE/TASK → GOAL)
- `RESOLVES` — closes an open uncertainty (DECISION/TASK → QUESTION)
- `FRAMES` — shapes interpretation of a node (CONCEPT → any)
- `INSTANTIATES` — task is the direct intervention causing goal (TASK → GOAL)
- `DIVERGES_TO` — one scored branch of a gate fork (GATE → STATE/GOAL)

Source values: `user | llm | import`

## vis-network visual encoding

**Node shape** = type (`state`→box, `event`→diamond, `decision`→hexagon, `concept`→ellipse, `question`→star, `blackbox`→question, `goal`→triangle, `task`→dot, `asset`→database, `gate`→square)
**Node color** = confidence (≥0.8 forest-green `#2f9e44`, ≥0.6 blue `#1971c2`, ≥0.4 amber `#e67700`, ≥0.2 orange-red `#e8590c`, else red `#c92a2a`)
**Node font color** = dark `#1a1a2e` for all types except `event` → white `#ffffff`
**Node border** = source (user→solid `#555`, llm→dashed `#8b5cf6`, flagged→solid `#ef4444`)
**Node tooltip** = rich HTML: label, description, type·archetype, confidence·source, flagged/deprecated
**Preview nodes** = dark purple bg `#2d1b4e`, dashed border `#8b5cf6`, label prefixed `⟨new⟩`
**Edge color** = relation (CAUSES `#94a3b8`, ENABLES `#22c55e`, BLOCKS `#ef4444`, TRIGGERS `#f59e0b`, REDUCES `#4a9eed`, REQUIRES `#8b5cf6`, AMPLIFIES `#ec4899`, PRECONDITION_OF `#06b6d4`, RESOLVES `#10b981`, FRAMES `#a78bfa`, INSTANTIATES `#fbbf24`, DIVERGES_TO `#fb923c`)
**Edge width** = `weight × 6` (min 1, max 8) | deprecated→dashes+opacity 0.35 | BLOCKS→arrowhead `bar` | DIVERGES_TO→arrowhead `vee`
**Edge tooltip** = rich HTML: relation, weight·confidence, condition, evidence, flagged/deprecated

Default layout: `hierarchical UD, physics: false`. Single source of truth: `HIERARCHICAL_LAYOUT` constant used by both `OPTIONS` and `rerenderLayout()`. Key settings: `sortMethod: 'directed'`, `shakeTowards: 'leaves'` (flush leaf nodes at bottom), `parentCentralization: false` (prevent sibling drift), `nodeSpacing: 120`. `rerenderLayout()` briefly re-enables hierarchical layout to recalculate positions then disables it so nodes can be dragged freely. Never use `physics: true` as default.

## Delete behaviour

Soft-delete only: sets `deprecated: true`, removes from vis DataSet, cascades to connected edges when deleting a node. Never physically removes from `chainData` arrays or the JSON file.

## Storage conventions

Files: `./chains/<name>.causal.json` — lowercase, hyphens, no spaces
Seeds: `./chains/<name>-seed.causal.json` — read-only pristine state; never listed or switched to; used by reset-demo
Backups: `./chains/backups/<name>_<YYYYMMDDTHHmmss>.causal.json`
Auto-backup triggers: before enrich/contradict/merge, before restore, every 10th manual browser save; also before reset-demo overwrites a target

## What NOT to do

- Never call Claude API in a loop without user confirmation between calls
- Never serve the editor on a public port — localhost only
- Never store API keys in chain files or output
- Never show raw JSON to user in browser — always render in vis-network
- Never use `physics: true` as default layout
- Never persist preview nodes/edges (`_preview_*` ids) — they are display-only until accepted
- Never list or switch to `*-seed.causal.json` files — they are reset-demo templates only
- Never save to `_chain_path` if it points to a seed file
