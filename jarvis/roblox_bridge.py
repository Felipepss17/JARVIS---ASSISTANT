"""Recebe localmente erros/avisos encaminhados pelo plugin opcional do Roblox Studio."""
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

HOST = "127.0.0.1"
PORT = 18743
_records = deque(maxlen=100)
_lock = threading.Lock()
_server = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path != "/roblox/output":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 8192:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            message = str(payload.get("message", "")).strip()[:3000]
            level = str(payload.get("level", "")).lower()[:20]
            context = str(payload.get("context", ""))[:500]
            if not message or level not in {"error", "warning"}:
                self.send_error(400)
                return
            record = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "level": level, "message": message, "context": context}
            with _lock:
                _records.append(record)
            self.send_response(204)
            self.end_headers()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            self.send_error(400)


def start_server():
    """Start once, bound to loopback only; returns (server, error)."""
    global _server
    if _server is not None:
        return _server, None
    try:
        server = ThreadingHTTPServer((HOST, PORT), _Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="roblox-output-bridge", daemon=True).start()
        _server = server
        return server, None
    except OSError as error:
        return None, str(error)


def stop_server():
    global _server
    server, _server = _server, None
    if server:
        server.shutdown()
        server.server_close()


def get_recent_output(limite=30):
    with _lock:
        records = list(_records)[-max(1, min(int(limite), 50)):]
    if not records:
        return ("Ainda não recebi erros/avisos. No Roblox Studio, instale o plugin "
                "roblox/JARVIS_Output_Connector.lua, clique em ‘Capturar Output’ e reproduza o problema.")
    return "\n".join(f"[{r['time']}] {r['level'].upper()}: {r['message']}" +
                     (f"\nContexto: {r['context']}" if r["context"] else "") for r in records)
