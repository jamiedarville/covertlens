import { useEffect, useState } from "react";
import type { AnalyzePayload } from "../types";
import { roleHeaders, useDemoRole } from "../demoRole";
import { RoleControl } from "../components/RoleControl";
import { SimpleResult } from "../components/TrafficLight";
import { TechDetails } from "../components/Help";

interface Demo {
  id: string;
  run_id: string;
  scene: string;
  state:
    | "ready"
    | "blocked"
    | "sending"
    | "sent"
    | "receiver_failed"
    | "delivery_changed";
  analysis: AnalyzePayload | null;
  sender: { model: string; request_id: string | null };
  receiver: {
    model: string;
    message: string | null;
    request_id: string | null;
  } | null;
  receiver_attempt?: number;
  receiver_error?: { code: string; message: string; http_status?: number };
  recovery: "not_observed" | "recovered" | "not_recovered" | "unknown";
}
interface Config {
  enabled: boolean;
  sender_model: string;
  receiver_model: string;
}

async function demoRequest<T>(
  path: string,
  role: string,
  body?: object,
): Promise<T> {
  const response = await fetch(`/api/agent-demo${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", ...roleHeaders(role) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 403)
      throw new Error(
        "Choose Researcher in the user selector to run this demo.",
      );
    if (response.status === 429)
      throw new Error("Please wait a minute before trying this step again.");
    throw new Error(result.detail || "This step could not finish. Try again.");
  }
  return result as T;
}

export default function AgentDemo() {
  const [role, setRole] = useDemoRole();
  const [config, setConfig] = useState<Config | null>(null);
  const [scene, setScene] = useState("house");
  const [message, setMessage] = useState("HELLO WORLD");
  const [show, setShow] = useState(false);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [demo, setDemo] = useState<Demo | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    demoRequest<Config>("/config", role)
      .then((value) => {
        if (active) setConfig(value);
      })
      .catch(() => {
        if (active)
          setError(
            "The API connection could not be checked. Reload this page.",
          );
      });
    const id = new URLSearchParams(window.location.search).get("demo");
    // Clear any evidence fetched under the previous role before loading again.
    setDemo(null);
    setImage(null);
    setShow(false);
    setRevealed(null);
    if (id) {
      Promise.all([
        demoRequest<Demo>(`/${encodeURIComponent(id)}`, role),
        demoRequest<{ image_url: string }>(
          `/${encodeURIComponent(id)}/image`,
          role,
          {},
        ),
      ])
        .then(([value, picture]) => {
          if (active) {
            setDemo(value);
            setImage(picture.image_url);
          }
        })
        .catch((e: Error) => {
          if (active) setError(e.message);
        });
    }
    return () => {
      active = false;
    };
  }, [role]);

  async function perform(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "This step could not finish. Try again.",
      );
    } finally {
      setBusy("");
    }
  }

  async function create() {
    await perform("The sender is making the picture…", async () => {
      const next = await demoRequest<Demo>("", role, { scene, message });
      setDemo(next);
      setShow(false);
      setRevealed(null);
      window.history.replaceState(null, "", `/demo?demo=${next.id}`);
      const picture = await demoRequest<{ image_url: string }>(
        `/${next.id}/image`,
        role,
        {},
      );
      setImage(picture.image_url);
    });
  }

  async function step(action: "analyze" | "block" | "send" | "retry") {
    if (!demo) return;
    const labels = {
      analyze: "Checking the picture…",
      block: "Blocking delivery…",
      send: "Sending the picture and waiting for the receiver…",
      retry: "Asking the receiver to read the picture again…",
    };
    await perform(labels[action], async () => {
      try {
        setDemo(
          await demoRequest<Demo>(
            `/${demo.id}/${action}`,
            role,
            action === "retry" ? { attempt: demo.receiver_attempt ?? 1 } : {},
          ),
        );
      } catch (failure) {
        // A provider call can fail after delivery. Restore the saved outcome.
        setDemo(await demoRequest<Demo>(`/${demo.id}`, role));
        throw failure;
      }
    });
  }

  async function toggleMessage() {
    if (show) {
      setShow(false);
      return;
    }
    if (!demo) {
      setShow(true);
      return;
    }
    await perform("Opening the sender’s message…", async () => {
      const result = await demoRequest<{ message: string }>(
        `/${demo.id}/show`,
        role,
        {},
      );
      setRevealed(result.message);
      setShow(true);
    });
  }

  function reset() {
    window.history.replaceState(null, "", "/demo");
    setDemo(null);
    setImage(null);
    setShow(false);
    setRevealed(null);
    setError("");
  }

  const ready = demo?.state === "ready";
  const canSend =
    ready &&
    demo?.analysis?.status === "parsed" &&
    demo.analysis.decision?.delivery === "permit";
  return (
    <>
      <h1>Two agents. One hidden message.</h1>
      <p>
        Watch a sender put two words into a picture’s shapes. Check the picture,
        choose whether to send it, then see what the receiver can read.
      </p>
      <RoleControl
        role={role}
        onChange={setRole}
        disabled={!!busy}
        hint="Choose Researcher to make pictures and decide whether they are sent."
      />
      {config && (
        <p className="note">
          Sender uses {config.sender_model}. Receiver uses{" "}
          {config.receiver_model} in a separate conversation.
        </p>
      )}
      {config && !config.enabled && (
        <p className="alert">
          The agent API needs to be connected on this server. Ask the person
          running the demo to add the Muse API key.
        </p>
      )}
      <p role="status" aria-live="polite">
        {busy}
      </p>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      <div className="agent-demo-flow">
        <section className="card" aria-labelledby="sender-title">
          <h2 id="sender-title">1. Sender agent</h2>
          {!demo ? (
            <>
              <label>
                Make a picture of
                <select
                  value={scene}
                  onChange={(e) => setScene(e.target.value)}
                  disabled={!!busy}
                >
                  <option value="house">A house</option>
                  <option value="garden">A garden</option>
                  <option value="night_sky">A night sky</option>
                  <option value="skyline">A skyline</option>
                </select>
              </label>
              <label>
                Two-word message
                <input
                  type={show ? "text" : "password"}
                  value={message}
                  maxLength={17}
                  onChange={(e) => setMessage(e.target.value)}
                  disabled={!!busy}
                  autoComplete="off"
                />
              </label>
              <p className="note">Use two words, up to eight letters each.</p>
              <button
                className="button"
                type="button"
                onClick={toggleMessage}
                aria-pressed={show}
                disabled={!!busy}
              >
                {show ? "Hide" : "Show"} message
              </button>{" "}
              <button
                className="button button-primary"
                type="button"
                onClick={create}
                disabled={!!busy || !config?.enabled}
              >
                Make the picture
              </button>
            </>
          ) : (
            <>
              {image && (
                <img
                  className="skyline-img"
                  src={image}
                  alt={`The sender’s ${demo.scene.replaceAll("_", " ")} picture`}
                />
              )}
              <p>
                The sender used a drawing tool to put its message into the
                heights of the small shapes along the bottom.
              </p>
              <button
                className="button"
                type="button"
                onClick={toggleMessage}
                disabled={!!busy}
                aria-expanded={show}
              >
                {show ? "Hide" : "Show"} sender’s message
              </button>
              {show && <p className="demo-message">{revealed}</p>}
            </>
          )}
        </section>

        <section className="card" aria-labelledby="check-title">
          <h2 id="check-title">2. Check and decide</h2>
          {!demo ? (
            <p>Make a picture first.</p>
          ) : (
            <>
              {!demo.analysis ? (
                <p>
                  The picture is waiting here. The receiver has not seen it.
                </p>
              ) : (
                <SimpleResult payload={demo.analysis} />
              )}
              {ready && (
                <>
                  <p>
                    <button
                      className="button button-primary"
                      onClick={() => step("analyze")}
                      disabled={!!busy || !!demo.analysis}
                    >
                      Check for a hidden message
                    </button>
                  </p>
                  <p>
                    <button
                      className="button"
                      onClick={() => step("block")}
                      disabled={!!busy}
                    >
                      Block the picture
                    </button>{" "}
                    <button
                      className="button button-primary"
                      onClick={() => step("send")}
                      disabled={!!busy || !canSend}
                    >
                      Send to receiver
                    </button>
                  </p>
                  {!demo.analysis && (
                    <p className="note">
                      Run the check to enable sending. You can block at any
                      time.
                    </p>
                  )}
                  {demo.analysis && !canSend && (
                    <p className="note">
                      The engine held this picture back. Block it, then try
                      another message or scene.
                    </p>
                  )}
                </>
              )}
              {demo.analysis && (
                <TechDetails summary="See the technical evidence">
                  <pre className="demo-json">
                    {JSON.stringify(demo.analysis, null, 2)}
                  </pre>
                </TechDetails>
              )}
            </>
          )}
        </section>

        <section className="card" aria-labelledby="receiver-title">
          <h2 id="receiver-title">3. Receiver agent</h2>
          {!demo || ready ? (
            <p>Waiting for you to send a picture.</p>
          ) : demo.state === "blocked" ? (
            <p>
              <strong>Blocked.</strong> The receiver did not get the picture.
              Message recovery was not tested.
            </p>
          ) : demo.state === "delivery_changed" ? (
            <p>
              The delivery decision changed outside this demo. Start another
              demo to test the receiver.
            </p>
          ) : demo.state === "sending" ? (
            <p>
              The picture was sent and the receiver’s answer is pending. Reload
              to check the saved result. If the server restarted during the
              call, start another demo.
            </p>
          ) : demo.state === "receiver_failed" ? (
            <>
              <p role="alert">
                {demo.receiver_error?.message ||
                  "The receiver’s answer could not be obtained. Try the receiver again."}
              </p>
              <button
                className="button button-primary"
                onClick={() => step("retry")}
                disabled={!!busy}
              >
                Try receiver again
              </button>
              <p className="note">
                This makes another API call using the same picture.
              </p>
              <TechDetails summary="Receiver error details">
                <pre className="demo-json">
                  {JSON.stringify(
                    {
                      error: demo.receiver_error,
                      receiver: demo.receiver,
                      attempt: demo.receiver_attempt,
                    },
                    null,
                    2,
                  )}
                </pre>
              </TechDetails>
            </>
          ) : (
            <>
              <p>
                <strong>
                  {demo.recovery === "recovered"
                    ? "The receiver read the right message."
                    : "The receiver did not recover the exact message."}
                </strong>
              </p>
              <p>The receiver answered</p>
              <p className="demo-message">
                {demo.receiver?.message || "Could not read a message"}
              </p>
              <p className="note">
                Compared with the sender’s two words, ignoring capital letters
                and extra spaces.
              </p>
            </>
          )}
          <p className="note">
            The receiver gets the picture and the shared reading instructions.
            The sender’s message is kept separate.
          </p>
        </section>
      </div>
      {demo && (
        <p>
          <button className="button" onClick={reset} disabled={!!busy}>
            Start another demo
          </button>
        </p>
      )}
    </>
  );
}
