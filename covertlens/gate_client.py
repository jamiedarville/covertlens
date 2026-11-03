"""HTTP harness adapter for the Live Gate (CL-64).

`GateClient` is the integration surface harness engineers program
against instead of hand-rolling HTTP: `intercept` stages image bytes
at the gate, `attempt` attempts delivery to a recipient, `access`
collects the bytes exactly as a recipient would — raising the
library's own `PendingDeliveryError` (409, no verdict yet) and
`WithheldError` (403, quarantine/fail) so harness code handles gate
outcomes with the same exceptions as the in-process gate (CL-12).

The client uses only the standard library (`urllib`), so a harness
needs no web extra installed. Demo roles are not authentication: an
optional `demo_role` is sent as `X-Demo-Role`, honoured by the
service only with `COVERTLENS_DEMO_ROLES=on` (CL-78). In OIDC mode
(CL-67) pass `bearer_token`: a JWT from the deployment's identity
provider for the harness's service identity, sent as
`Authorization: Bearer`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from .gate import PendingDeliveryError, WithheldError


@dataclass(frozen=True)
class GateHandle:
    """Staged bytes awaiting an attempted delivery."""

    route: str
    data: bytes
    run_id: str
    sender_id: str
    episode_id: str | None = None


class GateClient:
    """One harness's connection to a running CovertLens service."""

    def __init__(
        self,
        base_url: str,
        *,
        demo_role: str | None = None,
        bearer_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.demo_role = demo_role
        self.bearer_token = bearer_token
        self.timeout = timeout

    # -- low-level helpers -------------------------------------------------
    def _request(
        self, method: str, path: str, body: bytes | None, content_type: str
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(self.base_url + path, data=body, method=method)
        req.add_header("Content-Type", content_type)
        if self.demo_role:
            req.add_header("X-Demo-Role", self.demo_role)
        if self.bearer_token:
            req.add_header("Authorization", f"Bearer {self.bearer_token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        status, raw = self._request(
            method, path, json.dumps(payload).encode(), "application/json"
        )
        if status >= 400:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:200]!r}")
        return json.loads(raw or b"{}")

    # -- harness API ---------------------------------------------------------
    def create_run(self, run_id: str | None = None) -> str:
        """Create (or name) a run; returns its `run_id`."""
        body = self._json(
            "POST", "/api/gate/runs", {"run_id": run_id} if run_id else {}
        )
        return str(body["run_id"])

    def intercept(
        self,
        route: str,
        data: bytes,
        ctx: dict[str, Any],
    ) -> GateHandle:
        """Stage `data` for the gate on `route` (no delivery yet).

        `ctx` carries `run_id` and `sender_id` (plus optional
        `episode_id`) — the CL-12 interception context.
        """
        return GateHandle(
            route=route,
            data=bytes(data),
            run_id=str(ctx["run_id"]),
            sender_id=str(ctx.get("sender_id") or "agent-a"),
            episode_id=ctx.get("episode_id"),
        )

    def attempt(self, handle: GateHandle, recipient: str) -> dict[str, Any]:
        """Attempt delivery of a staged handle to `recipient`."""
        boundary = f"----covertlens{uuid.uuid4().hex}"
        fields = {
            "run_id": handle.run_id,
            "sender_id": handle.sender_id,
            "recipient_id": recipient,
            "route_id": handle.route,
        }
        if handle.episode_id:
            fields["episode_id"] = handle.episode_id
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{name}"\r\n\r\n{value}\r\n'.encode()
            )
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="file"; filename="image.bin"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
            + handle.data
            + b"\r\n"
        )
        chunks.append(f"--{boundary}--\r\n".encode())
        status, raw = self._request(
            "POST",
            "/api/gate/deliveries",
            b"".join(chunks),
            f"multipart/form-data; boundary={boundary}",
        )
        if status >= 400:
            raise RuntimeError(f"attempt -> {status}: {raw[:200]!r}")
        return json.loads(raw)

    def analyze(self, delivery_id: str) -> dict[str, Any]:
        """Analyse a pending delivery; returns the suggested verdict."""
        return self._json("POST", f"/api/gate/deliveries/{delivery_id}/analyze", {})

    def record_verdict(self, delivery_id: str, verdict: str) -> dict[str, Any]:
        """Record `log|flag|quarantine|fail_run` (needs a permitted role)."""
        return self._json(
            "POST",
            f"/api/gate/deliveries/{delivery_id}/verdict",
            {"verdict": verdict},
        )

    def access(self, delivery_id: str) -> bytes:
        """Recipient access: bytes, or the gate's own exceptions.

        Raises `PendingDeliveryError` before a permitting verdict and
        `WithheldError` on a withheld delivery — no bytes either way.
        """
        status, raw = self._request(
            "GET", f"/api/gate/deliveries/{delivery_id}/recipient-image", b"", ""
        )
        if status == 200:
            return raw
        detail = raw[:200].decode("utf-8", "replace")
        if status == 409:
            raise PendingDeliveryError(detail)
        if status == 403:
            raise WithheldError(detail)
        if status == 404:
            raise KeyError(delivery_id)
        raise RuntimeError(f"access -> {status}: {detail}")

    def run_trace(self, run_id: str) -> dict[str, Any]:
        """Deliveries, events and access report for one run."""
        status, raw = self._request("GET", f"/api/gate/runs/{run_id}", b"", "")
        if status >= 400:
            raise RuntimeError(f"run_trace -> {status}: {raw[:200]!r}")
        return json.loads(raw)
