"""
Local HTTP server for the causal editor.
Serves the HTML/JS/CSS editor and provides a REST API for chain I/O and LLM calls.
Browser ↔ server communication uses HTTP polling (GET /api/chain) and POST endpoints.
"""
import base64
import hashlib
import json
import os
import re
import struct
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import chain.io as chain_io
from chain.schema import CausalChain
from chain.validate import validate

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_TEMPLATE = os.path.join(os.path.dirname(__file__), "template.html")

# Shared state
_chain: CausalChain = None
_chain_path: str = None
_chain_lock = threading.Lock()
_last_modified: float = 0.0


def _mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
    }.get(ext, "application/octet-stream")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Silence default access log

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg: str, status: int = 400):
        self._send_json({"error": msg}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── WebSocket upgrade ─────────────────────────────────────────────────────

    def _ws_handshake(self) -> bool:
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        return True

    def _ws_recv(self) -> bytes | None:
        try:
            header = self.rfile.read(2)
            if len(header) < 2:
                return None
            masked = bool(header[1] & 0x80)
            length = header[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self.rfile.read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self.rfile.read(8))[0]
            mask = self.rfile.read(4) if masked else b"\x00\x00\x00\x00"
            data = bytearray(self.rfile.read(length))
            if masked:
                for i in range(len(data)):
                    data[i] ^= mask[i % 4]
            return bytes(data)
        except Exception:
            return None

    def _ws_send(self, data: str):
        encoded = data.encode()
        header = bytearray([0x81])
        n = len(encoded)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header += bytearray([126]) + struct.pack(">H", n)
        else:
            header += bytearray([127]) + struct.pack(">Q", n)
        try:
            self.wfile.write(bytes(header) + encoded)
            self.wfile.flush()
        except Exception:
            pass

    def _ws_loop(self):
        """Push chain updates to the browser when the chain changes on disk/terminal."""
        global _last_modified
        while True:
            try:
                msg = self._ws_recv()
                if msg is None:
                    break
                # Client can send ping or chain updates
                try:
                    payload = json.loads(msg.decode())
                    if payload.get("type") == "ping":
                        self._ws_send(json.dumps({"type": "pong"}))
                except Exception:
                    pass
            except Exception:
                break

    # ── Routing ───────────────────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        # WebSocket upgrade
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._ws_handshake()
            self._ws_loop()
            return

        if path == "/" or path == "/editor":
            self._serve_file(_TEMPLATE)
        elif path == "/decompose":
            self._serve_file(os.path.join(os.path.dirname(__file__), "decompose.html"))
        elif path == "/api/chain":
            self._api_get_chain()
        elif path == "/api/chains":
            self._api_list_chains()
        elif path.startswith("/static/"):
            rel = path[len("/static/"):]
            self._serve_file(os.path.join(_STATIC_DIR, rel))
        else:
            self._send_error("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/chain":
            self._api_save_chain()
        elif path == "/api/chain/switch":
            self._api_switch_chain()
        elif path == "/api/demo/reset":
            self._api_demo_reset()
        elif path == "/api/chain/save-new":
            self._api_save_new_chain()
        elif path == "/api/validate":
            self._api_validate()
        elif path == "/llm/ask":
            self._llm_ask()
        elif path == "/llm/explain":
            self._llm_explain()
        elif path == "/llm/suggest":
            self._llm_suggest()
        elif path == "/llm/critique":
            self._llm_critique()
        elif path == "/llm/contradict":
            self._llm_contradict()
        elif path == "/llm/enrich-preview":
            self._llm_enrich_preview()
        elif path == "/llm/import-text":
            self._llm_import_text()
        elif path == "/llm/ingest-note":
            self._llm_ingest_note()
        else:
            self._send_error("Not found", 404)

    # ── Static file serving ───────────────────────────────────────────────────

    def _serve_file(self, filepath: str):
        if not os.path.isfile(filepath):
            self._send_error("File not found", 404)
            return
        with open(filepath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _mime(filepath))
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    # ── Chain API ─────────────────────────────────────────────────────────────

    def _api_get_chain(self):
        global _chain, _last_modified
        with _chain_lock:
            if _chain is None:
                self._send_json({"error": "no chain loaded"}, 404)
                return
            try:
                disk_mtime = os.path.getmtime(_chain_path)
                if disk_mtime > _last_modified:
                    _chain = chain_io.load(_chain_path)
                    _last_modified = disk_mtime
            except OSError:
                pass
            self._send_json(chain_io.to_dict(_chain))

    def _api_save_chain(self):
        global _chain, _last_modified
        body = self._body()
        with _chain_lock:
            try:
                # Rebuild chain from browser payload
                import chain.schema as schema
                meta = schema.ChainMeta(**{k: v for k, v in body.get("meta", {}).items()
                                           if k in schema.ChainMeta.__dataclass_fields__})
                nodes = [schema.Node(**{k: v for k, v in n.items()
                                        if k in schema.Node.__dataclass_fields__})
                         for n in body.get("nodes", [])]
                edges = []
                for e in body.get("edges", []):
                    ed = {k: v for k, v in e.items() if k in schema.Edge.__dataclass_fields__}
                    # JSON uses "from"/"to"; dataclass uses from_id/to_id
                    if "from" in e:
                        ed["from_id"] = e["from"]
                    if "to" in e:
                        ed["to_id"] = e["to"]
                    ed.pop("from", None)
                    ed.pop("to", None)
                    edges.append(schema.Edge(**ed))

                new_chain = schema.CausalChain(
                    meta=meta, nodes=nodes, edges=edges,
                    history=body.get("history", _chain.history if _chain else [])
                )
                chain_io.save(new_chain, _chain_path)
                _chain = new_chain
                _last_modified = time.time()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_error(str(exc))

    def _api_validate(self):
        with _chain_lock:
            if _chain is None:
                self._send_json({"issues": []})
                return
            issues = validate(_chain)
            self._send_json({"issues": issues})

    def _api_list_chains(self):
        chains_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chains")
        result = []
        if os.path.isdir(chains_dir):
            for fname in sorted(os.listdir(chains_dir)):
                if not fname.endswith(".causal.json"):
                    continue
                if fname.endswith("-seed.causal.json"):
                    continue  # seed files are read-only templates, not user-selectable chains
                path = os.path.join(chains_dir, fname)
                try:
                    data = json.load(open(path))
                    meta = data.get("meta", {})
                    active_nodes = sum(1 for n in data.get("nodes", []) if not n.get("deprecated"))
                    active_edges = sum(1 for e in data.get("edges", []) if not e.get("deprecated"))
                    result.append({
                        "filename": fname,
                        "name": meta.get("name", fname),
                        "domain": meta.get("domain", ""),
                        "nodes": active_nodes,
                        "edges": active_edges,
                        "active": _chain_path and os.path.basename(_chain_path) == fname,
                    })
                except Exception:
                    pass
        self._send_json({"chains": result})

    def _api_switch_chain(self):
        global _chain, _chain_path, _last_modified
        body = self._body()
        filename = body.get("filename", "")
        if not filename:
            self._send_error("No filename provided")
            return
        if filename.endswith("-seed.causal.json"):
            self._send_error("Seed files are read-only and cannot be switched to directly", 400)
            return
        chains_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chains")
        path = os.path.join(chains_dir, filename)
        if not os.path.isfile(path):
            self._send_error(f"Chain not found: {filename}", 404)
            return
        with _chain_lock:
            try:
                new_chain = chain_io.load(path)
                _chain = new_chain
                _chain_path = path
                _last_modified = os.path.getmtime(path)
                self._send_json(chain_io.to_dict(_chain))
            except Exception as exc:
                self._send_error(str(exc))

    def _api_demo_reset(self):
        global _chain, _chain_path, _last_modified
        import shutil
        chains_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chains")
        seeds = sorted(f for f in os.listdir(chains_dir) if f.endswith("-seed.causal.json"))
        if not seeds:
            self._send_error("No seed files found")
            return
        reset = []
        with _chain_lock:
            try:
                for seed_name in seeds:
                    target_name = seed_name.replace("-seed.causal.json", ".causal.json")
                    seed_path   = os.path.join(chains_dir, seed_name)
                    target_path = os.path.join(chains_dir, target_name)
                    if os.path.exists(target_path):
                        chain_io.backup(target_path)
                    shutil.copy2(seed_path, target_path)
                    reset.append(target_name)
                    # If the currently loaded chain was reset, reload it
                    if _chain_path and os.path.abspath(_chain_path) == os.path.abspath(target_path):
                        _chain = chain_io.load(target_path)
                        _last_modified = os.path.getmtime(target_path)
                # Return current chain state after reset
                chain_data = chain_io.to_dict(_chain) if _chain else {}
                self._send_json({"reset": reset, "chain": chain_data})
            except Exception as exc:
                self._send_error(str(exc))

    def _api_save_new_chain(self):
        """Create a new .causal.json from accepted import-text suggestions."""
        from datetime import datetime
        import shutil
        body = self._body()
        name = body.get("name", "").strip() or "Untitled"
        suggestions = body.get("suggestions", [])
        try:
            chains_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chains")
            slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'chain'
            filename = f"{slug}.causal.json"
            path = os.path.join(chains_dir, filename)
            counter = 1
            while os.path.exists(path):
                filename = f"{slug}-{counter}.causal.json"
                path = os.path.join(chains_dir, filename)
                counter += 1

            import chain.schema as schema
            now = datetime.now().isoformat()
            meta = schema.ChainMeta(
                id=uuid.uuid4().hex[:8], name=name, domain="custom",
                created_at=now, updated_at=now, version=1, author="",
                description="Created from text decomposition.",
            )
            nodes, label_to_id, edges = [], {}, []
            for s in suggestions:
                if s.get("kind") == "import_node":
                    nid = uuid.uuid4().hex[:8]
                    label_to_id[s["label"]] = nid
                    nodes.append(schema.Node(
                        id=nid, label=s.get("label", ""),
                        description=s.get("description", ""),
                        type=s.get("node_type", "state"),
                        archetype=s.get("archetype") or None,
                        tags=[], confidence=float(s.get("confidence", 0.7)),
                        created_at=now, source="llm",
                        deprecated=False, flagged=bool(s.get("flagged", False)),
                    ))
            for s in suggestions:
                if s.get("kind") == "import_edge":
                    from_id = label_to_id.get(s.get("connects_from_label", ""))
                    to_id = label_to_id.get(s.get("connects_to_label", ""))
                    if not from_id or not to_id:
                        continue
                    edges.append(schema.Edge(
                        id=uuid.uuid4().hex[:8], from_id=from_id, to_id=to_id,
                        relation=s.get("relation", "CAUSES"),
                        weight=float(s.get("weight", 0.7)), confidence=0.7,
                        direction="forward", condition=None,
                        evidence=s.get("reasoning", ""),
                        deprecated=False, flagged=False, version=1,
                        created_at=now, source="llm",
                    ))
            new_chain = schema.CausalChain(meta=meta, nodes=nodes, edges=edges, history=[])
            chain_io.save(new_chain, path)
            self._send_json({"filename": filename, "chain": chain_io.to_dict(new_chain)})
        except Exception as exc:
            self._send_error(str(exc))

    # ── LLM endpoints ─────────────────────────────────────────────────────────

    def _llm_ask(self):
        body = self._body()
        question = body.get("question", "")
        lang = body.get("lang", "en")
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        try:
            from llm import client as llm_client
            from llm.prompts import ASK_CHAIN
            prompt = ASK_CHAIN.format(
                chain_json=json.dumps(chain_data, indent=2),
                question=question,
                lang=lang,
            )
            result = llm_client.call(prompt)
            self._send_json({"answer": result.get("answer", "")})
        except Exception as exc:
            self._send_error(str(exc))

    def _llm_explain(self):
        body = self._body()
        node_id = body.get("node_id")
        lang = body.get("lang", "en")
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        try:
            from llm import client as llm_client
            from llm.prompts import EXPLAIN_CHAIN, EXPLAIN_NODE
            if node_id:
                node = next((n for n in chain_data.get("nodes", []) if n["id"] == node_id), None)
                label = node["label"] if node else node_id
                prompt = EXPLAIN_NODE.format(
                    context_json=json.dumps(chain_data, indent=2),
                    node_label=label,
                    lang=lang,
                )
            else:
                prompt = EXPLAIN_CHAIN.format(
                    chain_json=json.dumps(chain_data, indent=2),
                    lang=lang,
                )
            result = llm_client.call(prompt)
            self._send_json({"explanation": result.get("explanation", "")})
        except Exception as exc:
            self._send_error(str(exc))

    def _llm_suggest(self):
        body = self._body()
        n = body.get("n", 5)
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        try:
            from llm import client as llm_client
            from llm.prompts import SUGGEST_NODES
            prompt = SUGGEST_NODES.format(chain_json=json.dumps(chain_data, indent=2), n=n)
            result = llm_client.call(prompt)
            self._send_json({"suggestions": result.get("suggestions", [])})
        except Exception as exc:
            self._send_error(str(exc))

    def _llm_critique(self):
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        try:
            from llm import client as llm_client
            from llm.prompts import CRITIQUE_CHAIN
            prompt = CRITIQUE_CHAIN.format(chain_json=json.dumps(chain_data, indent=2))
            result = llm_client.call(prompt)
            self._send_json({"issues": result.get("issues", [])})
        except Exception as exc:
            self._send_error(str(exc))

    def _llm_contradict(self):
        body = self._body()
        observation = body.get("observation", "")
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        try:
            from llm import client as llm_client
            from llm.prompts import CONTRADICT_CHECK
            prompt = CONTRADICT_CHECK.format(
                chain_json=json.dumps(chain_data, indent=2),
                observation=observation,
            )
            result = llm_client.call(prompt)
            self._send_json(result)
        except Exception as exc:
            self._send_error(str(exc))

    def _llm_enrich_preview(self):
        body = self._body()
        mode = body.get("mode", "gaps")
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        try:
            from llm import client as llm_client
            from llm.prompts import ENRICH_GAPS, SUGGEST_NODES, CRITIQUE_CHAIN

            if mode == "gaps":
                prompt = ENRICH_GAPS.format(chain_json=json.dumps(chain_data, indent=2), n=5)
                result = llm_client.call(prompt)
                suggestions = []
                for g in result.get("gaps", []):
                    mn = g.get("missing_node", {})
                    suggestions.append({
                        "kind": "gap_node",
                        "label": mn.get("label", ""),
                        "node_type": mn.get("type", "state"),
                        "description": mn.get("description", ""),
                        "connects_from": g.get("between_from"),
                        "connects_to": g.get("between_to"),
                        "reasoning": g.get("reasoning", ""),
                    })
            elif mode == "critique":
                prompt = CRITIQUE_CHAIN.format(chain_json=json.dumps(chain_data, indent=2))
                result = llm_client.call(prompt)
                suggestions = []
                # Map each issue to a gap_node suggestion so it flows through the preview overlay.
                # Issues about missing mechanisms become node suggestions; others surface as
                # labelled review items (the user can accept or reject each one).
                node_map = {n["id"]: n.get("label", n["id"]) for n in chain_data.get("nodes", [])}
                for iss in result.get("issues", []):
                    elem_id = iss.get("element_id", "")
                    elem_label = node_map.get(elem_id, elem_id)
                    issue_type = iss.get("type", "")
                    severity = iss.get("severity", "medium")
                    description = iss.get("description", "")
                    fix = iss.get("suggested_fix", "")
                    if issue_type == "missing_mechanism":
                        suggestions.append({
                            "kind": "gap_node",
                            "label": f"[mechanism] {elem_label}",
                            "node_type": "concept",
                            "description": fix,
                            "connects_from": elem_id if elem_id in node_map else None,
                            "connects_to": None,
                            "reasoning": f"[{severity}] {description}",
                        })
                    else:
                        suggestions.append({
                            "kind": "gap_node",
                            "label": f"[{issue_type}] {elem_label or 'chain'}",
                            "node_type": "question",
                            "description": fix,
                            "connects_from": None,
                            "connects_to": None,
                            "reasoning": f"[{severity}] {description}",
                        })
            else:  # suggest
                prompt = SUGGEST_NODES.format(chain_json=json.dumps(chain_data, indent=2), n=5)
                result = llm_client.call(prompt)
                suggestions = []
                for s in result.get("suggestions", []):
                    suggestions.append({
                        "kind": s.get("type", "node"),
                        "label": s.get("label", ""),
                        "node_type": "state",
                        "description": s.get("description", ""),
                        "connects_from": s.get("connects_from"),
                        "connects_to": s.get("connects_to"),
                        "relation": s.get("relation", "CAUSES"),
                        "reasoning": s.get("reasoning", ""),
                    })

            self._send_json({"suggestions": suggestions})
        except Exception as exc:
            self._send_error(str(exc))

    def _llm_import_text(self):
        body = self._body()
        text = body.get("text", "").strip()
        if not text:
            self._send_error("No text provided")
            return
        try:
            from llm import client as llm_client
            from llm.prompts import TEXT_TO_CHAIN

            prompt = TEXT_TO_CHAIN.format(text=text)
            result = llm_client.call(prompt, max_tokens=4000)

            raw_nodes = result.get("nodes", [])
            raw_edges = result.get("edges", [])

            suggestions = []
            for n in raw_nodes:
                klass = n.get("klass", "KU")
                suggestions.append({
                    "kind": "import_node",
                    "label": n.get("label", ""),
                    "node_type": n.get("type", "state"),
                    "description": n.get("description", ""),
                    "archetype": n.get("archetype") or None,
                    "confidence": float(n.get("confidence", 0.7)),
                    "flagged": bool(n.get("flagged", False)),
                    "klass": klass,
                    "reasoning": f"[{klass}] {n.get('description', '')}",
                })
            for e in raw_edges:
                suggestions.append({
                    "kind": "import_edge",
                    "label": f"{e.get('from_label', '')} → {e.get('to_label', '')}",
                    "connects_from_label": e.get("from_label", ""),
                    "connects_to_label": e.get("to_label", ""),
                    "relation": e.get("relation", "CAUSES"),
                    "weight": e.get("weight", 0.7),
                    "reasoning": e.get("evidence", ""),
                })

            self._send_json({
                "suggestions": suggestions,
                "causal_prompt": result.get("causal_prompt", ""),
                "metrics": result.get("metrics", {}),
            })
        except Exception as exc:
            self._send_error(str(exc))


    def _llm_ingest_note(self):
        body = self._body()
        try:
            from note.ingest import ingest_note
            from note.parser import w_score
            note_data = {
                "type": body.get("type", "observation"),
                "text": body.get("text", "").strip(),
                "seed_entities": body.get("seed_entities", []),
                "confidence": float(body.get("confidence", 0.5)),
                "urgency": float(body.get("urgency", 0.3)),
            }
            if not note_data["text"]:
                self._send_error("No text provided")
                return

            # Build YAML front matter for ingest_note
            seeds_yaml = ""
            if note_data["seed_entities"]:
                seeds_list = "\n".join(f"  - {s}" for s in note_data["seed_entities"])
                seeds_yaml = f"seed_entities:\n{seeds_list}\n"
            note_text = (
                f"---\n"
                f"type: {note_data['type']}\n"
                f"confidence: {note_data['confidence']}\n"
                f"urgency: {note_data['urgency']}\n"
                f"{seeds_yaml}"
                f"---\n"
                f"{note_data['text']}"
            )

            with _chain_lock:
                result = ingest_note(_chain, note_text)

            self._send_json({
                "suggestions": result["suggestions"],
                "classification": result["classification"],
                "w_score": result["w_score"],
            })
        except Exception as exc:
            self._send_error(str(exc))


def start(chain_path: str, port: int = 7331, open_browser: bool = True):
    global _chain, _chain_path
    _chain_path = chain_path
    _chain = chain_io.load(chain_path)

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"  Editor: {url}")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
