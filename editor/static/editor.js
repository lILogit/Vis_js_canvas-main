/**
 * editor.js — vis-network graph logic
 * Handles rendering, visual encoding, selection, edit interactions,
 * enrich preview, and soft-delete.
 */
import { markDirty, saveChain, loadChain, listChains, switchChain, resetDemo, llmAsk, llmExplain, llmContradict, llmEnrichPreview, llmIngestNote, llmSummarize, createChain, deleteChain } from './sync.js';

// ── Visual encoding constants ─────────────────────────────────────────────

const TYPE_SHAPE = {
  state:    'box',
  event:    'diamond',
  decision: 'hexagon',
  concept:  'ellipse',
  question: 'star',
  blackbox: 'question',
  // RCDE extensions
  goal:     'triangle',    // terminal anchor — desired future state
  task:     'dot',         // deliberate intervention by an agent
  asset:    'database',    // resource/capability consumed by a task
  gate:     'square',      // formally scored fork (mutually exclusive paths)
};

const RELATION_COLOR = {
  CAUSES:          '#94a3b8',  // slate-gray
  ENABLES:         '#22c55e',  // green
  BLOCKS:          '#ef4444',  // red
  TRIGGERS:        '#f59e0b',  // amber
  REDUCES:         '#4a9eed',  // blue
  REQUIRES:        '#8b5cf6',  // purple
  AMPLIFIES:       '#ec4899',  // pink
  // RCDE extensions
  PRECONDITION_OF: '#06b6d4',  // cyan — must be true before target fires
  RESOLVES:        '#10b981',  // emerald — closes an open uncertainty
  FRAMES:          '#a78bfa',  // lavender — shapes interpretation
  INSTANTIATES:    '#fbbf24',  // gold — task directly causes goal
  DIVERGES_TO:     '#fb923c',  // orange — one branch of a gate fork
};

// ── Cluster roles (edit-action oriented, 5–7 chunks cognitive load) ──────
// Priority: issues → levers → drivers → outcomes → pathway

const CLUSTER_ROLES = {
  drivers:  { label: 'Drivers',  color: '#c92a2a', shape: 'box' },
  pathway:  { label: 'Pathway',  color: '#1971c2', shape: 'ellipse' },
  outcomes: { label: 'Outcomes', color: '#2f9e44', shape: 'triangle' },
  levers:   { label: 'Levers',   color: '#e67700', shape: 'hexagon' },
  issues:   { label: 'Issues',   color: '#8b5cf6', shape: 'star' },
};

const CLUSTER_OUT_SCALE = 0.45;
const CLUSTER_IN_SCALE  = 0.65;

function confidenceColor(c) {
  // Dark-enough fills so white label text passes WCAG AA contrast
  if (c >= 0.80) return '#2f9e44';  // forest green
  if (c >= 0.60) return '#1971c2';  // blue
  if (c >= 0.40) return '#e67700';  // amber
  if (c >= 0.20) return '#e8590c';  // orange-red
  return '#c92a2a';                 // red
}

function nodeToVis(n) {
  const shape = TYPE_SHAPE[n.type] || 'box';
  const color = n.deprecated ? '#444' : confidenceColor(n.confidence);
  const borderColor = n.flagged ? '#ef4444' : (n.source === 'llm' ? '#8b5cf6' : '#555');
  const borderDashes = n.source === 'llm' ? [5, 3] : false;
  const conf = n.confidence ?? 0.5;

  const tipLines = [
    `<b>${n.label}</b>`,
    n.description ? n.description : null,
    `type: ${n.type}${n.archetype ? ' · ' + n.archetype : ''}`,
    `confidence: ${conf.toFixed(2)}  source: ${n.source || 'user'}`,
    n.flagged ? '⚑ flagged' : null,
    n.deprecated ? '(deprecated)' : null,
  ].filter(Boolean).join('<br>');

  return {
    id: n.id,
    label: n.label,
    title: tipLines,
    shape,
    color: { background: color, border: borderColor, highlight: { background: color, border: '#fff' } },
    borderWidth: n.flagged ? 3 : 2,
    borderDashes,
    opacity: n.deprecated ? 0.35 : 1,
    font: { face: 'Courier New', color: '#ffffff' },  // white on all dark confidence fills
    margin: { top: 8, bottom: 8, left: 10, right: 10 },
    widthConstraint: { minimum: 60, maximum: 140 },  // prevents text from escaping fixed-size shapes (hexagon, star)
    _raw: n,
  };
}

function edgeToVis(e) {
  const color = e.flagged ? '#ef4444' : (RELATION_COLOR[e.relation] || '#888');
  const arrowType = e.relation === 'BLOCKS' ? 'bar' : e.relation === 'DIVERGES_TO' ? 'vee' : 'arrow';
  const w = e.weight ?? 0.5;

  const tipLines = [
    `<b>${e.relation}</b>`,
    `weight: ${w.toFixed(2)}  confidence: ${(e.confidence ?? 0.5).toFixed(2)}`,
    e.condition ? `condition: ${e.condition}` : null,
    e.evidence ? e.evidence : null,
    e.flagged ? '⚑ flagged' : null,
    e.deprecated ? '(deprecated)' : null,
  ].filter(Boolean).join('<br>');

  return {
    id: e.id,
    from: e.from,
    to: e.to,
    label: e.relation,
    title: tipLines,
    width: Math.min(8, Math.max(1, w * 6)),
    color: { color, highlight: '#fff', hover: '#fff', inherit: false },
    dashes: e.deprecated,
    opacity: e.deprecated ? 0.35 : 1,
    arrows: { to: { enabled: true, scaleFactor: 0.8, type: arrowType } },
    smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.5 },
    font: { size: 11, align: 'top', color: '#bbb', strokeWidth: 0, background: 'rgba(26,26,46,0.85)' },
    _raw: e,
  };
}

// ── Network options ───────────────────────────────────────────────────────

// Single source of truth for hierarchical layout — used by both OPTIONS (initial
// render) and rerenderLayout() so they always produce identical results.
const HIERARCHICAL_LAYOUT = {
  enabled: true,
  direction: 'UD',             // up-to-down: causes at top, effects at bottom
  sortMethod: 'directed',      // follow edge direction for level assignment
  shakeTowards: 'leaves',      // align leaf nodes at the bottom (effects flush-bottom)
  levelSeparation: 180,        // vertical distance between levels
  nodeSpacing: 200,            // horizontal gap between siblings
  treeSpacing: 220,            // gap between disconnected sub-graphs
  blockShifting: true,         // shift branches to reduce horizontal whitespace
  edgeMinimization: true,      // reposition nodes to shorten total edge length
  parentCentralization: true,  // center parent nodes over their children
};

// Single source of truth for kinetic lattice physics (Kinetic Lattice pattern).
// hierarchicalRepulsion keeps the UD hierarchy intact while avoidOverlap pushes
// overlapping nodes apart — same concept as Barnes-Hut avoidOverlap in sample.
const PHYSICS_CONFIG = {
  enabled: true,
  solver: 'hierarchicalRepulsion',
  hierarchicalRepulsion: {
    nodeDistance: 200,    // repulsion radius — nodes closer than this get pushed apart
    centralGravity: 0.0,  // no central pull; hierarchy controls Y positions
    springLength: 180,    // preferred edge length
    springConstant: 0.01, // soft springs — loose, fluid feel (sample: 0.04)
    damping: 0.09,        // friction — prevents eternal vibrating (from sample)
    avoidOverlap: 1.0,    // full collision avoidance (key feature from sample)
  },
  stabilization: {
    enabled: true,
    iterations: 300,      // compute 300 physics steps before first draw (sample uses 1000)
    updateInterval: 25,   // from sample
    fit: true,
  },
};

const OPTIONS = {
  layout: { hierarchical: HIERARCHICAL_LAYOUT },
  physics: PHYSICS_CONFIG,
  edges: {
    arrows: { to: { enabled: true, scaleFactor: 0.8 } },
    smooth: { type: 'continuous', roundness: 0.5 },  // continuous curves — from sample ("cutting edge")
    font: { size: 11, align: 'top', color: '#bbb', background: 'rgba(26,26,46,0.85)' },
    color: { inherit: false },
    width: 2,
  },
  nodes: {
    font: { size: 13, face: 'Courier New', color: '#ffffff', multi: false },
    borderWidth: 2,
    shadow: true,   // depth cue — from sample
    margin: 8,
    widthConstraint: { minimum: 60, maximum: 140 },
  },
  manipulation: {
    enabled: false,                        // hide vis toolbar; we drive modes programmatically
    addNode:  (data, cb) => _openNodeModal(data, cb, true),
    editNode: (data, cb) => _openNodeModal(data, cb, false),
    addEdge:  (data, cb) => _openEdgeModal(data, cb, true),
    editEdge: { editWithoutDrag: (data, cb) => _openEdgeModal(data, cb, false) },
  },
  interaction: {
    hover: true,
    tooltipDelay: 150,
    navigationButtons: true,
    keyboard: true,
    multiselect: true,
    selectConnectedEdges: true,
  },
};

// ── App state ─────────────────────────────────────────────────────────────

let network = null;
let nodes = null;
let edges = null;
let chainData = null;
let selectedId = null;
let selectedType = null; // 'node' | 'edge'

// Preview state (enrich suggestions shown in graph but not yet committed)
let _previewNodeIds = [];
let _previewEdgeIds = [];
let _pendingSuggestions = [];

// Cluster state
let _clusteringEnabled = false;
let _activeClusters = []; // [{id, role}]

// Lasso selection state
let _lassoActive = false;
let _lassoPoints = []; // [{x, y}] in overlay-canvas DOM coords
let _lassoMousePos = null;

// ── Bootstrap ─────────────────────────────────────────────────────────────

async function checkLlmStatus() {
  const dot   = document.getElementById('llm-status-dot');
  const label = document.getElementById('llm-status-label');
  dot.className   = 'llm-dot spin';
  label.textContent = 'LLM: checking…';
  try {
    const resp = await fetch('/api/llm-status');
    const data = await resp.json();
    if (data.ok) {
      dot.className   = 'llm-dot ok';
      label.textContent = `LLM: ${data.provider} — OK`;
    } else {
      dot.className   = 'llm-dot error';
      label.textContent = `LLM: ${data.provider} — Failure`;
      label.title = data.error || '';
    }
  } catch (e) {
    dot.className   = 'llm-dot error';
    label.textContent = 'LLM: unreachable';
    label.title = String(e);
  }
}

async function init() {
  chainData = await loadChain();
  renderGraph(chainData);
  updateStatusBar();
  document.getElementById('chain-name').textContent = chainData.meta?.name || 'Untitled';
  document.title = `Causal Editor — ${chainData.meta?.name || 'Untitled'}`;

  setupToolbar();
  setupInfoPanel();
  setupFilters();
  setupKeyboard();
  setupSuggestionsPanel();
  setupLasso();

  // Load current provider from server and sync the select
  fetch('/api/llm-provider').then(r => r.json()).then(data => {
    document.getElementById('llm-provider-select').value = data.provider;
  });

  document.getElementById('llm-provider-select').addEventListener('change', async e => {
    await fetch('/api/llm-provider', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({provider: e.target.value}),
    });
    checkLlmStatus();
  });

  document.getElementById('btn-llm-recheck').addEventListener('click', checkLlmStatus);
  checkLlmStatus();
}

function renderGraph(data) {
  // Reset clustering before layout so clusters don't interfere with hierarchical recalc
  _clusteringEnabled = false;
  _activeClusters = [];
  document.getElementById('btn-cluster')?.classList.remove('active');

  const visNodes = (data.nodes || []).filter(n => !n.deprecated).map(nodeToVis);
  const visEdges = (data.edges || []).map(edgeToVis);
  showChainPanel();

  if (network) {
    // Show overlay to hide the clear/add flash and layout computation,
    // matching the page-refresh pattern (overlay hides → CSS fade reveals graph).
    const loadingEl = document.getElementById('graph-loading');
    if (loadingEl) loadingEl.style.opacity = '1';
    network.setOptions({ layout: { hierarchical: HIERARCHICAL_LAYOUT } });
    nodes.clear();
    edges.clear();
    nodes.add(visNodes);
    edges.add(visEdges);
    let _switchDone = false;
    function _finishSwitch() {
      if (_switchDone) return;
      _switchDone = true;
      network.setOptions({ layout: { hierarchical: { enabled: false } } });
      network.fit(); // instant while overlay is still covering the canvas
      if (loadingEl) loadingEl.style.opacity = '0'; // CSS transition fades graph in
    }
    network.once('stabilized', _finishSwitch);
    setTimeout(_finishSwitch, 150); // fallback if stabilized is suppressed
    return;
  }

  nodes = new vis.DataSet(visNodes);
  edges = new vis.DataSet(visEdges);

  network = new vis.Network(
    document.getElementById('graph'),
    { nodes, edges },
    OPTIONS
  );

  // After physics stabilizes: lock positions, reveal graph (same overlay-fade pattern
  // used by chain switch and rerenderLayout). once() ensures this fires only for the
  // initial load — not for any subsequent stabilized events from menu actions.
  let _hideLoadingDone = false;
  let _hideLoadingFallback;
  function _hideLoading() {
    if (_hideLoadingDone) return;
    _hideLoadingDone = true;
    clearTimeout(_hideLoadingFallback);
    network.setOptions({ physics: { enabled: false }, layout: { hierarchical: { enabled: false } } });
    network.fit(); // instant — overlay is still visible, CSS transition reveals graph
    const el = document.getElementById('graph-loading');
    if (el) el.style.opacity = '0';
  }
  network.once('stabilizationIterationsDone', _hideLoading);
  network.once('stabilized', _hideLoading);
  _hideLoadingFallback = setTimeout(_hideLoading, 3000);

  network.on('zoom', handleZoomClustering);

  network.on('selectNode', ({ nodes: sel }) => {
    if (!sel.length) return;
    // Open cluster on click
    if (network.isCluster(sel[0])) { network.openCluster(sel[0]); _activeClusters = _activeClusters.filter(c => c.id !== sel[0]); return; }
    // Ignore clicks on preview nodes
    if (String(sel[0]).startsWith('_preview_')) return;
    selectedId = sel[0];
    selectedType = 'node';
    const raw = chainData.nodes.find(n => n.id === selectedId);
    showNodePanel(raw);
  });

  network.on('selectEdge', ({ edges: sel, nodes: selNodes }) => {
    if (selNodes.length > 0) return;
    if (!sel.length) return;
    if (String(sel[0]).startsWith('_preview_')) return;
    selectedId = sel[0];
    selectedType = 'edge';
    const raw = chainData.edges.find(e => e.id === selectedId);
    showEdgePanel(raw);
  });

  network.on('deselectNode', () => {
    selectedId = null;
    selectedType = null;
    showChainPanel();
  });

  network.on('deselectEdge', () => {
    selectedId = null;
    selectedType = null;
    showChainPanel();
  });

  // Double-click → open edit modal for node or edge
  network.on('doubleClick', ({ nodes: sel, edges: esel }) => {
    if (sel.length > 0) {
      if (String(sel[0]).startsWith('_preview_')) return;
      network.editNode();   // triggers editNode manipulation callback
    } else if (esel.length > 0) {
      if (String(esel[0]).startsWith('_preview_')) return;
      const raw = chainData.edges.find(e => e.id === esel[0]);
      if (!raw) return;
      _openEdgeModal(
        { id: raw.id, from: raw.from ?? raw.from_id, to: raw.to ?? raw.to_id },
        () => {},
        false,
      );
    }
  });
}

// ── Info panel ────────────────────────────────────────────────────────────

function showChainPanel() {
  if (!chainData) return;
  const m = chainData.meta || {};
  document.getElementById('info-content').innerHTML = `
    <div class="chain-panel">
      <div class="cp-row">
        <span class="cp-label">Chain</span>
        <span class="cp-value">${esc(m.name || 'Untitled')}</span>
      </div>
      <div class="cp-row">
        <span class="cp-label">Domain</span>
        <span class="cp-value">${esc(m.domain || '')}</span>
      </div>
      <div class="cp-notes">
        <label class="cp-label" for="cp-notes-ta">Notes</label>
        <textarea id="cp-notes-ta" rows="6" placeholder="Add notes about this chain…">${esc(m.description || '')}</textarea>
      </div>
    </div>`;
  document.getElementById('cp-notes-ta').addEventListener('input', e => {
    chainData.meta.description = e.target.value;
    markDirty();
  });
}

function clearInfoPanel() {
  document.getElementById('info-content').innerHTML =
    '<p style="color:#666;font-size:12px;">Click a node or edge to inspect.</p>';
  document.getElementById('llm-response').classList.remove('visible');
}

function showNodePanel(n) {
  if (!n) return;
  const c = document.getElementById('info-content');
  c.innerHTML = `
    <div class="field">
      <label>ID</label>
      <input value="${esc(n.id)}" readonly style="opacity:0.5">
    </div>
    <div class="field">
      <label>Label</label>
      <input id="pi-label" value="${esc(n.label)}" placeholder="Short name (≤20 chars)">
    </div>
    <div class="field">
      <label>Type</label>
      <select id="pi-type">
        ${['state','event','decision','concept','question','blackbox','goal','task','asset','gate']
          .map(t => `<option value="${t}" ${n.type===t?'selected':''}>${t}</option>`).join('')}
      </select>
    </div>
    <div class="field">
      <label>Description</label>
      <textarea id="pi-desc">${esc(n.description || '')}</textarea>
    </div>
    <div class="field">
      <label>Confidence — <span id="pi-conf-val">${n.confidence.toFixed(2)}</span></label>
      <div class="confidence-row">
        <input type="range" id="pi-conf" min="0" max="1" step="0.05" value="${n.confidence}">
      </div>
    </div>
    <div class="field">
      <label>Source</label>
      <input value="${n.source}" readonly style="opacity:0.5">
    </div>
    <div class="llm-actions">
      <button id="btn-explain">Explain this node</button>
      <button id="btn-ask-llm">Ask LLM...</button>
      <button id="btn-flag" class="${n.flagged ? 'danger' : ''}">${n.flagged ? 'Unflag' : 'Flag for review'}</button>
      <button id="btn-apply-node">Apply changes</button>
      <button id="btn-delete-node" class="danger">Delete node</button>
    </div>
  `;

  document.getElementById('pi-conf').addEventListener('input', e => {
    document.getElementById('pi-conf-val').textContent = parseFloat(e.target.value).toFixed(2);
  });
  document.getElementById('btn-apply-node').addEventListener('click', () => applyNodeEdits(n.id));
  document.getElementById('btn-explain').addEventListener('click', () => runExplain(n.id));
  document.getElementById('btn-ask-llm').addEventListener('click', () => showAskDialog(n.id));
  document.getElementById('btn-flag').addEventListener('click', () => toggleFlag(n.id, 'node'));
  document.getElementById('btn-delete-node').addEventListener('click', () => deleteSelected());
}

function showEdgePanel(e) {
  if (!e) return;
  const c = document.getElementById('info-content');
  c.innerHTML = `
    <div class="field">
      <label>ID</label>
      <input value="${esc(e.id)}" readonly style="opacity:0.5">
    </div>
    <div class="field">
      <label>From → To</label>
      <input value="${esc(e.from)} → ${esc(e.to)}" readonly style="opacity:0.5">
    </div>
    <div class="field">
      <label>Relation</label>
      <select id="pe-relation">
        ${['CAUSES','ENABLES','BLOCKS','TRIGGERS','REDUCES','REQUIRES','AMPLIFIES',
           'PRECONDITION_OF','RESOLVES','FRAMES','INSTANTIATES','DIVERGES_TO']
          .map(r => `<option value="${r}" ${e.relation===r?'selected':''}>${r}</option>`).join('')}
      </select>
    </div>
    <div class="field">
      <label>Weight — <span id="pe-w-val">${e.weight.toFixed(2)}</span></label>
      <div class="confidence-row">
        <input type="range" id="pe-weight" min="0" max="1" step="0.05" value="${e.weight}">
      </div>
    </div>
    <div class="field">
      <label>Evidence</label>
      <textarea id="pe-evidence">${esc(e.evidence || '')}</textarea>
    </div>
    <div class="field">
      <label>Condition</label>
      <input id="pe-condition" value="${esc(e.condition || '')}" placeholder="Under what condition?">
    </div>
    <div class="llm-actions">
      <button id="btn-contradict">Check contradiction...</button>
      <button id="btn-flag-edge" class="${e.flagged ? 'danger' : ''}">${e.flagged ? 'Unflag' : 'Flag'}</button>
      <button id="btn-apply-edge">Apply changes</button>
      <button id="btn-delete-edge" class="danger">Delete edge</button>
    </div>
  `;

  document.getElementById('pe-weight').addEventListener('input', ev => {
    document.getElementById('pe-w-val').textContent = parseFloat(ev.target.value).toFixed(2);
  });
  document.getElementById('btn-apply-edge').addEventListener('click', () => applyEdgeEdits(e.id));
  document.getElementById('btn-contradict').addEventListener('click', () => showContradictDialog(e.id));
  document.getElementById('btn-flag-edge').addEventListener('click', () => toggleFlag(e.id, 'edge'));
  document.getElementById('btn-delete-edge').addEventListener('click', () => deleteSelected());
}

// ── Edit helpers ──────────────────────────────────────────────────────────

function applyNodeEdits(nodeId) {
  const node = chainData.nodes.find(n => n.id === nodeId);
  if (!node) return;
  node.label = document.getElementById('pi-label').value.trim();
  node.type = document.getElementById('pi-type').value;
  node.description = document.getElementById('pi-desc').value;
  node.confidence = parseFloat(document.getElementById('pi-conf').value);
  nodes.update(nodeToVis(node));
  markDirty();
  updateStatusBar();
}

function applyEdgeEdits(edgeId) {
  const edge = chainData.edges.find(e => e.id === edgeId);
  if (!edge) return;
  edge.relation = document.getElementById('pe-relation').value;
  edge.weight = parseFloat(document.getElementById('pe-weight').value);
  edge.evidence = document.getElementById('pe-evidence').value;
  edge.condition = document.getElementById('pe-condition').value || null;
  edges.update(edgeToVis(edge));
  markDirty();
}

function toggleFlag(id, type) {
  const items = type === 'node' ? chainData.nodes : chainData.edges;
  const item = items.find(i => i.id === id);
  if (!item) return;
  item.flagged = !item.flagged;
  if (type === 'node') nodes.update(nodeToVis(item));
  else edges.update(edgeToVis(item));
  markDirty();
  if (type === 'node') showNodePanel(item);
  else showEdgePanel(item);
}

// ── Delete (soft) ─────────────────────────────────────────────────────────

function deleteSelected() {
  if (!selectedId) return;

  const label = selectedType === 'node'
    ? (chainData.nodes.find(n => n.id === selectedId)?.label || selectedId)
    : selectedId;

  if (!confirm(`Delete ${selectedType} "${label}"?\n(Soft-delete: sets deprecated=true)`)) return;

  if (selectedType === 'node') {
    const node = chainData.nodes.find(n => n.id === selectedId);
    if (!node) return;
    node.deprecated = true;
    nodes.remove(selectedId);
    // Deprecate all connected edges
    chainData.edges.forEach(e => {
      if ((e.from === selectedId || e.to === selectedId || e.from_id === selectedId || e.to_id === selectedId) && !e.deprecated) {
        e.deprecated = true;
        edges.remove(e.id);
      }
    });
    chainData.history.push({
      timestamp: new Date().toISOString(),
      action: 'node_edit',
      actor: 'user',
      payload: { id: selectedId, deprecated: true },
    });
  } else {
    const edge = chainData.edges.find(e => e.id === selectedId);
    if (!edge) return;
    edge.deprecated = true;
    edges.remove(selectedId);
    chainData.history.push({
      timestamp: new Date().toISOString(),
      action: 'edge_edit',
      actor: 'user',
      payload: { id: selectedId, deprecated: true },
    });
  }

  selectedId = null;
  selectedType = null;
  clearInfoPanel();
  markDirty();
  updateStatusBar();
}

// ── Manipulation modals ────────────────────────────────────────────────────

const _NODE_TYPES = ['state','event','decision','concept','question','blackbox','goal','task','asset','gate'];
const _RELATIONS  = ['CAUSES','ENABLES','BLOCKS','TRIGGERS','REDUCES','REQUIRES','AMPLIFIES',
                     'PRECONDITION_OF','RESOLVES','FRAMES','INSTANTIATES','DIVERGES_TO'];

// Populate selects once on module load
(function _initManipSelects() {
  const typeEl = document.getElementById('mn-type');
  _NODE_TYPES.forEach(t => { const o = document.createElement('option'); o.value = t; o.textContent = t; typeEl.appendChild(o); });
  const relEl = document.getElementById('me-relation');
  _RELATIONS.forEach(r => { const o = document.createElement('option'); o.value = r; o.textContent = r; relEl.appendChild(o); });
})();

function _openNodeModal(visData, callback, isNew) {
  const overlay = document.getElementById('manip-node-overlay');
  document.getElementById('mn-title').textContent = isNew ? 'Add Node' : 'Edit Node';
  document.getElementById('mn-hint').textContent = isNew ? 'Fill details then Apply to place node.' : '';

  // Populate from chainData for edits; use defaults for new
  const existing = !isNew && chainData.nodes.find(n => n.id === visData.id);
  document.getElementById('mn-label').value      = existing?.label       ?? '';
  document.getElementById('mn-type').value       = existing?.type        ?? 'state';
  document.getElementById('mn-desc').value       = existing?.description ?? '';
  document.getElementById('mn-archetype').value  = existing?.archetype   ?? '';
  document.getElementById('mn-flagged').checked  = existing?.flagged     ?? false;
  const conf = existing?.confidence ?? 0.7;
  document.getElementById('mn-conf').value       = conf;
  document.getElementById('mn-conf-val').textContent = conf.toFixed(2);

  overlay.style.display = '';
  document.getElementById('mn-label').focus();

  document.getElementById('mn-conf').oninput = e =>
    (document.getElementById('mn-conf-val').textContent = parseFloat(e.target.value).toFixed(2));

  function _apply() {
    const label = document.getElementById('mn-label').value.trim();
    if (!label) { document.getElementById('mn-label').focus(); return; }
    cleanup();
    overlay.style.display = 'none';

    const fields = {
      label,
      type:        document.getElementById('mn-type').value,
      description: document.getElementById('mn-desc').value.trim(),
      archetype:   document.getElementById('mn-archetype').value || null,
      confidence:  parseFloat(document.getElementById('mn-conf').value),
      flagged:     document.getElementById('mn-flagged').checked,
    };

    if (isNew) {
      const id = shortId();
      const newNode = { id, ...fields, tags: [], source: 'user', deprecated: false, created_at: new Date().toISOString() };
      chainData.nodes.push(newNode);
      chainData.history.push({ timestamp: newNode.created_at, action: 'node_add', actor: 'user', payload: { node_id: id } });
      nodes.add({ ...nodeToVis(newNode), x: visData.x, y: visData.y });
      callback(null);   // cancel vis's own add — we've placed it manually
    } else {
      const n = chainData.nodes.find(n => n.id === visData.id);
      if (n) Object.assign(n, fields);
      nodes.update(nodeToVis(n ?? { id: visData.id, ...fields }));
      chainData.history.push({ timestamp: new Date().toISOString(), action: 'node_edit', actor: 'user', payload: { node_id: visData.id } });
      callback(null);
    }
    markDirty();
    updateStatusBar();
  }

  function _cancel() {
    cleanup();
    overlay.style.display = 'none';
    callback(null);
  }

  function _onKey(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); _apply(); }
    if (e.key === 'Escape') { e.preventDefault(); _cancel(); }
  }

  function cleanup() {
    document.getElementById('mn-apply').onclick  = null;
    document.getElementById('mn-cancel').onclick = null;
    document.removeEventListener('keydown', _onKey);
  }

  document.getElementById('mn-apply').onclick  = _apply;
  document.getElementById('mn-cancel').onclick = _cancel;
  document.addEventListener('keydown', _onKey);
}

function _openEdgeModal(visData, callback, isNew) {
  const overlay = document.getElementById('manip-edge-overlay');
  document.getElementById('me-title').textContent = isNew ? 'Add Edge' : 'Edit Edge';

  // Show from → to labels
  const fromLabel = chainData.nodes.find(n => n.id === visData.from)?.label ?? visData.from ?? '';
  const toLabel   = chainData.nodes.find(n => n.id === visData.to)?.label   ?? visData.to   ?? '';
  document.getElementById('me-endpoints').value = `${fromLabel}  →  ${toLabel}`;

  const existing = !isNew && chainData.edges.find(e => e.id === visData.id);
  document.getElementById('me-relation').value  = existing?.relation  ?? 'CAUSES';
  document.getElementById('me-evidence').value  = existing?.evidence  ?? '';
  document.getElementById('me-condition').value = existing?.condition ?? '';
  const w = existing?.weight ?? 0.5;
  document.getElementById('me-weight').value = w;
  document.getElementById('me-weight-val').textContent = w.toFixed(2);

  overlay.style.display = '';

  document.getElementById('me-weight').oninput = e =>
    (document.getElementById('me-weight-val').textContent = parseFloat(e.target.value).toFixed(2));

  function _apply() {
    cleanup();
    overlay.style.display = 'none';

    const fields = {
      relation:  document.getElementById('me-relation').value,
      weight:    parseFloat(document.getElementById('me-weight').value),
      evidence:  document.getElementById('me-evidence').value.trim(),
      condition: document.getElementById('me-condition').value.trim() || null,
    };

    if (isNew) {
      const id = shortId();
      const newEdge = {
        id, from: visData.from, to: visData.to, ...fields,
        confidence: 0.5, direction: 'forward',
        deprecated: false, flagged: false, version: 1,
        source: 'user', created_at: new Date().toISOString(),
      };
      chainData.edges.push(newEdge);
      chainData.history.push({ timestamp: newEdge.created_at, action: 'edge_add', actor: 'user', payload: { edge_id: id } });
      edges.add(edgeToVis(newEdge));
      callback(null);
    } else {
      const e = chainData.edges.find(e => e.id === visData.id);
      if (e) Object.assign(e, fields);
      edges.update(edgeToVis(e ?? { id: visData.id, from: visData.from, to: visData.to, ...fields }));
      chainData.history.push({ timestamp: new Date().toISOString(), action: 'edge_edit', actor: 'user', payload: { edge_id: visData.id } });
      callback(null);
    }
    markDirty();
  }

  function _cancel() {
    cleanup();
    overlay.style.display = 'none';
    callback(null);
  }

  function _onKey(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); _apply(); }
    if (e.key === 'Escape') { e.preventDefault(); _cancel(); }
  }

  function cleanup() {
    document.getElementById('me-apply').onclick  = null;
    document.getElementById('me-cancel').onclick = null;
    document.removeEventListener('keydown', _onKey);
  }

  document.getElementById('me-apply').onclick  = _apply;
  document.getElementById('me-cancel').onclick = _cancel;
  document.addEventListener('keydown', _onKey);
}

function shortId() {
  return Math.random().toString(16).slice(2, 10);
}

// ── Enrich preview ────────────────────────────────────────────────────────

function clearPreviewItems() {
  try { nodes.remove(_previewNodeIds); } catch (_) {}
  try { edges.remove(_previewEdgeIds); } catch (_) {}
  _previewNodeIds = [];
  _previewEdgeIds = [];
}

function addPreviewToGraph(suggestions) {
  clearPreviewItems();

  // Build label→id map: new import_node previews + existing chain nodes (by label)
  const importLabelMap = {};
  // Seed with existing nodes so edges to/from known nodes resolve correctly
  if (chainData?.nodes) {
    for (const n of chainData.nodes) {
      if (!n.deprecated) importLabelMap[n.label] = n.id;
    }
  }
  // New preview nodes override (give them their preview ids)
  suggestions.forEach((s, i) => {
    if (s.kind === 'import_node') importLabelMap[s.label] = `_preview_node_${i}`;
  });

  for (let i = 0; i < suggestions.length; i++) {
    const s = suggestions[i];

    if (s.kind === 'import_node') {
      const nId = `_preview_node_${i}`;
      nodes.add({
        id: nId,
        label: `⟨new⟩ ${s.label}`,
        title: s.description || s.label,
        shape: TYPE_SHAPE[s.node_type] || 'box',
        color: {
          background: '#2d1b4e',
          border: '#8b5cf6',
          highlight: { background: '#3b2466', border: '#a78bfa' },
        },
        borderWidth: 2,
        borderDashes: [6, 3],
        font: { size: 13, face: 'Courier New', color: '#c4b5fd' },
      });
      _previewNodeIds.push(nId);

    } else if (s.kind === 'import_edge') {
      const fromId = importLabelMap[s.connects_from_label] || s._from_ref;
      const toId   = importLabelMap[s.connects_to_label]   || s._to_ref;
      if (!fromId || !toId) continue;
      const eId = `_preview_edge_${i}`;
      edges.add({
        id: eId, from: fromId, to: toId,
        label: s.relation || 'CAUSES',
        color: { color: '#8b5cf6', inherit: false },
        dashes: [6, 3], width: 2,
        arrows: { to: { enabled: true, scaleFactor: 0.8 } },
        font: { size: 10, color: '#8b5cf6' },
      });
      _previewEdgeIds.push(eId);

    } else if (s.kind === 'gap_node' && s.connects_from && s.connects_to) {
      const nId = `_preview_node_${i}`;
      nodes.add({
        id: nId,
        label: `⟨new⟩ ${s.label}`,
        title: s.reasoning,
        shape: TYPE_SHAPE[s.node_type] || 'box',
        color: {
          background: '#2d1b4e',
          border: '#8b5cf6',
          highlight: { background: '#3b2466', border: '#a78bfa' },
        },
        borderWidth: 2,
        borderDashes: [6, 3],
        font: { size: 13, face: 'Courier New', color: '#c4b5fd' },
      });
      _previewNodeIds.push(nId);

      const eaId = `_preview_edge_${i}_a`;
      edges.add({
        id: eaId, from: s.connects_from, to: nId,
        label: 'CAUSES',
        color: { color: '#8b5cf6', inherit: false },
        dashes: [6, 3], width: 2,
        arrows: { to: { enabled: true, scaleFactor: 0.8 } },
        font: { size: 10, color: '#8b5cf6' },
      });
      _previewEdgeIds.push(eaId);

      const ebId = `_preview_edge_${i}_b`;
      edges.add({
        id: ebId, from: nId, to: s.connects_to,
        label: 'CAUSES',
        color: { color: '#8b5cf6', inherit: false },
        dashes: [6, 3], width: 2,
        arrows: { to: { enabled: true, scaleFactor: 0.8 } },
        font: { size: 10, color: '#8b5cf6' },
      });
      _previewEdgeIds.push(ebId);

    } else if (s.kind === 'edge' && s.connects_from && s.connects_to) {
      const eId = `_preview_edge_${i}`;
      edges.add({
        id: eId, from: s.connects_from, to: s.connects_to,
        label: s.relation || 'CAUSES',
        title: s.reasoning,
        color: { color: '#8b5cf6', inherit: false },
        dashes: [6, 3], width: 2,
        arrows: { to: { enabled: true, scaleFactor: 0.8 } },
        font: { size: 10, color: '#8b5cf6' },
      });
      _previewEdgeIds.push(eId);

    } else {
      // Standalone node with no known connections
      const nId = `_preview_node_${i}`;
      nodes.add({
        id: nId,
        label: `⟨new⟩ ${s.label}`,
        title: s.reasoning,
        shape: TYPE_SHAPE[s.node_type] || 'box',
        color: { background: '#2d1b4e', border: '#8b5cf6' },
        borderWidth: 2,
        borderDashes: [6, 3],
        font: { size: 13, face: 'Courier New', color: '#c4b5fd' },
      });
      _previewNodeIds.push(nId);
    }
  }
}

function rerenderLayout() {
  if (!network) return;
  // Clear clusters before hierarchical layout recalculation
  declusAll();
  _clusteringEnabled = false;
  document.getElementById('btn-cluster')?.classList.remove('active');
  // Same overlay-fade pattern as page refresh and chain switch:
  // overlay hides computation → instant fit → CSS transition reveals graph.
  const loadingEl = document.getElementById('graph-loading');
  if (loadingEl) loadingEl.style.opacity = '1';
  network.setOptions({ layout: { hierarchical: HIERARCHICAL_LAYOUT } });
  let _layoutDone = false;
  function _finishLayout() {
    if (_layoutDone) return;
    _layoutDone = true;
    network.setOptions({ layout: { hierarchical: { enabled: false } } });
    network.fit();
    if (loadingEl) loadingEl.style.opacity = '0';
  }
  network.once('stabilized', _finishLayout);
  setTimeout(_finishLayout, 150);
}

async function applyPreviewSuggestions(selectedIndices) {
  const now = new Date().toISOString();

  // First pass: apply all import_node items and build label→realId map
  const importLabelToId = {};
  for (const i of selectedIndices) {
    const s = _pendingSuggestions[i];
    if (s?.kind === 'import_node') {
      const id = shortId();
      const node = { id, label: s.label, description: s.description || '', type: s.node_type || 'state', confidence: 0.7, source: 'llm', deprecated: false, flagged: false, tags: [], created_at: now };
      chainData.nodes.push(node);
      nodes.add(nodeToVis(node));
      chainData.history.push({ timestamp: now, action: 'node_add', actor: 'llm', payload: { node_id: id } });
      importLabelToId[s.label] = id;
    }
  }

  for (const i of selectedIndices) {
    const s = _pendingSuggestions[i];
    if (!s) continue;

    if (s.kind === 'import_node') {
      continue; // already applied above

    } else if (s.kind === 'import_edge') {
      // Resolve: 1) newly-created node label, 2) existing node by label, 3) raw node_id ref
      const existingByLabel = (label) => chainData.nodes.find(n => !n.deprecated && n.label === label)?.id;
      const fromId = importLabelToId[s.connects_from_label]
                  || existingByLabel(s.connects_from_label)
                  || s._from_ref;
      const toId   = importLabelToId[s.connects_to_label]
                  || existingByLabel(s.connects_to_label)
                  || s._to_ref;
      if (!fromId || !toId) continue;
      const edge = { id: shortId(), from: fromId, to: toId, relation: s.relation || 'CAUSES', weight: s.weight || 0.7, confidence: 0.7, direction: 'forward', condition: null, evidence: '', deprecated: false, flagged: false, version: 1, source: 'llm', created_at: now };
      chainData.edges.push(edge);
      edges.add(edgeToVis(edge));
      chainData.history.push({ timestamp: now, action: 'edge_add', actor: 'llm', payload: { edge_id: edge.id } });

    } else if (s.kind === 'gap_node' && s.connects_from && s.connects_to) {
      const id = shortId();
      const node = {
        id, label: s.label, description: s.description || '', type: s.node_type || 'state',
        confidence: 0.7, source: 'llm', deprecated: false, flagged: false,
        tags: [], created_at: now,
      };
      chainData.nodes.push(node);
      nodes.add(nodeToVis(node));

      const e1 = { id: shortId(), from: s.connects_from, to: id, relation: 'CAUSES', weight: 0.5, confidence: 0.5, direction: 'forward', condition: null, evidence: '', deprecated: false, flagged: false, version: 1, source: 'llm', created_at: now };
      const e2 = { id: shortId(), from: id, to: s.connects_to, relation: 'CAUSES', weight: 0.5, confidence: 0.5, direction: 'forward', condition: null, evidence: '', deprecated: false, flagged: false, version: 1, source: 'llm', created_at: now };
      chainData.edges.push(e1, e2);
      edges.add(edgeToVis(e1));
      edges.add(edgeToVis(e2));

      chainData.history.push({ timestamp: now, action: 'enrich', actor: 'llm', payload: { type: 'gap', node_id: id } });

    } else if (s.kind === 'edge' && s.connects_from && s.connects_to) {
      const edge = { id: shortId(), from: s.connects_from, to: s.connects_to, relation: s.relation || 'CAUSES', weight: 0.5, confidence: 0.5, direction: 'forward', condition: null, evidence: '', deprecated: false, flagged: false, version: 1, source: 'llm', created_at: now };
      chainData.edges.push(edge);
      edges.add(edgeToVis(edge));
      chainData.history.push({ timestamp: now, action: 'edge_add', actor: 'llm', payload: { edge_id: edge.id } });

    } else if (s.label) {
      const id = shortId();
      const node = { id, label: s.label, description: s.description || '', type: s.node_type || 'state', confidence: 0.7, source: 'llm', deprecated: false, flagged: false, tags: [], created_at: now };
      chainData.nodes.push(node);
      nodes.add(nodeToVis(node));
      chainData.history.push({ timestamp: now, action: 'node_add', actor: 'llm', payload: { node_id: id } });
    }
  }

  clearPreviewItems();
  _pendingSuggestions = [];
  updateStatusBar();

  // Re-run hierarchical layout so new nodes get proper positions, then fit
  rerenderLayout();

  // Auto-save immediately
  setStatus('saving…', 'dirty');
  try {
    await saveChain(chainData);
    setStatus('saved');
  } catch (err) {
    setStatus('save error: ' + err.message, 'error');
  }
}

async function runEnrich(mode = 'gaps') {
  clearPreviewItems();
  document.getElementById('suggestions-overlay').classList.remove('visible');

  const selIds = (network?.getSelectedNodes() || []).filter(id => !String(id).startsWith('_preview_'));
  const scope = selIds.length ? `${selIds.length} selected node${selIds.length > 1 ? 's' : ''}` : 'chain';
  showLlmLoading(`Analyzing ${scope} (mode: ${mode})...`);
  try {
    const r = await llmEnrichPreview(mode, selIds.length ? selIds : null);
    _pendingSuggestions = r.suggestions || [];

    if (!_pendingSuggestions.length) {
      showLlmResult('No suggestions found.');
      return;
    }

    addPreviewToGraph(_pendingSuggestions);
    showSuggestionsOverlay(_pendingSuggestions);
    showLlmResult(`${_pendingSuggestions.length} suggestion(s) shown in graph (purple dashed). Review in the panel.`);
  } catch (e) {
    showLlmResult('Error: ' + e.message);
  }
}


async function runIngestNote(noteData) {
  clearPreviewItems();
  document.getElementById('suggestions-overlay').classList.remove('visible');

  showLlmLoading('Ingesting note…');
  try {
    const r = await llmIngestNote(noteData);
    _pendingSuggestions = r.suggestions || [];
    const ws = r.w_score ?? 0;
    const classification = r.classification || {};

    if (!_pendingSuggestions.length) {
      showLlmResult('No new graph elements generated from this note.');
      return;
    }

    addPreviewToGraph(_pendingSuggestions);

    // Highlight known entities in graph
    const knownIds = (classification.known || [])
      .map(k => k.node_id)
      .filter(id => id && network.body.nodes[id]);
    if (knownIds.length) network.selectNodes(knownIds);

    showSuggestionsOverlay(_pendingSuggestions, ws);
    showLlmResult(`W-score: ${ws.toFixed(2)} | ${_pendingSuggestions.length} item(s) proposed.`);
  } catch (e) {
    showLlmResult('Error: ' + e.message);
  }
}

function showSuggestionsOverlay(suggestions, wScore = null) {
  const overlay = document.getElementById('suggestions-overlay');
  const list = document.getElementById('suggestions-list');

  // W-score badge in header (if provided)
  const header = overlay.querySelector('.suggestions-header h3');
  if (header) {
    const existingBadge = header.querySelector('.wscore-badge');
    if (existingBadge) existingBadge.remove();
    if (wScore !== null) {
      const cls = wScore >= 0.7 ? 'wscore-high' : wScore >= 0.4 ? 'wscore-med' : 'wscore-low';
      const badge = document.createElement('span');
      badge.className = `wscore-badge ${cls}`;
      badge.style.marginLeft = '8px';
      badge.style.fontSize = '11px';
      badge.textContent = `W: ${wScore.toFixed(2)}`;
      header.appendChild(badge);
    }
  }

  list.innerHTML = suggestions.map((s, i) => {
    const kindTag = `<span class="s-badge">${s.kind === 'gap_node' ? 'gap node' : s.kind}</span>`;
    const klassTag = s.klass ? `<span class="klass-badge klass-${s.klass.toLowerCase()}">${s.klass}</span>` : '';
    return `
      <div class="suggestion-item">
        <label>
          <input type="checkbox" class="s-check" data-idx="${i}" checked>
          <span class="s-label">${esc(s.label)}</span>
          ${kindTag}${klassTag}
        </label>
        ${s.connects_from ? `<div class="s-connects">${esc(s.connects_from)} → [new] → ${esc(s.connects_to)}</div>` : ''}
        <div class="s-reason">${esc(s.reasoning || '')}</div>
      </div>`;
  }).join('');

  overlay.classList.add('visible');
}


function setupSuggestionsPanel() {
  document.getElementById('btn-s-accept').addEventListener('click', async () => {
    const checks = document.querySelectorAll('.s-check');
    const selected = [];
    checks.forEach(cb => { if (cb.checked) selected.push(parseInt(cb.dataset.idx)); });
    document.getElementById('suggestions-overlay').classList.remove('visible');
    showLlmLoading(`Applying ${selected.length} suggestion(s)...`);
    await applyPreviewSuggestions(selected);
    showLlmResult(`Applied ${selected.length} suggestion(s) — saved.`);
  });

  document.getElementById('btn-s-reject').addEventListener('click', () => {
    clearPreviewItems();
    _pendingSuggestions = [];
    document.getElementById('suggestions-overlay').classList.remove('visible');
    showLlmResult('All suggestions rejected.');
  });

  document.getElementById('btn-s-close').addEventListener('click', () => {
    document.getElementById('suggestions-overlay').classList.remove('visible');
  });
}

// ── Filters ───────────────────────────────────────────────────────────────

function setupFilters() {
  const typeFilter = document.getElementById('filter-type');
  const confFilter = document.getElementById('filter-conf');
  const confVal = document.getElementById('filter-conf-val');
  const sourceFilter = document.getElementById('filter-source');
  const flaggedOnly = document.getElementById('filter-flagged');

  function applyFilters() {
    const typeVal = typeFilter.value;
    const minConf = parseFloat(confFilter.value);
    const sourceVal = sourceFilter.value;
    const flagged = flaggedOnly.checked;

    confVal.textContent = minConf.toFixed(1);

    const visNodes = chainData.nodes.filter(n => {
      if (n.deprecated) return false;
      if (typeVal !== 'all' && n.type !== typeVal) return false;
      if (n.confidence < minConf) return false;
      if (sourceVal !== 'all' && n.source !== sourceVal) return false;
      if (flagged && !n.flagged) return false;
      return true;
    }).map(nodeToVis);

    const visNodeIds = new Set(visNodes.map(n => n.id));
    const visEdges = chainData.edges.filter(e => {
      if (e.deprecated) return false;
      const fromId = e.from || e.from_id;
      const toId = e.to || e.to_id;
      return visNodeIds.has(fromId) && visNodeIds.has(toId);
    }).map(edgeToVis);

    nodes.clear();
    edges.clear();
    nodes.add(visNodes);
    edges.add(visEdges);
    // Re-add any active preview items
    if (_previewNodeIds.length) addPreviewToGraph(_pendingSuggestions);
  }

  typeFilter.addEventListener('change', applyFilters);
  confFilter.addEventListener('input', applyFilters);
  sourceFilter.addEventListener('change', applyFilters);
  flaggedOnly.addEventListener('change', applyFilters);
}

// ── Lasso polygon selection ───────────────────────────────────────────────

function activateLasso() {
  if (!network) return;
  _lassoActive = true;
  _lassoPoints = [];
  _lassoMousePos = null;
  const canvas = document.getElementById('lasso-canvas');
  const wrap = document.getElementById('graph-wrap');
  canvas.width = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
  canvas.classList.add('active');
  document.getElementById('btn-lasso').classList.add('active');
  network.setOptions({ interaction: { keyboard: false } });
}

function deactivateLasso() {
  _lassoActive = false;
  _lassoPoints = [];
  _lassoMousePos = null;
  const canvas = document.getElementById('lasso-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  canvas.classList.remove('active');
  document.getElementById('btn-lasso').classList.remove('active');
  if (network) network.setOptions({ interaction: { keyboard: true } });
}

function drawLasso() {
  const canvas = document.getElementById('lasso-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!_lassoPoints.length) return;

  ctx.beginPath();
  ctx.moveTo(_lassoPoints[0].x, _lassoPoints[0].y);
  for (let i = 1; i < _lassoPoints.length; i++) ctx.lineTo(_lassoPoints[i].x, _lassoPoints[i].y);

  // Rubber-band line to current mouse
  if (_lassoMousePos) ctx.lineTo(_lassoMousePos.x, _lassoMousePos.y);

  ctx.closePath();
  ctx.fillStyle = 'rgba(139,92,246,0.12)';
  ctx.fill();
  ctx.setLineDash([6, 3]);
  ctx.strokeStyle = '#8b5cf6';
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.setLineDash([]);

  // Vertex dots
  ctx.fillStyle = '#a78bfa';
  for (const pt of _lassoPoints) {
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function pointInPolygon(px, py, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i].x, yi = pts[i].y, xj = pts[j].x, yj = pts[j].y;
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

function finishLasso() {
  if (_lassoPoints.length < 3) { deactivateLasso(); return; }

  // Convert lasso DOM points to canvas coords
  const canvasPoly = _lassoPoints.map(pt => network.DOMtoCanvas({ x: pt.x, y: pt.y }));

  // Get all real (non-preview) node IDs
  const allIds = nodes.getIds().filter(id => !String(id).startsWith('_preview_'));
  const positions = network.getPositions(allIds); // canvas coords

  const matched = allIds.filter(id => {
    const pos = positions[id];
    return pos && pointInPolygon(pos.x, pos.y, canvasPoly);
  });

  deactivateLasso();  // must run before selectNodes — setOptions here would clear selection

  if (!matched.length) {
    setStatus('No nodes in selection');
    return;
  }
  network.selectNodes(matched);
  setStatus(`${matched.length} node${matched.length > 1 ? 's' : ''} selected — Delete to remove, or use Find Gaps / Suggest / Summary`);
}

async function softDeleteNodesBatch(ids) {
  if (!confirm(`Delete ${ids.length} node(s) and their edges?\n(Soft-delete: sets deprecated=true)`)) return;

  const now = new Date().toISOString();
  for (const id of ids) {
    const node = chainData.nodes.find(n => n.id === id);
    if (!node || node.deprecated) continue;
    node.deprecated = true;
    nodes.remove(id);
    chainData.edges.forEach(e => {
      if ((e.from === id || e.to === id) && !e.deprecated) {
        e.deprecated = true;
        edges.remove(e.id);
      }
    });
    chainData.history.push({ timestamp: now, action: 'node_edit', actor: 'user', payload: { id, deprecated: true } });
  }

  selectedId = null;
  selectedType = null;
  clearInfoPanel();
  markDirty();
  updateStatusBar();

  setStatus('saving…', 'dirty');
  try {
    await saveChain(chainData);
    setStatus('saved');
  } catch (err) {
    setStatus('save error: ' + err.message, 'error');
  }
}

// ── Clustering ────────────────────────────────────────────────────────────

function _computeDegrees() {
  const inDeg = {}, outDeg = {};
  (chainData?.nodes || []).filter(n => !n.deprecated).forEach(n => {
    inDeg[n.id] = 0;
    outDeg[n.id] = 0;
  });
  (chainData?.edges || []).filter(e => !e.deprecated).forEach(e => {
    if (e.from in outDeg) outDeg[e.from]++;
    if (e.to   in inDeg)  inDeg[e.to]++;
  });
  return { inDeg, outDeg };
}

function _nodeRole(raw, inDeg, outDeg) {
  // Priority 1: issues — flagged, uncertain, or unresolved
  if (raw.flagged || raw.type === 'question' || raw.archetype === 'question' ||
      (raw.confidence != null && raw.confidence < 0.4)) return 'issues';
  // Priority 2: levers — RCDE action types
  if (['task', 'decision', 'gate', 'asset'].includes(raw.type)) return 'levers';
  // Priority 3: drivers — no incoming edges or explicit archetype
  if (raw.archetype === 'root_cause' || (inDeg[raw.id] === 0)) return 'drivers';
  // Priority 4: outcomes — no outgoing edges, explicit archetype, or goal type
  if (raw.archetype === 'effect' || raw.type === 'goal' || (outDeg[raw.id] === 0)) return 'outcomes';
  // Priority 5: everything else is on the causal pathway
  return 'pathway';
}

function clusterByRole() {
  if (!network || !chainData) return;
  declusAll();
  const { inDeg, outDeg } = _computeDegrees();
  // Iterate in display order — issues last so they're visually distinct
  const roleOrder = ['drivers', 'pathway', 'outcomes', 'levers', 'issues'];
  roleOrder.forEach(role => {
    const props = CLUSTER_ROLES[role];
    const clusterId = `_cluster_${role}`;
    network.cluster({
      joinCondition: childNode => {
        if (String(childNode.id).startsWith('_preview_')) return false;
        const raw = (chainData?.nodes || []).find(n => n.id === childNode.id);
        return raw && !raw.deprecated && _nodeRole(raw, inDeg, outDeg) === role;
      },
      processProperties: (clusterOpts, childNodes) => {
        const n = childNodes.length;
        clusterOpts.id    = clusterId;
        clusterOpts.label = `${props.label}\n(${n})`;
        clusterOpts.title = `${props.label}: ${n} node${n > 1 ? 's' : ''}`;
        _activeClusters.push({ id: clusterId, role });
        return clusterOpts;
      },
      clusterNodeProperties: {
        id: clusterId,
        borderWidth: 3,
        shape: props.shape,
        color: { background: props.color, border: '#fff', highlight: { background: props.color, border: '#fff' } },
        font: { size: 14, color: '#fff', bold: true, multi: false },
        widthConstraint: { minimum: 90, maximum: 180 },
        allowSingleNodeCluster: false,
      },
    });
  });
}

function declusAll() {
  if (!network) return;
  [..._activeClusters].forEach(({ id }) => {
    try { if (network.isCluster(id)) network.openCluster(id); } catch (_) {}
  });
  _activeClusters = [];
}

function handleZoomClustering(params) {
  if (!_clusteringEnabled) return;
  if (params.direction === '-' && params.scale < CLUSTER_OUT_SCALE && !_activeClusters.length) {
    clusterByRole();
  } else if (params.direction === '+' && params.scale > CLUSTER_IN_SCALE && _activeClusters.length) {
    declusAll();
  }
}

function setupLasso() {
  const lassoCanvas = document.getElementById('lasso-canvas');

  lassoCanvas.addEventListener('click', e => {
    if (!_lassoActive) return;
    _lassoPoints.push({ x: e.offsetX, y: e.offsetY });
    drawLasso();
  });

  lassoCanvas.addEventListener('dblclick', e => {
    if (!_lassoActive) return;
    // dblclick fires after two clicks — remove the extra point added by the second click
    if (_lassoPoints.length > 0) _lassoPoints.pop();
    if (_lassoPoints.length >= 3) finishLasso();
    else deactivateLasso();
  });

  lassoCanvas.addEventListener('mousemove', e => {
    if (!_lassoActive) return;
    _lassoMousePos = { x: e.offsetX, y: e.offsetY };
    drawLasso();
  });

  lassoCanvas.addEventListener('contextmenu', e => {
    e.preventDefault();
    if (_lassoActive) deactivateLasso();
  });
}

// ── Toolbar ───────────────────────────────────────────────────────────────

function setupToolbar() {
  document.getElementById('btn-add-node').addEventListener('click', () => {
    network?.addNodeMode();
    setStatus('Click anywhere on the canvas to place a new node.', 0);
  });
  document.getElementById('btn-add-edge').addEventListener('click', () => {
    network?.addEdgeMode();
    setStatus('Drag from a source node to a target node to add an edge.', 0);
  });
  document.getElementById('btn-save').addEventListener('click', async () => {
    try {
      await saveChain(chainData);
      setStatus('saved');
    } catch (e) {
      setStatus('save error: ' + e.message, 'error');
    }
  });
  document.getElementById('btn-fit').addEventListener('click', () =>
    network?.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } }));
  document.getElementById('btn-hierarchical').addEventListener('click', rerenderLayout);
  document.getElementById('btn-cluster').addEventListener('click', () => {
    if (_clusteringEnabled) {
      _clusteringEnabled = false;
      declusAll();
      document.getElementById('btn-cluster').classList.remove('active');
      setStatus('Clustering off');
    } else {
      _clusteringEnabled = true;
      document.getElementById('btn-cluster').classList.add('active');
      clusterByRole();
      setStatus('Clustered by role — zoom out to auto-cluster, click a group to expand');
    }
  });
  document.getElementById('btn-enrich').addEventListener('click', () => runEnrich('gaps'));
  document.getElementById('btn-suggest').addEventListener('click', () => runEnrich('suggest'));
  document.getElementById('btn-critique').addEventListener('click', () => runEnrich('critique'));
  document.getElementById('btn-summarize').addEventListener('click', runSummarize);
  document.getElementById('btn-summary-close').addEventListener('click', () =>
    document.getElementById('summary-overlay').classList.remove('visible'));
  document.getElementById('btn-lasso').addEventListener('click', () => {
    if (_lassoActive) deactivateLasso();
    else activateLasso();
  });

  // Note modal
  const noteOverlay = document.getElementById('note-overlay');
  const noteConf = document.getElementById('note-conf');
  const noteUrg = document.getElementById('note-urg');
  const noteConfVal = document.getElementById('note-conf-val');
  const noteUrgVal = document.getElementById('note-urg-val');
  const noteWscoreBadge = document.getElementById('note-wscore-badge');

  function updateWscoreBadge() {
    const ws = Math.round((parseFloat(noteConf.value) * 0.6 + parseFloat(noteUrg.value) * 0.4) * 100) / 100;
    noteWscoreBadge.textContent = ws.toFixed(2);
    noteWscoreBadge.className = 'wscore-badge ' + (ws >= 0.7 ? 'wscore-high' : ws >= 0.4 ? 'wscore-med' : 'wscore-low');
    return ws;
  }

  noteConf.addEventListener('input', () => { noteConfVal.textContent = parseFloat(noteConf.value).toFixed(2); updateWscoreBadge(); });
  noteUrg.addEventListener('input', () => { noteUrgVal.textContent = parseFloat(noteUrg.value).toFixed(2); updateWscoreBadge(); });

  const closeNote = () => {
    noteOverlay.classList.remove('visible');
    document.getElementById('note-text').value = '';
    document.getElementById('note-seeds').value = '';
    noteConf.value = 0.5; noteUrg.value = 0.3;
    noteConfVal.textContent = '0.5'; noteUrgVal.textContent = '0.3';
    updateWscoreBadge();
  };

  document.getElementById('btn-note').addEventListener('click', () => noteOverlay.classList.add('visible'));
  document.getElementById('btn-note-close').addEventListener('click', closeNote);
  document.getElementById('btn-note-cancel').addEventListener('click', closeNote);
  document.getElementById('btn-note-submit').addEventListener('click', () => {
    const text = document.getElementById('note-text').value.trim();
    if (!text) return;
    const seedsRaw = document.getElementById('note-seeds').value.trim();
    const seeds = seedsRaw ? seedsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
    const noteData = {
      type: document.getElementById('note-type').value,
      text,
      seed_entities: seeds,
      confidence: parseFloat(noteConf.value),
      urgency: parseFloat(noteUrg.value),
    };
    closeNote();
    runIngestNote(noteData);
  });

  // Note example presets
  const NOTE_EXAMPLES = {
    cold_swim: {
      type: 'observation', confidence: 0.75, urgency: 0.5,
      seeds: 'cold swim, focus, cortisol',
      text: "I've noticed that on days I do a 3-minute cold swim in the morning, my focus is noticeably sharper for the first 3 hours. This might be because cold exposure acutely lowers cortisol and triggers a norepinephrine spike that primes attention circuits.",
    },
    caffeine_loop: {
      type: 'hypothesis', confidence: 0.6, urgency: 0.4,
      seeds: 'Poor sleep quality, Reduced focus',
      text: "High caffeine intake late in the day (after 2pm) worsens sleep quality the following night, creating a feedback loop where poor focus leads to more caffeine consumption which further degrades sleep. This loop may be broken by enforcing a caffeine cutoff time.",
    },
    deadline_stress: {
      type: 'observation', confidence: 0.5, urgency: 0.3,
      seeds: '',
      text: "Stress from deadlines appears to cause sleep fragmentation even when total hours look adequate. The perceived urgency keeps the nervous system activated at bedtime.",
    },
    // RCDE node-type samples
    task_cold_protocol: {
      type: 'decision', confidence: 0.82, urgency: 0.75,
      seeds: 'cold swim, norepinephrine spike, acute cortisol reduction',
      text: "I have decided to formalise the cold swim into a repeatable morning protocol: exactly 10 minutes in water at or below 15°C, performed within 30 minutes of waking, every weekday. This converts the incidental cold swim event into a deliberate TASK that an agent triggers intentionally with the specific intent to produce the norepinephrine spike and acute cortisol reduction already in the chain. The task only fires if its asset requirements are met — cold water access and a usable time slot before the first meeting.",
    },
    goal_cognitive_peak: {
      type: 'hypothesis', confidence: 0.78, urgency: 0.65,
      seeds: 'sustained focus window, Working memory impairment, norepinephrine spike',
      text: "The terminal outcome I am trying to engineer is a sustained cognitive peak: focus and working memory both above personal baseline for at least 90 uninterrupted minutes each morning, measured by zero task-switching in the first deep-work block. This should be modelled as a GOAL node — the single desired future STATE that anchors the entire chain. The sustained focus window is a direct precondition of this goal. Working memory impairment is its negation and should remain as the risk case.",
    },
    gate_intervention_fork: {
      type: 'decision', confidence: 0.70, urgency: 0.80,
      seeds: 'norepinephrine spike, acute cortisol reduction, sustained focus window',
      text: "I am at a formal fork: two mutually exclusive intervention strategies compete to produce the norepinephrine spike and cortisol reduction the chain already models. Path A is the cold swim protocol (behavioural, zero cost, time-costly). Path B is a low-dose L-tyrosine + ashwagandha stack taken on waking (pharmacological, recurring cost, time-cheap). I cannot run both for measurement reasons. This fork should be modelled as a GATE node with two DIVERGES_TO edges. The gate scores Path A higher on cost and Path B higher on time-efficiency. The gate stays open until a 4-week trial of Path A concludes.",
    },
    asset_cold_water_access: {
      type: 'evidence', confidence: 0.90, urgency: 0.60,
      seeds: 'cold swim',
      text: "The cold swim task cannot execute without physical access to cold water at or below 15°C within 30 minutes of waking. This is a hard prerequisite — an ASSET node, not a causal state. Concretely: a working cold tap capable of reaching ≤15°C, or an outdoor body of water within 5 minutes, or a chest freezer bath. At my current location the tap reaches 12°C in winter and 18°C in summer. In summer a secondary asset (ice bag supply, ≥2kg per session) is required. The ASSET connects to the cold swim TASK via a REQUIRES edge. If absent, a Discovery Task should be generated upstream.",
    },
    // Mixed taxonomy samples
    cognitive_mechanisms: {
      type: 'hypothesis', confidence: 0.72, urgency: 0.60,
      seeds: 'norepinephrine spike, sustained focus window, acute cortisol reduction, Working memory impairment',
      text: "Attentional resource theory holds that the brain allocates a finite pool of executive bandwidth across competing tasks, and that norepinephrine acts as the primary modulator of pool size. This should be modelled as a CONCEPT node that frames how the norepinephrine spike connects to the sustained focus window and why cortisol reduction amplifies that effect. There is an unresolved QUESTION blocking the current chain: does the focus window reliably extend beyond 90 minutes under chronic protocol, or does receptor downregulation cap the effect? This question directly blocks the goal of a 90-minute cognitive peak. Additionally, the mechanism by which cold exposure calibrates the HPA axis response differently on high-stress vs. low-stress days is a BLACKBOX — internal process unknown, flagged for review — and it causes day-to-day variance in the magnitude of acute cortisol reduction.",
    },
    decision_and_requirements: {
      type: 'decision', confidence: 0.80, urgency: 0.70,
      seeds: 'sustained focus window, Working memory impairment, 4-week cold swim trial, intervention strategy gate',
      text: "I have decided to adopt a biometric measurement protocol for the duration of the trial: resting HRV via chest strap and a 3-minute choice reaction-time benchmark every morning. This DECISION node sits downstream of the intervention strategy gate. The decision REQUIRES two assets before it can execute: a validated HRV chest strap and a standardised cognitive benchmark app. Without both assets the decision fires in name only. The sustained focus window is a direct PRECONDITION_OF the goal of a 90-minute cognitive peak — the window must be present and measurable before the goal can be claimed as achieved. This decision also resolves the open question about focus window duration by generating daily reaction-time series data.",
    },
    full_taxonomy_demo: {
      type: 'evidence', confidence: 0.85, urgency: 0.55,
      seeds: 'cold swim, norepinephrine spike, acute cortisol reduction, sustained focus window, Working memory impairment, intervention strategy gate, 4-week cold swim trial, L-tyrosine + ashwagandha stack',
      text: "Full-chain synthesis covering all node types and edge relations. STATE nodes (acute cortisol reduction, sustained focus window, Working memory impairment) are persistent conditions. EVENT: cold swim is a discrete occurrence. TASK: 4-week cold swim trial is a deliberate agent-triggered intervention. ASSET: L-tyrosine + ashwagandha stack connects to its task via REQUIRES. GATE: intervention strategy gate is a formally scored fork with DIVERGES_TO branches. GOAL: 90-minute cognitive peak is the terminal anchor. CONCEPT: attentional resource theory FRAMES the norepinephrine spike and impairment nodes. QUESTION: whether the focus window exceeds 90 minutes BLOCKS the goal. DECISION: adopting biometric measurement REQUIRES specific assets and RESOLVES the open question. BLACKBOX: HPA axis calibration variance causes noise in cortisol reduction magnitude. Edge inventory: CAUSES (cold swim → cortisol reduction), TRIGGERS (cold swim → norepinephrine spike), ENABLES (spike → focus window), AMPLIFIES (spike → memory capacity), REDUCES (cortisol → impairment risk), FRAMES (concept → spike), BLOCKS (question → goal), REQUIRES (task → asset), PRECONDITION_OF (focus window → goal), INSTANTIATES (trial → cold swim event), RESOLVES (decision → question), DIVERGES_TO (gate → each branch).",
    },
  };

  document.getElementById('note-example').addEventListener('change', e => {
    const key = e.target.value;
    if (!key || !NOTE_EXAMPLES[key]) return;
    const ex = NOTE_EXAMPLES[key];
    document.getElementById('note-type').value = ex.type;
    document.getElementById('note-text').value = ex.text;
    document.getElementById('note-seeds').value = ex.seeds;
    noteConf.value = ex.confidence; noteUrg.value = ex.urgency;
    noteConfVal.textContent = ex.confidence.toFixed(2);
    noteUrgVal.textContent = ex.urgency.toFixed(2);
    updateWscoreBadge();
  });

  updateWscoreBadge();

  // Chain switcher modal
  const cswOverlay = document.getElementById('chain-switcher-overlay');
  document.getElementById('btn-switch-chain').addEventListener('click', async () => {
    const list = document.getElementById('chain-switcher-list');
    list.innerHTML = '<div style="color:#666;font-size:12px;padding:8px">Loading…</div>';
    cswOverlay.classList.add('visible');
    try {
      const { chains } = await listChains();
      list.innerHTML = chains.map(c => `
        <div class="chain-item${c.active ? ' active' : ''}" data-filename="${esc(c.filename)}">
          <div class="chain-item-info">
            <div class="chain-item-name">${esc(c.name)}</div>
            <div class="chain-item-meta">${esc(c.domain)} · ${c.nodes}n / ${c.edges}e</div>
          </div>
          <div class="chain-item-actions">
            <span class="chain-item-badge">${c.active ? '● active' : c.filename}</span>
            <button class="chain-item-del" data-filename="${esc(c.filename)}" title="Delete chain">🗑</button>
          </div>
        </div>
      `).join('');
      list.querySelectorAll('.chain-item').forEach(el => {
        // Delete button — stop propagation so it doesn't trigger switch
        el.querySelector('.chain-item-del').addEventListener('click', async e => {
          e.stopPropagation();
          const filename = el.dataset.filename;
          const name = el.querySelector('.chain-item-name').textContent;
          if (!confirm(`Delete "${name}"? A backup will be saved.`)) return;
          try {
            const r = await deleteChain(filename);
            if (r.next_chain) {
              chainData = r.next_chain;
              renderGraph(chainData);
              document.getElementById('chain-name').textContent = r.next_chain.meta?.name || '';
            }
            // Refresh the list
            el.remove();
            setStatus('Deleted: ' + filename);
            if (!list.querySelectorAll('.chain-item').length) {
              list.innerHTML = '<div style="color:#666;font-size:12px;padding:8px">No chains.</div>';
            }
          } catch (err) {
            setStatus('Delete failed: ' + err.message, 'error');
          }
        });
        el.addEventListener('click', async () => {
          const filename = el.dataset.filename;
          if (el.classList.contains('active')) { cswOverlay.classList.remove('visible'); return; }
          cswOverlay.classList.remove('visible');
          setStatus('Switching chain…');
          try {
            const data = await switchChain(filename);
            chainData = data;
            renderGraph(chainData);
            document.getElementById('chain-name').textContent = data.meta?.name || filename;
            setStatus('loaded ' + (data.meta?.name || filename));
          } catch (err) {
            setStatus('switch failed: ' + err.message, 'error');
          }
        });
      });
    } catch (err) {
      list.innerHTML = `<div style="color:#f66;font-size:12px;padding:8px">Error: ${esc(err.message)}</div>`;
    }
  });
  document.getElementById('btn-csw-close').addEventListener('click', () => cswOverlay.classList.remove('visible'));

  // New chain modal
  const ncOverlay = document.getElementById('new-chain-overlay');
  function openNewChain() { ncOverlay.classList.add('visible'); document.getElementById('nc-name').focus(); }
  function closeNewChain() { ncOverlay.classList.remove('visible'); }
  document.getElementById('btn-new-chain').addEventListener('click', openNewChain);
  document.getElementById('btn-new-chain-close').addEventListener('click', closeNewChain);
  document.getElementById('btn-nc-cancel').addEventListener('click', closeNewChain);
  document.getElementById('btn-nc-create').addEventListener('click', async () => {
    const name = document.getElementById('nc-name').value.trim();
    if (!name) { document.getElementById('nc-name').focus(); return; }
    const domain = document.getElementById('nc-domain').value.trim() || 'custom';
    closeNewChain();
    setStatus('Creating chain…');
    try {
      const r = await createChain(name, domain);
      chainData = r.chain;
      renderGraph(chainData);
      document.getElementById('chain-name').textContent = r.chain.meta?.name || name;
      document.getElementById('nc-name').value = '';
      document.getElementById('nc-domain').value = '';
      setStatus('Created: ' + (r.chain.meta?.name || name));
    } catch (e) {
      setStatus('Create failed: ' + e.message, 'error');
    }
  });

  // Reset demo
  document.getElementById('btn-reset-demo').addEventListener('click', async () => {
    if (!confirm('Reset demo chain to its initial seed state? Current state will be backed up.')) return;
    setStatus('Resetting demo…');
    try {
      const r = await resetDemo();
      if (r.chain && Object.keys(r.chain).length) {
        chainData = r.chain;
        renderGraph(chainData);
        document.getElementById('chain-name').textContent = r.chain.meta?.name || 'Demo chain';
      }
      clearPreviewItems();
      document.getElementById('suggestions-overlay').classList.remove('visible');
      setStatus('Demo reset — ' + (r.reset || []).join(', '));
    } catch (e) {
      setStatus('Reset failed: ' + e.message, 'error');
    }
  });
}

function setupInfoPanel() {
  showChainPanel();
}

function setupKeyboard() {
  document.addEventListener('keydown', e => {
    // Save
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      saveChain(chainData).then(() => setStatus('saved')).catch(err => setStatus(err.message, 'error'));
    }
    // Delete selected node/edge
    if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
      const tag = e.target.tagName.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      e.preventDefault();
      deleteSelected();
    }
    // Escape: cancel lasso first, then close overlays
    if (e.key === 'Escape') {
      if (_lassoActive) { deactivateLasso(); return; }
      document.getElementById('suggestions-overlay').classList.remove('visible');
      document.getElementById('note-overlay').classList.remove('visible');
      document.getElementById('chain-switcher-overlay').classList.remove('visible');
      document.getElementById('new-chain-overlay').classList.remove('visible');
      document.getElementById('summary-overlay').classList.remove('visible');
    }
    // Enter: finish lasso polygon
    if (e.key === 'Enter' && _lassoActive) {
      e.preventDefault();
      if (_lassoPoints.length >= 3) finishLasso();
    }
  });
}

// ── LLM actions ───────────────────────────────────────────────────────────

async function runExplain(nodeId) {
  showLlmLoading('Explaining...');
  try {
    const r = await llmExplain(nodeId);
    showLlmResult(r.explanation || 'No explanation returned.');
  } catch (e) {
    showLlmResult('Error: ' + e.message);
  }
}


function showAskDialog(nodeId) {
  const q = prompt('Ask the LLM about this node:');
  if (!q) return;
  showLlmLoading('Thinking...');
  llmAsk(q).then(r => showLlmResult(r.answer || 'No answer.')).catch(e => showLlmResult('Error: ' + e.message));
}

function showContradictDialog(edgeId) {
  const obs = prompt('Enter an observation to check against this edge:');
  if (!obs) return;
  showLlmLoading('Checking contradiction...');
  llmContradict(obs).then(r => {
    if (r.no_conflict) { showLlmResult('No contradiction found.'); return; }
    const conflicts = (r.conflicts || []).map(c =>
      `Edge ${c.edge_id}: ${c.conflict_type}\n${c.reasoning}\nWeight: ${c.current_weight} → ${c.suggested_weight}`
    ).join('\n\n');
    showLlmResult(conflicts || JSON.stringify(r));
  }).catch(e => showLlmResult('Error: ' + e.message));
}

async function runSummarize() {
  const overlay = document.getElementById('summary-overlay');
  const body = document.getElementById('summary-body');
  const headline = document.getElementById('summary-headline');
  headline.textContent = '';

  const selIds = (network?.getSelectedNodes() || []).filter(id => !String(id).startsWith('_preview_'));
  const scope = selIds.length ? `${selIds.length} selected node${selIds.length > 1 ? 's' : ''}` : null;
  body.innerHTML = `<div class="summary-loading">${scope ? `Summarizing ${scope}…` : 'Generating summary…'}</div>`;
  overlay.classList.add('visible');

  try {
    const r = await llmSummarize(selIds.length ? selIds : null);
    headline.textContent = r.headline || '';
    body.innerHTML = _renderSummary(r);
  } catch (e) {
    body.innerHTML = `<div class="summary-error">Error: ${esc(e.message)}</div>`;
  }
}

function _renderSummary(r) {
  const parts = [];

  // Goal
  if (r.goal) {
    parts.push(`
      <div class="sum-section sum-goal">
        <div class="sum-section-title">🎯 Goal</div>
        <div class="sum-item">
          <span class="sum-label">${esc(r.goal.label || '')}</span>
          <span class="sum-plain">${esc(r.goal.plain || '')}</span>
        </div>
      </div>`);
  }

  // Critical path
  if (r.critical_path?.length) {
    const steps = r.critical_path.map(s => `
      <div class="sum-step">
        <span class="sum-step-num">${s.step}</span>
        <div class="sum-step-body">
          <span class="sum-label">${esc(s.label || '')}</span>
          <span class="sum-role sum-role-${(s.role || '').replace('_', '-')}">${esc(s.role || '')}</span>
          <span class="sum-plain">${esc(s.plain || '')}</span>
        </div>
      </div>`).join('');
    parts.push(`
      <div class="sum-section sum-path">
        <div class="sum-section-title">🛤 Critical Path</div>
        ${steps}
      </div>`);
  }

  // Tasks
  if (r.tasks?.length) {
    const items = r.tasks.map(t => {
      const req = t.requires?.length ? `<span class="sum-requires">requires: ${t.requires.map(x => esc(x)).join(', ')}</span>` : '';
      return `<div class="sum-item"><span class="sum-label">${esc(t.label || '')}</span>${req}<span class="sum-plain">${esc(t.plain || '')}</span></div>`;
    }).join('');
    parts.push(`<div class="sum-section sum-tasks"><div class="sum-section-title">⚡ Tasks</div>${items}</div>`);
  }

  // Decisions
  if (r.decisions?.length) {
    const items = r.decisions.map(d => {
      const branches = d.branches?.length
        ? `<div class="sum-branches">${d.branches.map(b => `<span class="sum-branch">${esc(b.label || '')} → ${esc(b.outcome || '')}</span>`).join('')}</div>`
        : '';
      return `<div class="sum-item"><span class="sum-label">${esc(d.label || '')}</span><span class="sum-plain">${esc(d.plain || '')}</span>${branches}</div>`;
    }).join('');
    parts.push(`<div class="sum-section sum-decisions"><div class="sum-section-title">🔀 Decisions</div>${items}</div>`);
  }

  // Risks
  if (r.risks?.length) {
    const items = r.risks.map(risk => `
      <div class="sum-item sum-risk-item">
        <span class="sum-label">${esc(risk.label || '')}</span>
        <span class="sum-plain">${esc(risk.plain || '')}</span>
      </div>`).join('');
    parts.push(`<div class="sum-section sum-risks"><div class="sum-section-title">⚠ Risks</div>${items}</div>`);
  }

  // Open questions
  if (r.open_questions?.length) {
    const items = r.open_questions.map(q => `<div class="sum-question">${esc(q)}</div>`).join('');
    parts.push(`<div class="sum-section sum-questions"><div class="sum-section-title">❓ Open Questions</div>${items}</div>`);
  }

  return parts.join('') || '<div class="summary-loading">Nothing to summarize yet.</div>';
}

function showLlmLoading(msg) {
  const el = document.getElementById('llm-response');
  el.textContent = msg;
  el.classList.add('visible');
}

function showLlmResult(text) {
  const el = document.getElementById('llm-response');
  el.textContent = text;
  el.classList.add('visible');
}

// ── Status bar ────────────────────────────────────────────────────────────

function updateStatusBar() {
  if (!chainData) return;
  const activeNodes = chainData.nodes.filter(n => !n.deprecated).length;
  const activeEdges = chainData.edges.filter(e => !e.deprecated).length;
  document.getElementById('status-nodes').textContent = `${activeNodes} nodes`;
  document.getElementById('status-edges').textContent = `${activeEdges} edges`;
}

function setStatus(msg, level = 'ok') {
  const dot = document.getElementById('status-dot');
  const saved = document.getElementById('status-saved');
  if (dot) dot.className = 'dot' + (level === 'error' ? ' error' : level === 'dirty' ? ' dirty' : '');
  if (saved) saved.textContent = msg;
}

// ── Utils ─────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Start ─────────────────────────────────────────────────────────────────
init().catch(err => {
  document.body.innerHTML = `<div style="padding:40px;color:#ef4444;font-family:monospace">
    <h2>Failed to load chain</h2><pre>${err.message}</pre>
  </div>`;
});
