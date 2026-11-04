# Interactive two-agent demo

Open `/demo` in the full server application and choose Researcher. Choose a
house, garden, night sky or skyline, enter two words of up to eight letters
each, and click **Make the picture**. **Show** reveals the sender's message.
**Check for a hidden message** runs the existing engine and displays its
four traffic-light results. **Block** holds the image back. **Send to receiver**
is available when the frozen engine decision permits delivery, including
flagged deliveries. The receiver's actual answer and its comparison with the
sender's message appear in the third panel.

## Connect Muse Spark

The default model is `muse-spark-1.3` through `https://api.meta.ai/v1`.
Configure `MODEL_API_KEY` or `META_API_KEY` in the server environment.
`COVERTLENS_AGENT_DEMO_API_KEY` overrides these for this demo alone.
The server must run a demo build with `COVERTLENS_DEMO_ROLES=on`.
The Docker demo already enables demo roles. For a local launch, configure
these variables in your shell or secret manager and run `uvicorn app.main:app`.
Keys stay on the server.

Optional environment settings allow another API model to be used.

| Variable | Default or behavior |
| --- | --- |
| `COVERTLENS_AGENT_DEMO_PROVIDER` | `meta`, using Chat Completions. `anthropic` selects the Messages adapter. |
| `COVERTLENS_AGENT_DEMO_ENDPOINT` | `https://api.meta.ai/v1`, the base URL before `/chat/completions` or `/messages` |
| `COVERTLENS_AGENT_DEMO_MODEL` | `muse-spark-1.3` for both agents |
| `COVERTLENS_AGENT_DEMO_SENDER_MODEL` | Overrides the sender model |
| `COVERTLENS_AGENT_DEMO_RECEIVER_MODEL` | Overrides the receiver model |

Other providers must support the selected HTTP format. The sender needs text
output with JSON drawing arguments. The receiver needs PNG image input and
JSON text output. Native API formats beyond these two adapters need an adapter.

## How the demonstration works

The sender model produces drawing-tool arguments for the chosen scene. The
local tool uses the existing geometric fixture encoder to place the full
ASCII message in a row of shape heights. Scenery is drawn above the row.
These are simple illustrations. The model drives a drawing tool rather than
returning image bytes itself.

A separate receiver model call receives the gate-served PNG and the same
fixed reading instructions for every demo. It receives neither the secret
nor the sender transcript. The receiver measures the image itself. No local
decoder fills in its answer. A correct answer is an exact match after
normalizing capitalization and whitespace. Wrong answers and null answers
are displayed as failed recovery. Live vision-model recovery can fail.

The real, unchanged detector analyzes original image bytes. Its warning is
separate from whether the receiver recovers the words. Blocking skips the
receiver call and leaves recovery `not_observed`. Sending first records the
frozen decision through the existing persistent gate, then obtains bytes only
through `recipient_access`. Manually blocking an image remains available even
when its warning is green or orange. A withholding decision disables sending.

The demo record, image, sender request ID, analysis and receiver result are
stored under the service data directory. Reloading a demo URL reads its saved
state. A lock serializes transitions in the service's single application
process. Duplicate send requests reuse the saved result. A failed or
interrupted receiver call is never automatically repeated. Run another demo
for a fresh call. Deploy this interactive demo with one application process,
matching the existing in-process gate singleton.

This feature uses the full server application. The standalone browser-only
Analyze build continues to run image checks without server-side agents.
