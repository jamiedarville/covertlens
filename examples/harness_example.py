"""Example harness: two stub agents, one gate (CL-64).

Moves one clean and one encoded image from agent-a to agent-b
through a running CovertLens service. The clean delivery is
permitted and its bytes reach agent-b; the encoded delivery is
quarantined, `access` raises `WithheldError`, and no bytes reach
agent-b. Both traces are printed.

Run against the demo image:

    docker run -p 8000:8000 -v covertlens-data:/data \
        ghcr.io/jamiedarville/covertlens:v0.1.0
    python examples/harness_example.py [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse

from covertlens.fixtures import build_pair
from covertlens.gate import WithheldError
from covertlens.gate_client import GateClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    client = GateClient(args.base_url, demo_role="researcher")
    run_id = client.create_run()
    received: list[int] = []  # what stub agent-b actually got

    clean, encoded = build_pair("spatial_lsb", payload_bytes=64)
    for label, image, verdict in (
        ("clean", clean.data, "log"),
        ("encoded", encoded.data, "quarantine"),
    ):
        handle = client.intercept(
            "R-01", image, {"run_id": run_id, "sender_id": "agent-a"}
        )
        delivery = client.attempt(handle, "agent-b")
        delivery_id = delivery["delivery_id"]
        print(f"{label}: attempted {delivery_id} -> {delivery['state']}")
        client.record_verdict(delivery_id, verdict)
        try:
            data = client.access(delivery_id)
            received.append(len(data))
            print(f"{label}: agent-b received {len(data)} bytes")
        except WithheldError as exc:
            print(f"{label}: withheld, agent-b received nothing ({exc})")

    trace = client.run_trace(run_id)
    for row in trace["deliveries"]:
        print(
            f"trace: {row['delivery_id']} {row['state']} "
            f"verdict={row['verdict']} hash={row['content_hash'][:19]}..."
        )
    assert len(received) == 1, "exactly the permitted delivery may arrive"
    print("OK: 1 permitted, 1 withheld, 0 withheld bytes delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
