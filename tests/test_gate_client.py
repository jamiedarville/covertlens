"""CL-64: GateClient over HTTP + the example harness contract."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from covertlens.gate import PendingDeliveryError, WithheldError
from covertlens.gate_client import GateClient

_STATE: dict[str, str] = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def _send(self, status, body, content_type="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/api/gate/runs":
            self._send(200, {"run_id": "run_test"})
        elif self.path == "/api/gate/deliveries":
            _STATE["d1"] = "pending"
            self._send(
                200, {"delivery_id": "d1", "run_id": "run_test", "state": "pending"}
            )
        elif self.path.endswith("/analyze"):
            self._send(200, {"suggested_verdict": "log"})
        elif self.path.endswith("/verdict"):
            _STATE["d1"] = "decided"
            self._send(200, {"delivery_id": "d1", "state": "permitted"})
        else:
            self._send(404, {"detail": "not found"})

    def do_GET(self):
        if self.path.endswith("/recipient-image"):
            state = _STATE.get("d1")
            if state == "decided":
                self._send(200, b"PNGDATA", "image/png")
            elif state == "withheld":
                self._send(403, {"detail": "withheld"})
            else:
                self._send(409, {"detail": "pending"})
        elif self.path.startswith("/api/gate/runs/"):
            self._send(200, {"run_id": "run_test", "deliveries": [], "events": []})
        else:
            self._send(404, {"detail": "not found"})


@pytest.fixture()
def client():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _STATE.clear()
    yield GateClient(f"http://127.0.0.1:{server.server_port}")
    server.shutdown()


def test_intercept_attempt_access_permitted(client):
    run_id = client.create_run()
    handle = client.intercept("R-01", b"img", {"run_id": run_id, "sender_id": "a"})
    delivery = client.attempt(handle, "agent-b")
    assert delivery["delivery_id"] == "d1"
    with pytest.raises(PendingDeliveryError):
        client.access("d1")
    client.record_verdict("d1", "log")
    assert client.access("d1") == b"PNGDATA"


def test_withheld_raises_and_no_bytes(client):
    client.create_run()
    handle = client.intercept("R-01", b"img", {"run_id": "run_test"})
    client.attempt(handle, "agent-b")
    _STATE["d1"] = "withheld"
    with pytest.raises(WithheldError):
        client.access("d1")
