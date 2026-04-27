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

# Run all tests (139 pass, 2 skip without API key)
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

# Note ingestion pipeline
python3 cli.py parse-note notes/<note>.yaml          # parse + W-score
python3 cli.py classify chains/<chain>.causal.json notes/<note>.yaml  # known vs. ΔDATA
python3 cli.py ingest chains/<chain>.causal.json notes/<note>.yaml    # full pipeline

# Living Code — forge, enrich, re-forge
python3 cli.py forge chains/<chain>.causal.json [--out runtime/<name>.py]
python3 cli.py enrich-text chains/<chain>.causal.json --text-file article.txt --source hn.cz
python3 cli.py reforge chains/<chain>.causal.json [--out runtime/<name>.py] [--diff-out runs/d.txt]

# Full end-to-end Living Code demo (steps 1-4,6-8 work without API key)
bash demo_mortgage_mvp.sh

# Interactive demo harness (note ingestion pipeline)
python3 demo.py
python3 demo.py --chain chains/sleep-cognition.causal.json --note notes/note_cold_swim.yaml --dry-run
```

Environment: `ANTHROPIC_API_KEY` is loaded automatically from `.env` at project root via `_load_dotenv()` in `cli.py`.

## Architecture

```
cli.py                  ← entry point; all subcommands; loads .env
demo.py                 ← interactive harness for note ingestion pipeline
demo_mortgage_mvp.sh    ← end-to-end Living Code demo (T1→T6, 8 steps)
editor/
  serve.py              ← HTTPServer on port 7331; REST API + WebSocket upgrade
  template.html         ← vis.js editor UI (toolbar + graph + inspector + overlays)
  decompose.html        ← standalone Knowledge Decomposer page (/decompose route)
  grammar.html          ← standalone Chain Grammar System page (/grammar route)
  static/
    editor.js           ← vis-network init, visual encoding, enrich/import/merge preview,
                           RCDE cluster, summary save/history, CCF panel
    sync.js             ← fetch wrappers for /api/* and /llm/* endpoints
    style.css           ← dark theme
    decompose.js        ← Knowledge Decomposer vis-network; epistemic class coloring
    decompose.css       ← Decomposer layout + klass badge styles
llm/
  client.py             ← Claude API wrapper; strips markdown; parses JSON
  prompts.py            ← all prompt templates: ENRICH, GAP, TEXT_TO_CHAIN,
                           NOTE_CLASSIFY, NOTE_TO_GRAPH, NOTE_MERGE_CHAIN,
                           NOTE_CONNECT_ISOLATED, TEXT_EXTRACT
  enrichment.py         ← gap/weight enrichment pipelines with apply helpers
note/
  schema.py             ← NoteInput dataclass; ARCHETYPES, NOTE_TYPES constants
  parser.py             ← parse_note(), w_score(); supports --- fences, ```yaml blocks, plain text
  classifier.py         ← classify_note() — calls NOTE_CLASSIFY; returns known/delta/role
  evolution.py          ← evolve_graph() — calls NOTE_TO_GRAPH; returns import_node/import_edge
  ingest.py             ← ingest_note() — orchestrates parse→classify→evolve
chain/
  schema.py             ← CausalChain, Node, Edge, ChainMeta dataclasses; includes enrichment fields
  io.py                 ← load/save .causal.json with auto-backup; preserves evidence/overrides
  diff.py               ← structural diff between two chains
  validate.py           ← runs before every save; returns list of issues
src/
  ccf/
    ccf.py              ← compress(graph) → CCF v1 string; restore(ccf) → dict; to_prompt()
    defaults.py         ← NODE_DEFAULTS, EDGE_DEFAULTS, META_DEFAULTS
    grammar.py          ← VALID_TYPES, VALID_ARCHETYPES, VALID_RELATIONS frozensets
    cli.py              ← CLI: compress / restore / roundtrip / ratio
    __init__.py         ← public API re-exports
  forge/
    emit.py             ← forge_chain(chain) → deterministic .py; enrichment-aware:
                           emits _evidence_refs, rate field, last_enrichment in meta
    canonical.py        ← chain_hash(chain) → sha256
    diff.py             ← diff_chains, diff_forge_output, format_diff
    runtime.py          ← STATE/ASSET/EVENT/… decorators + simulate() entry point
    __init__.py         ← exports forge_chain, ForgeError, diff_chains, diff_forge_output, format_diff
  simulate/
    payoff.py           ← REFERENCE_SCENARIO, compute_branch(branch_id, scenario) → dict
    recommend.py        ← score_branch, recommend(results, scenario) → top-3
    runner.py           ← simulate(chain, mode, n, seed) → {branches, recommendations, …};
                           print_comparison(result) for CLI output
    montecarlo.py       ← path_probability, monte_carlo, DEFAULT_CERTAINTIES, BRANCH_PATH_NODES
    sensitivity.py      ← sensitivity_analysis, most_sensitive_node_for_branch, branch_exposures
    trace.py            ← TraceWriter context manager → JSONL in runs/
  enrichment/
    extract.py          ← extract_events(text, chain) → [event] via LLM + TEXT_EXTRACT prompt
    classify.py         ← classify_event, ClassifyError, VALID_TARGET_IDS, E_CLASS_META (E1-E6)
    gate.py             ← run_gates (5-gate pipeline), GateResult, _TARGET_MAP, SOURCE_CREDIBILITY
    apply.py            ← apply_event → chain+evidence+overrides; apply_pending_or_reject
    __init__.py         ← public API re-exports
runtime/                ← forged Python modules (git-tracked for byte-level diffs)
  mortgage_mvp.py       ← generated from chains/mortgage-mvp.causal.json (forge --out)
  mortgage-mvp.py       ← generated by reforge command
runs/                   ← append-only JSONL traces and diff outputs (gitignored except seeds)
chains/                 ← default storage directory
  mortgage-mvp-seed.causal.json  ← pristine seed for reset-demo
  mortgage-mvp.causal.json       ← working copy (enrichable)
chains/backups/         ← timestamped backup destination
notes/                  ← sample note YAML files
tests/                  ← pytest; 141 tests, 10 test files
  test_ccf.py           ← CCF compress/restore round-trip
  test_enrichment.py    ← classify/gate/apply unit tests + 2 LLM integration tests (skip w/o key)
  test_forge.py         ← forge_chain determinism, section order, error handling
  test_io.py            ← load/save/backup round-trip
  test_montecarlo.py    ← path probability, Monte Carlo, sensitivity, trace
  test_note.py          ← note parser, W-score, YAML formats
  test_reforge.py       ← post-enrichment forge output, diff utilities, provenance completeness
  test_schema.py        ← dataclass defaults and short_id
  test_simulate.py      ← all 6 branch payoffs, recommendations, simulate() modes
  test_validate.py      ← orphan edges, weight bounds, cycle detection
.env                    ← ANTHROPIC_API_KEY (gitignored)
```

**Server API endpoints:**
- `GET /api/chain` — load current chain; auto-reloads from disk if mtime changed
- `GET /api/chains` — list all `.causal.json` files in `chains/` (excludes `*-seed.causal.json`)
- `GET /api/chain/ccf` — return CCF v1 compressed text for the current chain (active nodes/edges only; invalid archetypes normalised to `mechanism`)
- `POST /api/chain` — save chain from browser
- `POST /api/chain/switch` — hot-swap active chain without server restart; body: `{filename}`; rejects seed files
- `POST /api/chain/import` — accept a `.causal.json` payload, save to `chains/` (auto-incrementing slug), switch to it; body: `{chain}`
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
- `POST /llm/ingest-note` — legacy note ingestion pipeline (CLI only); body: NoteInput fields; returns `{suggestions, classification, w_score}`
- `POST /llm/note-chain` — Note merge preview (browser); body: `{domain, text}`; calls `NOTE_MERGE_CHAIN`, runs `_patch_isolated_nodes()`, returns full merged chain with `_status` tags and optional `_auto_connected` count
- `POST /llm/summarize` — structured briefing; optional `node_ids` for selection scope

**Enrich/import preview flow (browser):**
Any LLM action that produces graph items → preview nodes/edges added with `_preview_*` ids (purple dashed, `⟨new⟩` label) → suggestions overlay with checkboxes and optional W-score badge → `Accept selected` → `applyPreviewSuggestions()` → `rerenderLayout()` → auto-save

**Note merge preview flow (browser):**
`📝 Note` → user enters Domain + text + confidence/urgency sliders → `Preview merge` → `POST /llm/note-chain` → `addMergePreviewToGraph()` overlays the current graph with colour-coded diffs → merge overlay checklist → `Apply selected` → `applyMergeSelections()` → `rerenderLayout()` → auto-save

- **New nodes** — `_merge_new_*` ids; dark green bg `#0a2a0a`, dashed border `#22c55e`, `⟨new⟩` label prefix; node type badge highlighted blue for actionable types (task/decision/gate/goal/asset) with `▶` pin
- **Modified nodes** — existing id retained; amber dashed border `#f59e0b`, `⟨mod⟩` label prefix; original appearance restored on discard via `nodeToVis()`
- **New edges** — `_merge_e_*` ids; green `#22c55e` dashed
- **Modified edges** — existing id retained; amber `#f59e0b` dashed; restored on discard via `edgeToVis()`
- **Isolation guard** — after all vis `add()` calls, any `_merge_new_*` node not referenced by any edge is removed from vis and from `_mergePending.newNodes`; vis.js silently drops edges whose endpoint doesn't exist so the guard runs after, not before
- **Server-side patch** — `_patch_isolated_nodes(result, chain_data, llm_client)` in `serve.py`: detects new nodes with no edges, calls `NOTE_CONNECT_ISOLATED` as a follow-up LLM call, merges returned edges into the result; sets `result["_auto_connected"] = N`; best-effort (silent no-op on failure, client-side guard catches remainder)
- **`_mergePending`** state — `{newNodes, modNodes, newEdges, modEdges, newIdToVis, summary}`; `newIdToVis` maps LLM `_new_N` ids to vis `_merge_new_N` ids; cleared on chain switch, import, new chain, demo reset, and `renderGraph()`

## Note ingestion pipeline (CLI / legacy browser)

**W-score** = `confidence × 0.6 + urgency × 0.4` — priority gating for ingestion.

**Stage 0 — parse** (`note/parser.py`): Splits YAML front matter (--- fences or ```yaml block) from free text. Falls back to plain text with defaults. Stdlib only.

**Stage 1 — classify** (`note/classifier.py`): Calls `NOTE_CLASSIFY` prompt. Returns `{known: [{entity, node_id, similarity}], delta: [{entity, suggested_type, description, actionable}], structural_role, reasoning}`. Prefers actionable delta types: `task > decision > gate > goal > asset > event > state`.

**Stage 2 — evolve** (`note/evolution.py`): Calls `NOTE_TO_GRAPH` prompt with `note_type`, known context + ΔDATA. Returns `import_node`/`import_edge` suggestions with `confidence` and `reasoning` per node. `from_ref`/`to_ref` can be existing `node_id` or a ΔDATA label — resolved in Python, never in the LLM.

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

## Living Code pipeline (T1–T6)

The Mortgage MVP demonstrates a full Living Code loop: chain → forge → simulate → enrich → re-forge → diff.

**T1 — Seed chain** (`chains/mortgage-mvp.causal.json`): 19 nodes, 25 edges, Czech mortgage scenario (2.4M CZK, 4.9%, 18y, income 85k, reserve 800k). Six decision branches.

**T2 — Forge** (`cli.py forge`): `forge_chain(chain_dict) → str` emits a deterministic Python module. Two calls on the same chain produce byte-identical output (modulo timestamp). Uses `chain_hash()` (SHA-256) for provenance.

**T3 — Simulate** (`src/simulate/`): `compute_branch(branch_id, scenario)` → `{monthly_payment, total_interest, interest_saved, months, reserve_after, dti}`. `recommend(results, scenario)` → top-3 scored branches. `print_comparison(result)` prints Czech comparison table.

**T4 — Monte Carlo** (`src/simulate/montecarlo.py`, `sensitivity.py`, `trace.py`): Path probability = product of node certainties along causal spine + ENABLES predecessors. n=10,000 runs, seed=42 (deterministic). Sensitivity analysis ranks nodes by `|ΔP|/δ`. `TraceWriter` writes append-only JSONL to `runs/`.

**T5 — Enrichment** (`src/enrichment/`): LLM extracts typed events (E1-E6) from financial news via `TEXT_EXTRACT` prompt. 5-gate validation pipeline: schema → credibility (`source_cred × extraction_conf ≥ 0.75`) → bounded shift (±0.10 max per cycle) → grammar re-check → circuit breaker (>15% payoff shift blocked). E1 events auto-apply to `chain.evidence[]` + `chain.meta.scenario_overrides`. E2-E6 go to `chain.pending_review[]`. Known sources: `hn.cz=0.88`, `cnb.cz=0.95`, `unknown=0.50`.

**T6 — Re-forge** (`cli.py reforge`, `src/forge/diff.py`): Re-emits Python after enrichment. Changed nodes gain `_evidence_refs=[...]` in their decorator and a typed field (`rate: float = 0.0395`). `_forge_meta` gains `last_enrichment`. `diff_forge_output()` strips volatile lines (timestamp, hash) before diffing — only semantic mutations show. `diff_chains()` returns structured semantic diff with `changed_nodes`, `new_evidence`, `scenario_changes`.

**Event classes (E1-E6):**
- `E1` — value_update: specific numeric change to a named node parameter → auto-apply
- `E2` — confidence_shift: source reliability or node probability changed → pending_review
- `E3` — new_actor: new institution/entity enters the scenario → pending_review
- `E4` — structural_change: causal pathway added or removed → pending_review
- `E5` — deadline_update: time constraint introduced or changed → pending_review
- `E6` — scenario_invalidation: entire branch or assumption invalidated → pending_review

**Valid enrichment targets** (`VALID_TARGET_IDS` in `src/enrichment/classify.py`):
`AltBankOffer.rate`, `RenewalOffer.rate`, `MortgageActive.annual_rate`, `FixationEndingSoon`, `RateRegime2028`, `MonthlyIncome`, `SavingsReserve`

## Browser UI features

Toolbar buttons: `⎇ Chain` (chain switcher modal) | `＋ New` (create empty chain) | `⬆ Import` (upload `.causal.json`) | `⬇ Export` (download `.causal.json`) | `↺ Reset demo` | `+ Node` | `+ Edge` | `Fit` | `Layout ↕` | `⊞ Cluster` | `⊸ Path` | `Find gaps` | `Suggest` | `Critique` | `📋 Summary` | `⬇ From text` | `📝 Note` | `⬡ Polygon` | `⊕ Decompose` | `📖 Grammar` | `Save ⌘S`

**Chain switcher** — lists all non-seed chains from `GET /api/chains` as cards; clicking one calls `POST /api/chain/switch` and re-renders the graph without page reload. Hover a card to reveal a 🗑 delete button (backs up then removes the file; seed files are protected).

**New chain** — `＋ New` button opens a modal with Name + Domain fields; calls `POST /api/chain/new`, saves an empty chain and switches to it immediately.

**Import chain** — `⬆ Import` opens a file picker; the selected `.causal.json` is read client-side, POSTed to `POST /api/chain/import`, saved to `chains/` with an auto-incrementing slug if a name collision occurs, and switched to immediately.

**Export chain** — `⬇ Export` serialises the current `chainData` to JSON and triggers a browser download named `<chain-slug>.causal.json`. No server round-trip.

**Reset demo** — `↺ Reset demo` button calls `POST /api/demo/reset`; backs up current chain then restores from `*-seed.causal.json`. Seed files are excluded from the chain switcher and cannot be switched to directly.

**Note modal** — Domain text input (e.g. "Personal finance") + free-text area + confidence/urgency sliders with live W-score badge (green ≥0.7, yellow ≥0.4, red <0.4). `Preview merge` button calls `POST /llm/note-chain`; domain value is prepended to note text as `[Domain: ...]` context. Opens the **merge overlay** (green-accented right panel, separate from suggestions overlay) showing grouped checklist of new and modified elements.

**Knowledge Decomposer** (`⊕ Decompose` → opens `/decompose` in new tab) — standalone page that runs the `TEXT_TO_CHAIN` pipeline on pasted text. Nodes are coloured by epistemic class instead of confidence: `KK` blue (abstract parametric mechanism), `KU` yellow (known category, specific instance value), `UU` red (post-cutoff/proprietary, flagged for human review), `UK` purple (cross-domain bridge pattern). Result can be saved as a new `.causal.json` chain via `Save as chain`.

**Summary modal** — `📋 Summary` opens a choice screen when saved summaries exist: `⚡ Generate new` (calls `POST /llm/summarize`) or `📂 Open from history`. When no history exists, generates immediately. Result is a structured briefing (headline, goal, critical path, tasks, decisions, risks, open questions) in colour-coded sections. `💾 Save` persists the snapshot to `chain.summaries` via `POST /api/summary/save`. `📂 History` lists all snapshots; each entry can be viewed, exported as `.md`, or deleted. Operates on selected nodes if any are selected, otherwise the full chain.

**RCDE Path highlight** — `⊸ Path` toggles colour-coding of every node and edge by its RCDE role: root_cause (red), pathway (blue), decision (cyan), effect (green), questions (amber). Off-path edges dim to near-invisible. Node colours override confidence colours for the duration; clicking again restores them via `nodeToVis`/`edgeToVis`. Auto-clears on chain switch, import, new chain, node/edge edit, delete, and accepting preview suggestions. Works independently of cluster positioning.

**RCDE Cluster view** — `⊞ Cluster` toggles a layer-snap layout. Nodes are assigned to RCDE roles (`root_cause` → top, `pathway`, `decision`, `effect`, `questions` → bottom) by `_nodeRole()` using type, archetype, and in/out degree. `_snapToLayers()` saves current positions to `_preclusterPositions` then moves all nodes to vertical columns at fixed Y bands; `_restorePositions()` reverts. `afterDrawing` draws labelled colour bands each frame. No `network.cluster()` API is used — pure `moveNode()`.

**Grammar System** — `📖 Grammar` (opens `/grammar` in new tab) — 4-tab reference: concept map SVG, node/edge compatibility matrix, grammar rules G1–G8 accordion, RCDE binding panel.

**Polygon lasso** — overlay canvas; click to place vertices, **double-click** or **Enter** to close polygon and select all enclosed nodes (persists selection); `Escape` cancels. Selection can then be used with Find gaps / Suggest / Summary (scoped to selected nodes) or deleted with `Delete`/`Backspace`. Multi-node selection also works with **Ctrl+click** (or **Cmd+click**).

**Selection-scoped LLM features** — `Find gaps`, `Suggest`, and `📋 Summary` check `network.getSelectedNodes()` before calling the server. If ≥1 real nodes are selected, only that subgraph (selected nodes + edges between them) is sent to the LLM; the loading message shows the count. Deselect all to revert to full-chain scope.

**Chain Structure panel** — collapsible `<details>` section at the bottom of the Inspector sidebar. Calls `GET /api/chain/ccf` and displays the CCF v1 text in a scrollable monospace block. The summary line shows a `NN · NE` badge (active node/edge counts). A **Copy** button copies the CCF to clipboard. Refreshes automatically on load, chain switch, import, new-chain creation, and manual save. Server-side: filters deprecated items, normalises null/invalid archetypes to `mechanism` before calling `ccf.compress()`.

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
- Merge preview nodes/edges use ids prefixed `_merge_new_` / `_merge_e_` — never persisted; cleared by `clearMergePreview()` and `renderGraph()`
- Isolated merge-preview nodes are forbidden — `addMergePreviewToGraph()` removes any `_merge_new_*` node not referenced by any edge after all vis DataSet operations complete
- Enrichment tests use the seed file (`mortgage-mvp-seed.causal.json`) as baseline — never the working copy

## LLM enrichment

Model: `claude-sonnet-4-6` | Max tokens: 1000 per call (2500 for `note-chain`, 800 for `_patch_isolated_nodes` follow-up)
All prompts are named constants in `llm/prompts.py`. System prompt always includes: `"Return only valid JSON. No preamble. No markdown."`

CLI enrichment modes (`python3 cli.py enrich <file> --mode`): `full | gaps | weights | scope`
Browser enrichment: `Find gaps` (mode=gaps) | `Suggest` (mode=suggest) — both use preview flow. `📋 Summary` uses a separate read-only modal (no preview nodes). All three are selection-scoped when nodes are selected (`POST /llm/enrich-preview` and `POST /llm/summarize` accept optional `node_ids`; server calls `_subgraph()` to filter chain data).

**Note prompts** (`llm/prompts.py`):
- `NOTE_MERGE_CHAIN` — takes `{chain_json, domain, note_text}`; returns full merged chain with `_status: existing|new|modified` on every node/edge, `_reasoning`, `_changes`; enforces no-isolated-node rule
- `NOTE_CONNECT_ISOLATED` — follow-up prompt; takes `{isolated_json, existing_nodes_json, new_nodes_json, edge_id_start}`; returns `{edges}` connecting each isolated node to the most causally relevant target
- `NOTE_CLASSIFY` — takes `{chain_json, note_type, note_text, seed_entities}`; delta items include `actionable` flag; type priority: `task > decision > gate > goal > asset > event > state`
- `NOTE_TO_GRAPH` — takes `{context_json, delta_json, note_type, structural_role, w_score}`; returns nodes with `confidence` and `reasoning` fields; actionability rules keyed to `note_type`
- `TEXT_EXTRACT` — takes `{alt_rate, renewal_rate, annual_rate, article_text}`; returns array of E1-E6 events with `class`, `target_node_id`, `direction`, `magnitude`, `new_value_hint`, `extraction_confidence`, `text_span`, `reasoning`; `URL_EXTRACT` is an alias

## CCF v1 — Causal Compact Format

Text serialisation of a causal graph. ~15× smaller than `.causal.json`. Used by the Chain Structure inspector panel and `to_prompt()` for LLM context embedding. Module: `src/ccf/`.

```
GRAPH:<name>|<domain>|<short_id>
N:<alias>=<label>[<type>/<archetype>]"<description>"@<chain_link>~<confidence>{tag1,tag2}!~dep
E:<from_alias>-><to_alias> <relation>,<weight>,<confidence>
```

- Aliases are ordinal (`n0`, `n1`, …); generated fresh on `restore()` with new UUIDs
- Fields at default values are omitted (confidence 0.7 for nodes, weight/confidence 0.5 for edges)
- `!` = flagged, `~dep` = deprecated
- `compress()` raises `ValueError` on missing required fields, invalid enums, or dangling edges
- Before compressing in the browser endpoint, deprecated items are filtered and null/unknown archetypes are normalised to `mechanism`

CLI (requires `pip install -e .` or `python -m ccf`):
```bash
python -m ccf compress chains/<name>.causal.json [--out file.ccf]
python -m ccf restore file.ccf [--out chains/<name>.causal.json]
python -m ccf roundtrip chains/<name>.causal.json   # verify lossless
python -m ccf ratio chains/<name>.causal.json        # print compression ratio
```

## .causal.json format

```json
{
  "meta": {
    "id", "name", "domain", "created_at", "updated_at", "version", "author", "description",
    "scenario_overrides": {}       // enrichment: e.g. {"alt_rate": 0.0395}
  },
  "nodes": [{
    "id", "label", "description", "type", "archetype", "tags", "confidence",
    "created_at", "source", "deprecated", "flagged", "chain_link",
    "_status": "enriched",         // set by enrichment.apply when E1 is applied
    "_evidence_ref": "ev_..."      // id of the evidence entry that modified this node
  }],
  "edges": [{
    "id", "from", "to", "relation", "weight", "confidence", "direction",
    "condition", "evidence", "deprecated", "flagged", "version", "created_at", "source"
  }],
  "history": [{ "timestamp", "action", "actor", "payload" }],
  "summaries": [{ "id", "created_at", "headline", "scope", "data" }],
  "evidence": [{                   // append-only enrichment ledger
    "id", "timestamp", "source", "source_credibility", "extraction_confidence",
    "text_span", "reasoning", "class", "target_node_id",
    "old_value", "new_value", "shift_proposed", "shift_applied",
    "shift_capped_by_bounds", "applied"
  }],
  "pending_review": [{             // E2-E6 and gate-blocked events
    "id", "class", "event", "source", "gate_result", "added_at"
  }]
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
**Preview nodes** = dark purple bg `#2d1b4e`, dashed border `#8b5cf6`, label prefixed `⟨new⟩` (enrich/suggest flow)
**Merge-new nodes** = dark green bg `#0a2a0a`, dashed border `#22c55e`, label prefixed `⟨new⟩` (note merge flow)
**Merge-modified nodes** = existing node overlaid with amber dashed border `#f59e0b`, label prefixed `⟨mod⟩`
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
- Never persist merge preview nodes/edges (`_merge_new_*` / `_merge_e_*` ids) — display-only until `applyMergeSelections()` creates real ids
- Never add isolated nodes to the merge preview — the isolation guard in `addMergePreviewToGraph()` enforces this; do not remove it
- Never list or switch to `*-seed.causal.json` files — they are reset-demo templates only
- Never save to `_chain_path` if it points to a seed file
- Never use `chains/mortgage-mvp.causal.json` as test fixture baseline — use the seed file
