/**
 * sync.js — chain save/load bridge
 * Handles polling for external changes and POSTing saves to the local server.
 */

const POLL_INTERVAL = 3000; // ms
let _dirty = false;
let _lastSaveCount = 0;
let _manualSaveCount = 0;
const AUTO_BACKUP_EVERY = 10;

export function markDirty() {
  _dirty = true;
  document.querySelector('#status-dot')?.classList.add('dirty');
  document.querySelector('#status-saved')?.textContent &&
    (document.getElementById('status-saved').textContent = 'unsaved');
}

export function markClean() {
  _dirty = false;
  document.querySelector('#status-dot')?.classList.remove('dirty');
  const el = document.getElementById('status-saved');
  if (el) el.textContent = 'saved';
}

export function isDirty() { return _dirty; }

// Redirect to login page on 401 from any API call
function _handleUnauthorized(resp) {
  if (resp.status === 401) {
    window.location.replace('/login');
    throw new Error('Session expired. Please log in again.');
  }
  return resp;
}

export async function logout() {
  await fetch('/auth/logout', { method: 'POST' });
  window.location.replace('/login');
}

export async function loadChain() {
  const resp = _handleUnauthorized(await fetch('/api/chain'));
  if (!resp.ok) throw new Error(`Load failed: ${resp.status}`);
  return resp.json();
}

export async function listChains() {
  const resp = await fetch('/api/chains');
  if (!resp.ok) throw new Error(`List failed: ${resp.status}`);
  return resp.json();
}

export async function switchChain(filename) {
  const resp = await fetch('/api/chain/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function saveChain(chainData) {
  const resp = await fetch('/api/chain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(chainData),
  });
  const result = await resp.json();
  if (!resp.ok || result.error) throw new Error(result.error || 'Save failed');

  _manualSaveCount++;
  if (_manualSaveCount % AUTO_BACKUP_EVERY === 0) {
    console.log(`[sync] Auto-backup threshold reached (${_manualSaveCount} saves)`);
  }
  markClean();
  return result;
}

export async function validateChain() {
  const resp = await fetch('/api/validate');
  if (!resp.ok) return { issues: [] };
  return resp.json();
}

// LLM API calls
export async function llmAsk(question, lang = 'en') {
  return _llmPost('/llm/ask', { question, lang });
}

export async function llmExplain(nodeId = null, lang = 'en') {
  return _llmPost('/llm/explain', { node_id: nodeId, lang });
}

export async function llmSuggest(n = 5) {
  return _llmPost('/llm/suggest', { n });
}

export async function llmCritique() {
  return _llmPost('/llm/critique', {});
}

export async function llmContradict(observation) {
  return _llmPost('/llm/contradict', { observation });
}

export async function llmEnrichPreview(mode = 'gaps', nodeIds = null) {
  return _llmPost('/llm/enrich-preview', { mode, ...(nodeIds ? { node_ids: nodeIds } : {}) });
}

export async function llmImportText(text) {
  return _llmPost('/llm/import-text', { text });
}

export async function llmIngestNote(noteData) {
  return _llmPost('/llm/ingest-note', noteData);
}

export async function createChain(name, domain) {
  const resp = await fetch('/api/chain/new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, domain }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function deleteChain(filename) {
  const resp = await fetch('/api/chain/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function llmSummarize(nodeIds = null) {
  return _llmPost('/llm/summarize', nodeIds ? { node_ids: nodeIds } : {});
}

export async function saveSummary(entry) {
  const resp = await fetch('/api/summary/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entry }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function deleteSummary(id) {
  const resp = await fetch('/api/summary/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function listSummaryFiles() {
  const resp = await fetch('/api/summary/files');
  if (!resp.ok) throw new Error(`List files failed: ${resp.status}`);
  return (await resp.json()).files || [];
}

export async function readSummaryFile(name) {
  const resp = await fetch(`/api/summary/file?name=${encodeURIComponent(name)}`);
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data.content;
}

export async function exportSummaryFile(name, content) {
  const resp = await fetch('/api/summary/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function saveNewChain(payload) {
  const resp = await fetch('/api/chain/save-new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export async function resetDemo() {
  const resp = await fetch('/api/demo/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}

async function _llmPost(endpoint, body) {
  const resp = _handleUnauthorized(await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data;
}
