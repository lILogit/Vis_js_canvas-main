# Causal Editor — User Guide

## What is this?

The Causal Editor is a visual tool for building and exploring **causal chain diagrams** — graphs that model how one thing leads to another. Use it to map out cause-and-effect relationships in any domain: science, policy, engineering, personal decision-making, research hypotheses, and more.

It combines a drag-and-drop graph **editor** with an AI assistant (Claude) that can fill gaps, suggest new nodes, critique your logic, and answer questions about your chain.

---

## Core Concept: The Causal Chain

A **causal chain** is a directed graph where:

- **Nodes** represent things that exist or happen (states, events, decisions, concepts, goals…)
- **Edges** represent the relationship between them (causes, enables, blocks, triggers…)
- **Confidence** on nodes and edges reflects how certain you are of each element
- **History** records every change — nothing is ever permanently deleted

The goal is to make implicit reasoning explicit and inspectable.

---

## The RCDE Framework

The editor uses the **RCDE** model — **Root cause → Causal pathway → Decision point → Effect** — to structure chains. Four extended node types support intervention planning:

| Layer | Purpose | Node types |
|---|---|---|
| **Root cause** | What drives the system | `state`, `event`, `concept` |
| **Causal pathway** | How causes propagate | `state`, `event`, `blackbox` |
| **Decision point** | Where agents can intervene | `decision`, `gate`, `task` |
| **Effect** | What the chain produces | `goal`, `state` |

Supporting types: `question` (open uncertainty), `asset` (resource/capability), `gate` (scored fork).

---

## Node Types

Each node type has a distinct **shape** and meaning.

| Type | Shape | Use when… |
|---|---|---|
| `state` | Rectangle | Something that persists over time — a condition, situation, or attribute. *"High cortisol level"*, *"System is overloaded"* |
| `event` | Diamond | Something that happens at a point in time — a change or occurrence. *"Patient collapses"*, *"Cache invalidated"* |
| `decision` | Hexagon | A choice point where an agent selects between options. *"Choose treatment protocol"* |
| `concept` | Ellipse | An abstract idea, principle, or explanatory construct. *"Cognitive load"*, *"Diminishing returns"* |
| `question` | Star | An open uncertainty or hypothesis not yet resolved. *"Does sleep duration mediate this?"* |
| `blackbox` | Question mark | A mechanism you know exists but can't fully explain yet. *"Unknown inflammatory pathway"* |
| `goal` | Triangle | The desired future state — the terminal anchor of the chain. At most **one** per chain. |
| `task` | Dot | A deliberate action taken by an agent to produce an effect. *"Administer 10mg dose"* |
| `asset` | Cylinder | A resource or capability consumed or required by a task. *"Budget"*, *"Lab equipment"* |
| `gate` | Square | A formally scored decision fork with mutually exclusive branches. Must have `DIVERGES_TO` edges. |

### Node color = confidence

| Color | Confidence |
|---|---|
| Forest green | ≥ 0.8 — well established |
| Blue | ≥ 0.6 — reasonably supported |
| Amber | ≥ 0.4 — plausible, uncertain |
| Orange-red | ≥ 0.2 — speculative |
| Red | < 0.2 — highly uncertain |

### Node border = source

| Border style | Meaning |
|---|---|
| Solid gray | Created by you (user) |
| Dashed purple | Suggested by the AI |
| Solid red | Flagged for review |

---

## Edge Types (Relations)

Edges are directed (from → to) and color-coded by relation type.

### Core causal relations

| Relation | Color | Meaning |
|---|---|---|
| `CAUSES` | Gray | A directly produces B. The primary causal link. |
| `ENABLES` | Green | A makes B possible, but does not guarantee it. |
| `BLOCKS` | Red | A prevents or inhibits B. Arrowhead shows as a bar. |
| `TRIGGERS` | Amber | A initiates B (often a threshold or event crossing). |
| `REDUCES` | Blue | A weakens or diminishes B. |
| `AMPLIFIES` | Pink | A strengthens or accelerates B. |
| `REQUIRES` | Purple | B cannot happen without A (precondition, not cause). |

### RCDE planning relations

| Relation | Color | Meaning |
|---|---|---|
| `PRECONDITION_OF` | Cyan | A must be true before B can fire. Used for STATE/TASK → GOAL. |
| `INSTANTIATES` | Gold | A task is the direct intervention causing a goal. TASK → GOAL. |
| `RESOLVES` | Emerald | A closes or answers an open question. DECISION/TASK → QUESTION. |
| `FRAMES` | Lavender | A shapes how B should be interpreted. CONCEPT → any. |
| `DIVERGES_TO` | Orange | One scored branch of a gate fork. GATE → STATE/GOAL. |

### Edge width = weight

Edge thickness scales with the `weight` field (0–1). A thick edge means a strong, high-weight relationship. A thin edge is weak or marginal.

---

## Node Archetypes

An **archetype** is a semantic role label you can attach to any node, independent of its type. It helps with analysis and LLM prompts.

| Archetype | Role |
|---|---|
| `root_cause` | The upstream driver of the chain |
| `mechanism` | The process by which one thing produces another |
| `effect` | A downstream outcome |
| `moderator` | A variable that changes the strength of a relationship |
| `evidence` | An empirical observation supporting the chain |
| `question` | An open issue that needs resolution |

---

## Getting Started

### Opening a chain
Launch the editor from the terminal:
```bash
python3 cli.py open chains/<name>.causal.json
```
The browser opens automatically at `http://localhost:7331`.

### Switching chains
Click **⎇ Chain** in the toolbar to see all your chains. Click any card to switch without restarting. Hover a card to reveal the delete button (🗑).

### Creating a chain
Click **＋ New**, enter a name and domain, and an empty chain is created and opened immediately.

---

## Editing the Graph

### Adding a node
1. Click **+ Node** in the toolbar
2. Fill in Label, Type, Description, Confidence, and optional Archetype
3. Click **Add** — the node appears in the graph

### Adding an edge
1. Click **+ Edge**
2. Select the **From** node, **To** node, and **Relation** type
3. Set weight and optional condition/evidence text
4. Click **Add**

### Editing a node or edge
Click any node or edge to open the **Inspector** panel on the right. Edit fields inline and click **Save changes**.

### Deleting
Select a node or edge and press `Delete` or `Backspace`. This is a **soft delete** — the element is hidden and marked `deprecated: true` but never removed from the file. Connected edges are cascaded automatically.

### Selecting multiple nodes
- **Ctrl+click** (or **Cmd+click**) to add nodes to selection
- **⬡ Polygon** button to draw a lasso polygon — click vertices, double-click or press `Enter` to close and select all enclosed nodes

### Layout
- **Fit** — zoom to fit the entire graph
- **Layout ↕** — re-run the hierarchical top-down layout
- **⊞ Cluster** — group nodes by RCDE layer: **Root Cause** (upstream drivers), **Pathway** (mid-chain propagation), **Decision** (interventions: task/gate/decision/asset), **Effect** (goals and terminal nodes), **Questions** (open uncertainties). Click a cluster to expand it. Zoom out past 0.45× to auto-cluster; zoom back in past 0.65× to auto-expand.
- Nodes can be freely dragged after layout

### Saving
`⌘S` / `Ctrl+S` or the **Save** button. The editor auto-backs up before significant operations. Every 10th manual save also triggers a backup.

---

## Filter Bar

At the bottom of the screen:

| Filter | What it does |
|---|---|
| **Type** | Show only nodes of a specific type |
| **Min confidence** | Hide nodes below a confidence threshold |
| **Source** | Show only user / AI / imported nodes |
| **Flagged only** | Show only nodes/edges marked for review |

---

## AI Features

All AI features require `ANTHROPIC_API_KEY` (or an OpenAI/Z.AI key) set in your `.env` file. The active provider is shown in the Inspector panel — click **↺** to recheck.

### Find gaps
Analyzes the chain and suggests missing nodes or edges that would make the causal logic more complete. Suggestions appear as purple dashed **preview nodes** (labeled `⟨new⟩`). Review them in the suggestions panel, check the ones you want, and click **Accept selected**.

### Suggest
Asks the AI to propose entirely new nodes and edges that could extend or enrich the chain. Same preview flow as above.

### Critique
Asks the AI to review the chain for logical issues: missing links, contradictions, unsupported jumps, over-simplified mechanisms. Results appear in the Inspector panel as a written review.

### Summary (📋)
Generates a structured briefing: headline, goal, critical path, tasks, decisions, risks, and open questions. Renders in color-coded sections in an overlay. Read-only — no preview nodes.

### Selection-scoped AI
If you have nodes selected (via Ctrl+click or polygon lasso), **Find gaps**, **Suggest**, and **Summary** all operate on just the selected subgraph. The loading message shows the node count. Deselect all to revert to full-chain scope.

### Ask a question
In the Inspector panel, type any question about the chain and press **Ask**. The AI answers in the context of your specific graph.

### Explain
Select a node and click **Explain** in the Inspector to get a natural language explanation of that node's role in the chain.

---

## Note Ingestion (📝 Note)

The Note modal lets you feed observations, hypotheses, or decisions into the chain as structured input.

### Note fields
| Field | Description |
|---|---|
| **Type** | `hypothesis`, `observation`, `decision`, `question`, or `evidence` |
| **Confidence** | How certain you are (0–1) |
| **Urgency** | How time-sensitive this is (0–1) |
| **Seed entities** | Existing node labels this note relates to |
| **Body** | Free text describing the note |

**W-score** = `confidence × 0.6 + urgency × 0.4` — shown as a badge (green ≥0.7, yellow ≥0.4, red <0.4). Low-scoring notes are lower priority for ingestion.

### What happens on Submit
1. The note is parsed and classified against the existing chain
2. Entities already in the chain are highlighted (blue selection glow)
3. New entities (ΔDATA) become preview nodes/edges for you to review
4. Accept selected suggestions to merge them into the chain

---

## Knowledge Decomposer (⊕ Decompose)

Opens in a new tab. Paste any free text (article excerpt, research notes, meeting transcript) and the AI extracts a causal graph from it. Nodes are colored by **epistemic class**:

| Color | Class | Meaning |
|---|---|---|
| Blue | `KK` | Known mechanism with quantifiable parameters |
| Yellow | `KU` | Known category, but specific instance value is uncertain |
| Red | `UU` | Post-cutoff or proprietary — flagged for human review |
| Purple | `UK` | Cross-domain bridge pattern |

Click **Save as chain** to persist the result as a new `.causal.json` file.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `⌘S` / `Ctrl+S` | Save chain |
| `Delete` / `Backspace` | Soft-delete selected node or edge |
| `Escape` | Cancel polygon lasso / close any overlay |
| `Enter` | Close polygon (≥ 3 points placed) |
| `Ctrl+click` / `Cmd+click` | Add node to selection |

---

## Chain File Format

Chains are stored as `.causal.json` files in the `chains/` folder. The format is human-readable JSON:

```
chains/
  my-chain.causal.json        ← your chain
  my-chain-seed.causal.json   ← pristine demo seed (reset-demo only)
  backups/
    my-chain_20260101T120000.causal.json
```

Seed files (`*-seed.causal.json`) are protected — they never appear in the chain switcher and cannot be edited. Use **↺ Reset demo** to restore a chain to its seed state.

---

## CLI Reference

```bash
# Open editor
python3 cli.py open chains/<name>.causal.json

# Create chain
python3 cli.py new "My Chain" --domain science

# Validate
python3 cli.py validate chains/<name>.causal.json

# LLM enrichment
python3 cli.py ask chains/<name>.causal.json "Why does X cause Y?"
python3 cli.py enrich chains/<name>.causal.json --mode gaps
python3 cli.py critique chains/<name>.causal.json

# Graph info
python3 cli.py info chains/<name>.causal.json
python3 cli.py list

# Export
python3 cli.py export chains/<name>.causal.json --format mermaid --output out.md
# Formats: json | dot | mermaid | markdown

# History and backup
python3 cli.py history chains/<name>.causal.json --last 20
python3 cli.py backup chains/<name>.causal.json
python3 cli.py diff chains/a.causal.json chains/b.causal.json
```

---

## Key Rules to Know

- **One GOAL per chain** — the `goal` node is the terminal anchor; only one is allowed
- **Assets stay off the spine** — `asset` nodes connect to tasks via `REQUIRES`/`ENABLES` only; they are never part of the main causal sequence
- **Gates need exits** — every `gate` node must have at least one `DIVERGES_TO` outbound edge
- **Nothing is truly deleted** — soft-delete sets `deprecated: true`; the history array is append-only
- **Preview nodes are temporary** — purple `⟨new⟩` nodes are display-only until you explicitly accept them; they are never saved to disk
