"""Tiny local API (127.0.0.1 only, token required) for the Acode plugin and Termux scripts."""
import hmac, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8765


def start_server(tracker, get_memory, token, port=PORT):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None):
            body = json.dumps(obj or {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self):
            return hmac.compare_digest(self.headers.get("X-Token", ""), token)

        def _body(self):
            n = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_OPTIONS(self):
            self._send(204)

        def do_GET(self):
            if not self._authed():
                return self._send(401, {"error": "bad token"})
            u = urlparse(self.path)
            if u.path == "/active":
                p, src, dirty = tracker.current()
                return self._send(200, {"path": p, "source": src, "dirty": dirty})
            if u.path == "/memory/search":
                mem = get_memory()
                if mem is None:
                    return self._send(423, {"error": "locked - unlock the app"})
                q = parse_qs(u.query)
                rows = mem.search(q.get("q", [""])[0], q.get("lang", [""])[0])
                return self._send(200, {"results": [{"id": r["id"], "kind": r["kind"],
                                                     "data": r["data"]} for r in rows]})
            self._send(404)

        def do_POST(self):
            if not self._authed():
                return self._send(401, {"error": "bad token"})
            try:
                b = self._body()
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if self.path == "/active":
                p = tracker.report(b.get("uri") or b.get("path") or "", b.get("dirty", False))
                return self._send(200 if p else 422, {"path": p})
            if self.path == "/memory/add":
                mem = get_memory()
                if mem is None:
                    return self._send(423, {"error": "locked - unlock the app"})
                if b.get("kind") not in ("pref", "note"):
                    return self._send(400, {"error": "kind must be pref or note"})
                return self._send(200, {"id": mem.add(b["kind"], {"text": str(b.get("text", ""))[:2000]},
                                                      b.get("lang", ""))})
            self._send(404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
