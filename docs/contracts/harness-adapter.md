# Harness adapter contract (CL-64)

Implements: CL-64 (traces EV-06, OP-08). Blocked by CL-53.

`covertlens.gate_client.GateClient` wraps the Live Gate HTTP API
for harness engineers:

| Method | Service call | Failure |
|---|---|---|
| `intercept(route, bytes, ctx)` | stages a `GateHandle` locally | — |
| `attempt(handle, recipient)` | `POST /api/gate/deliveries` (multipart) | `RuntimeError` on 4xx |
| `analyze(delivery_id)` | `POST .../analyze` | `RuntimeError` on 4xx |
| `record_verdict(delivery_id, verdict)` | `POST .../verdict` (needs a permitted demo role) | `RuntimeError` on 4xx |
| `access(delivery_id)` | `GET .../recipient-image` | `PendingDeliveryError` (409), `WithheldError` (403), `KeyError` (404) |
| `run_trace(run_id)` | `GET /api/gate/runs/{run_id}` | `RuntimeError` on 4xx |

The exceptions are the library's own (`covertlens.gate`), so
harness code handles HTTP and in-process gates identically. The
client is standard-library only. Demo roles are not
authentication (CL-78): `demo_role` is sent as `X-Demo-Role` and
honoured only with `COVERTLENS_DEMO_ROLES=on`.

## Example

[examples/harness_example.py](../../examples/harness_example.py)
moves a clean and an encoded image between two stub agents: the
clean delivery is permitted and received; the encoded delivery is
quarantined, `access` raises `WithheldError`, and no bytes reach
the recipient. Run it against `docker run` of the image (see the
file's docstring); both delivery traces are printed.

## Verification

`tests/test_gate_client.py` covers the status-to-exception mapping
and the permitted/withheld flows against a stub HTTP service.
