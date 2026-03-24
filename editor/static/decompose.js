/**
 * decompose.js — standalone Knowledge Decomposition page
 * Runs the TEXT_TO_CHAIN (KD) pipeline and visualises the result
 * as a vis-network graph. Nodes are coloured by epistemic class
 * (KK/KU/UU/UK) rather than confidence.
 */
import { llmImportText, saveNewChain } from './sync.js';

// ── Visual encoding ───────────────────────────────────────────────

const TYPE_SHAPE = {
  state: 'box', event: 'diamond', decision: 'hexagon',
  concept: 'ellipse', question: 'star', blackbox: 'question',
  // RCDE extensions
  goal: 'triangle', task: 'dot', asset: 'database', gate: 'square',
};

const RELATION_COLOR = {
  CAUSES:          '#94a3b8',
  ENABLES:         '#22c55e',
  BLOCKS:          '#ef4444',
  TRIGGERS:        '#f59e0b',
  REDUCES:         '#4a9eed',
  REQUIRES:        '#8b5cf6',
  AMPLIFIES:       '#ec4899',
  // RCDE extensions
  PRECONDITION_OF: '#06b6d4',
  RESOLVES:        '#10b981',
  FRAMES:          '#a78bfa',
  INSTANTIATES:    '#fbbf24',
  DIVERGES_TO:     '#fb923c',
};

// KK = blue (parametric), KU = yellow (instance), UU = red (unknown), UK = purple (bridge)
const KLASS_STYLE = {
  KK: { bg: '#0d2a4a', border: '#339af0', text: '#74c0fc' },
  KU: { bg: '#2e2400', border: '#f59f00', text: '#ffd43b' },
  UU: { bg: '#3a0808', border: '#fa5252', text: '#ff8787' },
  UK: { bg: '#2d1b4e', border: '#ae3ec9', text: '#cc5de8' },
};

function suggestionToVis(s, idx) {
  const shape = TYPE_SHAPE[s.node_type] || 'box';
  const klass = s.klass || 'KU';
  const style = KLASS_STYLE[klass] || KLASS_STYLE.KU;
  const flagBorder = s.flagged ? '#fa5252' : style.border;
  const tipLines = [
    `<b>${s.label}</b>  <i>[${klass}]</i>`,
    s.description || '',
    `type: ${s.node_type || 'state'}${s.archetype ? ' · ' + s.archetype : ''}`,
    `confidence: ${(s.confidence ?? 0.7).toFixed(2)}`,
    s.flagged ? '⚑ flagged — requires human review' : null,
  ].filter(Boolean).join('<br>');
  return {
    id: idx,
    label: s.label,
    title: tipLines,
    shape,
    color: {
      background: style.bg,
      border: flagBorder,
      highlight: { background: style.bg, border: '#fff' },
    },
    borderWidth: s.flagged ? 3 : 2,
    borderDashes: s.flagged ? [4, 3] : false,
    font: { face: 'Courier New', color: style.text, size: 12 },
    _raw: s,
    _idx: idx,
  };
}

const LAYOUT = {
  enabled: true,
  direction: 'UD',
  sortMethod: 'directed',
  shakeTowards: 'leaves',
  levelSeparation: 120,
  nodeSpacing: 120,
  treeSpacing: 100,
  blockShifting: true,
  edgeMinimization: true,
  parentCentralization: false,
};

const OPTIONS = {
  layout: { hierarchical: LAYOUT },
  physics: { enabled: false },
  edges: {
    arrows: { to: { enabled: true, scaleFactor: 0.8 } },
    smooth: { type: 'cubicBezier', forceDirection: 'vertical' },
    font: { size: 10, align: 'top', color: '#bbb' },
    color: { inherit: false },
    width: 2,
  },
  nodes: { font: { size: 12, face: 'Courier New' }, borderWidth: 2, shadow: false },
  manipulation: { enabled: false },
  interaction: { hover: true, tooltipDelay: 150, navigationButtons: true, keyboard: true },
};

// ── State ─────────────────────────────────────────────────────────

let network = null;
let visNodes = null;
let visEdges = null;
let _suggestions = [];   // all import_node suggestions (current decomposition)
let _edges = [];         // all import_edge suggestions

// ── Helpers ───────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function setStatus(msg, duration = 3000) {
  const el = document.getElementById('deco-status');
  el.textContent = msg;
  el.classList.add('visible');
  clearTimeout(el._timer);
  if (duration > 0) el._timer = setTimeout(() => el.classList.remove('visible'), duration);
}

// ── Render ────────────────────────────────────────────────────────

function rerenderLayout() {
  if (!network) return;
  network.setOptions({ layout: { hierarchical: LAYOUT } });
  let _done = false;
  function _finish() {
    if (_done) return;
    _done = true;
    network.setOptions({ layout: { hierarchical: { enabled: false } } });
    network.fit();
  }
  network.once('stabilized', _finish);
  setTimeout(_finish, 150);
}

function renderDecomposition(suggestions, edges) {
  const container = document.getElementById('deco-graph');

  const nodeItems = suggestions
    .filter(s => s.kind === 'import_node')
    .map((s, i) => suggestionToVis(s, i));

  // Build label → vis id map
  const labelToId = {};
  nodeItems.forEach(n => { labelToId[n.label] = n.id; });

  const edgeItems = edges
    .filter(s => s.kind === 'import_edge')
    .map((s, i) => {
      const fromId = labelToId[s.connects_from_label];
      const toId   = labelToId[s.connects_to_label];
      if (fromId == null || toId == null) return null;
      const color = RELATION_COLOR[s.relation] || '#888';
      const tip = [
        `<b>${s.relation}</b>`,
        `weight: ${(s.weight ?? 0.7).toFixed(2)}`,
        s.reasoning || '',
      ].filter(Boolean).join('<br>');
      const arrowType = s.relation === 'BLOCKS' ? 'bar'
                      : s.relation === 'DIVERGES_TO' ? 'vee'
                      : 'arrow';
      return {
        id: `e${i}`,
        from: fromId,
        to: toId,
        label: s.relation,
        title: tip,
        width: Math.min(8, Math.max(1, (s.weight ?? 0.7) * 6)),
        color: { color, highlight: '#fff', hover: '#fff', inherit: false },
        arrows: { to: { enabled: true, scaleFactor: 0.8, type: arrowType } },
        smooth: { type: 'cubicBezier', forceDirection: 'vertical' },
        font: { size: 10, align: 'top', color: '#bbb', strokeWidth: 2, strokeColor: '#1a1a2e' },
      };
    }).filter(Boolean);

  if (!network) {
    visNodes = new vis.DataSet(nodeItems);
    visEdges = new vis.DataSet(edgeItems);
    network = new vis.Network(container, { nodes: visNodes, edges: visEdges }, OPTIONS);
    network.on('click', onNetworkClick);
    rerenderLayout();
  } else {
    visNodes.clear(); visEdges.clear();
    visNodes.add(nodeItems); visEdges.add(edgeItems);
    rerenderLayout();
  }

  document.getElementById('btn-deco-save').disabled = false;
}

// ── Inspector ─────────────────────────────────────────────────────

function onNetworkClick(params) {
  if (!params.nodes.length) {
    document.getElementById('deco-inspector').style.display = 'none';
    return;
  }
  const nodeId = params.nodes[0];
  const vis = visNodes.get(nodeId);
  if (!vis) return;
  const s = vis._raw;

  const klass = s.klass || 'KU';
  const style = KLASS_STYLE[klass];

  const html = `
    <div class="deco-node-label">${esc(s.label)}</div>
    <div style="margin-bottom:8px">
      <span class="klass-badge klass-${klass.toLowerCase()}">${klass}</span>
      ${s.flagged ? '<span style="color:#fa5252;font-size:10px;margin-left:6px">⚑ flagged</span>' : ''}
    </div>
    <div class="deco-field">
      <label>Label</label>
      <input type="text" id="di-label" value="${esc(s.label)}">
    </div>
    <div class="deco-field">
      <label>Type</label>
      <select id="di-type">
        ${['state','event','decision','concept','question','blackbox','goal','task','asset','gate'].map(t =>
          `<option value="${t}"${s.node_type === t ? ' selected' : ''}>${t}</option>`
        ).join('')}
      </select>
    </div>
    <div class="deco-field">
      <label>Description</label>
      <textarea id="di-desc">${esc(s.description || '')}</textarea>
    </div>
    <div class="deco-field">
      <label>Confidence: <span id="di-conf-val">${(s.confidence ?? 0.7).toFixed(2)}</span></label>
      <input type="range" id="di-conf" min="0" max="1" step="0.05" value="${(s.confidence ?? 0.7)}">
    </div>
    <button id="di-apply" class="success" style="width:100%;margin-top:6px">Apply changes</button>
  `;

  const box = document.getElementById('deco-inspector');
  document.getElementById('deco-inspector-content').innerHTML = html;
  box.style.display = '';

  document.getElementById('di-conf').addEventListener('input', e => {
    document.getElementById('di-conf-val').textContent = parseFloat(e.target.value).toFixed(2);
  });

  document.getElementById('di-apply').addEventListener('click', () => {
    const newLabel = document.getElementById('di-label').value.trim() || s.label;
    const newType  = document.getElementById('di-type').value;
    const newDesc  = document.getElementById('di-desc').value.trim();
    const newConf  = parseFloat(document.getElementById('di-conf').value);

    // Update in _suggestions array
    const idx = vis._idx;
    if (_suggestions[idx]) {
      _suggestions[idx].label       = newLabel;
      _suggestions[idx].node_type   = newType;
      _suggestions[idx].description = newDesc;
      _suggestions[idx].confidence  = newConf;
    }

    // Update vis node
    const newStyle = KLASS_STYLE[klass] || KLASS_STYLE.KU;
    visNodes.update({
      id: nodeId,
      label: newLabel,
      shape: TYPE_SHAPE[newType] || 'box',
      _raw: { ...s, label: newLabel, node_type: newType, description: newDesc, confidence: newConf },
    });
    setStatus('Node updated');
  });
}

// ── Decompose ─────────────────────────────────────────────────────

async function runDecompose() {
  const text = document.getElementById('deco-input').value.trim();
  if (!text) { setStatus('Paste some text first.', 3000); return; }

  setStatus('Decomposing…', 0);
  document.getElementById('btn-deco-run').disabled = true;
  document.getElementById('btn-deco-save').disabled = true;
  document.getElementById('deco-metrics-box').style.display = 'none';

  try {
    const r = await llmImportText(text);
    _suggestions = (r.suggestions || []).filter(s => s.kind === 'import_node');
    _edges       = (r.suggestions || []).filter(s => s.kind === 'import_edge');

    if (!_suggestions.length) {
      setStatus('No structure extracted — try more descriptive text.', 4000);
      return;
    }

    renderDecomposition(_suggestions, _edges);
    renderMetrics(r.metrics || {}, r.causal_prompt || '');
    setStatus(`Extracted ${_suggestions.length} nodes, ${_edges.length} edges.`, 4000);
  } catch (e) {
    setStatus('Error: ' + e.message, 6000);
  } finally {
    document.getElementById('btn-deco-run').disabled = false;
  }
}

function renderMetrics(metrics, causalPrompt) {
  const box = document.getElementById('deco-metrics-box');
  const m = document.getElementById('deco-metrics');
  const cp = document.getElementById('deco-causal-prompt');

  const kk = metrics.kk_count ?? 0;
  const ku = metrics.ku_count ?? 0;
  const uu = metrics.uu_count ?? 0;
  const cr = ((metrics.compression_ratio ?? 0) * 100).toFixed(0);
  const rf = ((metrics.roundtrip_fidelity ?? 0) * 100).toFixed(0);

  m.innerHTML = [
    { val: kk, lbl: 'KK', color: '#74c0fc' },
    { val: ku, lbl: 'KU', color: '#ffd43b' },
    { val: uu, lbl: 'UU', color: '#ff8787' },
    { val: cr + '%', lbl: 'Compression', color: '#a78bfa' },
    { val: rf + '%', lbl: 'Fidelity', color: '#a9e34b' },
    { val: _edges.length, lbl: 'Edges', color: '#e0e0e0' },
  ].map(item => `
    <div class="deco-metric">
      <span class="deco-metric-val" style="color:${item.color}">${item.val}</span>
      <span class="deco-metric-lbl">${item.lbl}</span>
    </div>
  `).join('');

  cp.textContent = causalPrompt || '—';
  box.style.display = '';
}

// ── Save as new chain ─────────────────────────────────────────────

async function saveChain() {
  if (!_suggestions.length) return;
  const name = prompt('New chain name:', 'Knowledge chain');
  if (!name) return;

  setStatus('Saving…', 0);
  try {
    // Rebuild combined suggestions for the API (nodes then edges)
    const allSuggestions = [
      ..._suggestions.map(s => ({ ...s, kind: 'import_node' })),
      ..._edges,
    ];
    const r = await saveNewChain({ name, suggestions: allSuggestions });
    setStatus(`Saved as ${r.filename} — use ⎇ Chain in the editor to open it.`, 8000);
    document.getElementById('deco-title').textContent = name;
  } catch (e) {
    setStatus('Save error: ' + e.message, 6000);
  }
}

// ── Setup ─────────────────────────────────────────────────────────

function setup() {
  document.getElementById('btn-deco-run').addEventListener('click', runDecompose);
  document.getElementById('btn-deco-save').addEventListener('click', saveChain);
  document.getElementById('btn-deco-clear').addEventListener('click', () => {
    document.getElementById('deco-input').value = '';
    if (visNodes) { visNodes.clear(); visEdges.clear(); }
    _suggestions = []; _edges = [];
    document.getElementById('deco-metrics-box').style.display = 'none';
    document.getElementById('deco-inspector').style.display = 'none';
    document.getElementById('btn-deco-save').disabled = true;
    setStatus('Cleared', 2000);
  });
  document.getElementById('btn-deco-fit').addEventListener('click', () => {
    network?.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  });
  // Allow Ctrl/Cmd+Enter to trigger decompose
  document.getElementById('deco-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      runDecompose();
    }
  });
}

setup();
