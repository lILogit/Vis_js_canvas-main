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
_LOGIN_PAGE = os.path.join(os.path.dirname(__file__), "login.html")
_SUMMARIES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "summaries")

# Paths that do not require authentication
_PUBLIC_PATHS = {"/login", "/auth/login"}

# Shared state
_chain: CausalChain = None
_chain_path: str = None
_chain_lock = threading.Lock()
_last_modified: float = 0.0

# ── Auth / session state ──────────────────────────────────────────────────
_sessions: dict = {}  # token -> {"username": str, "expires": float}
_SESSION_TTL = 8 * 3600  # 8 hours


def _get_credentials() -> tuple[str, str]:
    """Return (username, password) from env vars, defaulting to admin/admin."""
    username = os.environ.get("EDITOR_USERNAME", "admin")
    password = os.environ.get("EDITOR_PASSWORD", "admin")
    return username, password


def _create_session(username: str) -> str:
    token = uuid.uuid4().hex
    _sessions[token] = {"username": username, "expires": time.time() + _SESSION_TTL}
    return token


def _get_token_from_cookie(cookie_header: str) -> str | None:
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("session="):
            return part[len("session="):]
    return None


def _check_auth(cookie_header: str) -> bool:
    token = _get_token_from_cookie(cookie_header)
    if not token:
        return False
    sess = _sessions.get(token)
    if sess and sess["expires"] > time.time():
        return True
    if sess:
        del _sessions[token]
    return False


def _subgraph(chain_data: dict, node_ids: list) -> dict:
    """Return a copy of chain_data filtered to the given node ids and edges between them."""
    id_set = set(node_ids)
    nodes = [n for n in chain_data.get("nodes", []) if n.get("id") in id_set]
    edges = [e for e in chain_data.get("edges", [])
             if e.get("from") in id_set and e.get("to") in id_set]
    return {"meta": chain_data.get("meta", {}), "nodes": nodes, "edges": edges}


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
            if not _check_auth(self.headers.get("Cookie", "")):
                return  # silently drop unauthenticated WS connections
            self._ws_handshake()
            self._ws_loop()
            return

        # Auth gate — redirect browser requests, 401 for API/asset requests
        if path not in _PUBLIC_PATHS:
            if not _check_auth(self.headers.get("Cookie", "")):
                if path.startswith("/api/") or path.startswith("/llm/") or path.startswith("/static/"):
                    self._send_error("Unauthorized", 401)
                else:
                    self.send_response(302)
                    self.send_header("Location", "/login")
                    self.end_headers()
                return

        if path == "/login":
            self._serve_file(_LOGIN_PAGE)
        elif path == "/" or path == "/editor":
            self._serve_file(_TEMPLATE)
        elif path == "/decompose":
            self._serve_file(os.path.join(os.path.dirname(__file__), "decompose.html"))
        elif path == "/grammar":
            self._serve_file(os.path.join(os.path.dirname(__file__), "grammar.html"))
        elif path == "/training" or path == "/training.html":
            self._serve_file(os.path.join(os.path.dirname(__file__), "training.html"))
        elif path == "/api/chain":
            self._api_get_chain()
        elif path == "/api/chains":
            self._api_list_chains()
        elif path == "/api/llm-status":
            self._api_llm_status()
        elif path == "/api/llm-provider":
            self._api_get_llm_provider()
        elif path == "/api/summary/files":
            self._api_summary_list_files()
        elif path == "/api/summary/file":
            self._api_summary_read_file()
        elif path.startswith("/static/"):
            rel = path[len("/static/"):]
            self._serve_file(os.path.join(_STATIC_DIR, rel))
        else:
            self._send_error("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path

        # Auth endpoints are always public
        if path == "/auth/login":
            self._auth_login()
            return
        if path == "/auth/logout":
            self._auth_logout()
            return

        # All other POST endpoints require a valid session
        if not _check_auth(self.headers.get("Cookie", "")):
            self._send_error("Unauthorized", 401)
            return

        if path == "/api/chain":
            self._api_save_chain()
        elif path == "/api/chain/switch":
            self._api_switch_chain()
        elif path == "/api/demo/reset":
            self._api_demo_reset()
        elif path == "/api/chain/save-new":
            self._api_save_new_chain()
        elif path == "/api/chain/new":
            self._api_new_chain()
        elif path == "/api/chain/delete":
            self._api_delete_chain()
        elif path == "/api/validate":
            self._api_validate()
        elif path == "/api/llm-provider":
            self._api_set_llm_provider()
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
        elif path == "/llm/summarize":
            self._llm_summarize()
        elif path == "/api/summary/save":
            self._api_summary_save()
        elif path == "/api/summary/delete":
            self._api_summary_delete()
        elif path == "/api/summary/export":
            self._api_summary_export()
        else:
            self._send_error("Not found", 404)

    # ── Auth endpoints ────────────────────────────────────────────────────────

    def _auth_login(self):
        body = self._body()
        username_in = body.get("username", "").strip()
        password_in = body.get("password", "")
        expected_user, expected_pass = _get_credentials()
        if username_in == expected_user and password_in == expected_pass:
            token = _create_session(username_in)
            resp_body = json.dumps({"ok": True, "username": username_in}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(resp_body))
            self.send_header("Set-Cookie",
                             f"session={token}; HttpOnly; Path=/; SameSite=Strict")
            self.end_headers()
            self.wfile.write(resp_body)
        else:
            self._send_error("Invalid username or password", 401)

    def _auth_logout(self):
        cookie_header = self.headers.get("Cookie", "")
        token = _get_token_from_cookie(cookie_header)
        if token:
            _sessions.pop(token, None)
        resp_body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(resp_body))
        # Expire the cookie
        self.send_header("Set-Cookie",
                         "session=; HttpOnly; Path=/; SameSite=Strict; Max-Age=0")
        self.end_headers()
        self.wfile.write(resp_body)

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

    def _api_new_chain(self):
        """Create and switch to a new empty chain."""
        global _chain, _chain_path, _last_modified
        from datetime import datetime
        body = self._body()
        name = body.get("name", "").strip() or "Untitled"
        domain = body.get("domain", "custom").strip() or "custom"
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
                id=uuid.uuid4().hex[:8], name=name, domain=domain,
                created_at=now, updated_at=now, version=1, author="",
                description="",
            )
            new_chain = schema.CausalChain(meta=meta, nodes=[], edges=[], history=[])
            chain_io.save(new_chain, path)
            with _chain_lock:
                _chain = new_chain
                _chain_path = path
                _last_modified = os.path.getmtime(path)
            self._send_json({"filename": filename, "chain": chain_io.to_dict(new_chain)})
        except Exception as exc:
            self._send_error(str(exc))

    def _api_delete_chain(self):
        """Move a chain file to backups and, if active, switch to another chain."""
        global _chain, _chain_path, _last_modified
        import shutil
        body = self._body()
        filename = body.get("filename", "").strip()
        if not filename:
            self._send_error("No filename provided")
            return
        if filename.endswith("-seed.causal.json"):
            self._send_error("Seed files cannot be deleted", 400)
            return
        chains_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chains")
        path = os.path.join(chains_dir, filename)
        if not os.path.isfile(path):
            self._send_error(f"Chain not found: {filename}", 404)
            return
        with _chain_lock:
            try:
                chain_io.backup(path)  # move to backups before deleting
                os.remove(path)
                was_active = _chain_path and os.path.abspath(_chain_path) == os.path.abspath(path)
                next_chain_data = None
                if was_active:
                    # Switch to first remaining non-seed chain, or null
                    remaining = sorted(
                        f for f in os.listdir(chains_dir)
                        if f.endswith(".causal.json") and not f.endswith("-seed.causal.json")
                    )
                    if remaining:
                        next_path = os.path.join(chains_dir, remaining[0])
                        _chain = chain_io.load(next_path)
                        _chain_path = next_path
                        _last_modified = os.path.getmtime(next_path)
                        next_chain_data = chain_io.to_dict(_chain)
                    else:
                        _chain = None
                        _chain_path = None
                        _last_modified = 0
                self._send_json({"deleted": filename, "next_chain": next_chain_data})
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
        node_ids = body.get("node_ids") or []
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        if node_ids:
            chain_data = _subgraph(chain_data, node_ids)
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


    def _llm_summarize(self):
        body = self._body()
        node_ids = body.get("node_ids") or []
        with _chain_lock:
            chain_data = chain_io.to_dict(_chain) if _chain else {}
        if node_ids:
            chain_data = _subgraph(chain_data, node_ids)
        try:
            from llm import client as llm_client
            from llm.prompts import SUMMARIZE_CHAIN
            prompt = SUMMARIZE_CHAIN.format(chain_json=json.dumps(chain_data, indent=2))
            result = llm_client.call(prompt)
            self._send_json(result)
        except Exception as exc:
            self._send_error(str(exc))

    def _api_summary_save(self):
        """Append a summary snapshot to the chain's summaries list and persist."""
        body = self._body()
        entry = body.get("entry")
        if not entry or not isinstance(entry, dict):
            self._send_error("Missing entry")
            return
        with _chain_lock:
            if not _chain:
                self._send_error("No chain loaded")
                return
            _chain.summaries.append(entry)
            try:
                chain_io.save(_chain, _chain_path)
            except Exception as exc:
                # Roll back in-memory on save failure
                _chain.summaries.pop()
                self._send_error(str(exc))
                return
        self._send_json({"ok": True, "id": entry.get("id")})

    def _api_summary_delete(self):
        """Remove a summary by id from the chain's summaries list and persist."""
        body = self._body()
        sid = body.get("id")
        if not sid:
            self._send_error("Missing id")
            return
        with _chain_lock:
            if not _chain:
                self._send_error("No chain loaded")
                return
            before = list(_chain.summaries)
            _chain.summaries = [s for s in _chain.summaries if s.get("id") != sid]
            if len(_chain.summaries) == len(before):
                self._send_error("Summary not found", 404)
                return
            try:
                chain_io.save(_chain, _chain_path)
            except Exception as exc:
                _chain.summaries = before
                self._send_error(str(exc))
                return
        self._send_json({"ok": True})

    def _api_summary_list_files(self):
        """List .md files in the summaries directory, newest first."""
        os.makedirs(_SUMMARIES_DIR, exist_ok=True)
        files = []
        for fname in os.listdir(_SUMMARIES_DIR):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(_SUMMARIES_DIR, fname)
            try:
                stat = os.stat(fpath)
                files.append({
                    "name": fname,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                })
            except OSError:
                continue
        files.sort(key=lambda f: f["modified_at"], reverse=True)
        self._send_json({"files": files})

    def _api_summary_read_file(self):
        """Return the content of a .md file from the summaries directory."""
        from urllib.parse import parse_qs
        qs = parse_qs(urlparse(self.path).query)
        name = (qs.get("name") or [""])[0]
        if not name or not name.endswith(".md") or "/" in name or ".." in name:
            self._send_error("Invalid filename")
            return
        fpath = os.path.join(_SUMMARIES_DIR, name)
        if not os.path.isfile(fpath):
            self._send_error("File not found", 404)
            return
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self._send_json({"name": name, "content": content})

    def _api_summary_export(self):
        """Write a summary .md file to the summaries directory."""
        body = self._body()
        name = body.get("name", "")
        content = body.get("content", "")
        if not name or not name.endswith(".md") or "/" in name or ".." in name:
            self._send_error("Invalid filename")
            return
        os.makedirs(_SUMMARIES_DIR, exist_ok=True)
        fpath = os.path.join(_SUMMARIES_DIR, name)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        self._send_json({"ok": True, "name": name})

    def _api_get_llm_provider(self):
        self._send_json({
            "provider": os.environ.get("LLM_PROVIDER", "anthropic").lower(),
            "providers": ["anthropic", "openai", "zai"],
        })

    def _api_set_llm_provider(self):
        body = self._body()
        provider = body.get("provider", "").lower()
        if provider not in ("anthropic", "zai", "openai"):
            self._send_error(f"Unknown provider: {provider}")
            return
        os.environ["LLM_PROVIDER"] = provider
        self._send_json({"provider": provider})

    def _api_llm_status(self):
        """Return active provider info and do a minimal ping to verify connectivity."""
        provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
        if provider == "zai":
            key_var = "ZAI_API_KEY"
            label = "Z.AI"
        elif provider == "openai":
            key_var = "OPENAI_API_KEY"
            label = "OpenAI"
        else:
            key_var = "ANTHROPIC_API_KEY"
            label = "Anthropic"

        api_key = os.environ.get(key_var)
        if not api_key:
            self._send_json({"provider": label, "ok": False, "error": f"{key_var} not set"})
            return

        try:
            if provider in ("zai", "openai"):
                from openai import OpenAI as _OAI
                if provider == "zai":
                    from llm.client import _ZAI_BASE_URL, _ZAI_MODEL
                    base_url, model = _ZAI_BASE_URL, _ZAI_MODEL
                else:
                    from llm.client import _OPENAI_BASE_URL, _OPENAI_MODEL
                    base_url, model = _OPENAI_BASE_URL, _OPENAI_MODEL
                c = _OAI(base_url=base_url, api_key=api_key)
                token_kwarg = "max_completion_tokens" if provider == "openai" else "max_tokens"
                resp = c.chat.completions.create(
                    model=model,
                    **{token_kwarg: 4},
                    messages=[
                        {"role": "system", "content": "ping"},
                        {"role": "user", "content": "hi"},
                    ],
                )
                self._send_json({"provider": label, "ok": True,
                                 "reply": resp.choices[0].message.content.strip()})
            else:
                import anthropic as _anthropic
                from llm.client import _MODEL
                c = _anthropic.Anthropic(api_key=api_key)
                msg = c.messages.create(
                    model=_MODEL,
                    max_tokens=4,
                    system="ping",
                    messages=[{"role": "user", "content": "hi"}],
                )
                self._send_json({"provider": label, "ok": True, "reply": msg.content[0].text.strip()})
        except Exception as exc:
            # RateLimitError with balance message → API reachable, key valid, no credits
            msg = str(exc)
            if "balance" in msg.lower() or "recharge" in msg.lower():
                self._send_json({"provider": label, "ok": True, "reply": "API reachable (no credits)"})
            else:
                self._send_json({"provider": label, "ok": False, "error": msg})


def start(chain_path: str, port: int = 7331, open_browser: bool = True, host: str = "127.0.0.1"):
    global _chain, _chain_path
    _chain_path = chain_path
    _chain = chain_io.load(chain_path)

    server = HTTPServer((host, port), Handler)
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
