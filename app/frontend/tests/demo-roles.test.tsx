// CL-78: evidence and gate-state requests carry the demo role, and
// the role picker says when the server ignores it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ApiError,
  createGateRun,
  fetchReviewAudit,
  fetchReviewerImage,
  fetchTraceRun,
  recordGateVerdict,
} from "../src/api";
import { DemoRoleView } from "../src/components/DemoRoleSelect";

type Call = { url: string; init?: RequestInit };

function stubFetch(status: number, body: unknown, contentType = "application/json") {
  const calls: Call[] = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const payload = typeof body === "string" ? body : JSON.stringify(body);
    return new Response(payload, { status, headers: { "Content-Type": contentType } });
  }) as typeof fetch;
  return calls;
}

function header(call: Call, name: string): string | undefined {
  const headers = (call.init?.headers ?? {}) as Record<string, string>;
  return headers[name];
}

test("reviewer image is fetched with the demo role, never an actor_id", async () => {
  const calls = stubFetch(200, "PNGBYTES", "image/png");
  const blob = await fetchReviewerImage("dlv_1", "reviewer");
  assert.equal(await blob.text(), "PNGBYTES");
  assert.equal(calls[0].url, "/api/gate/deliveries/dlv_1/reviewer-image");
  assert.ok(!calls[0].url.includes("actor_id"));
  assert.equal(header(calls[0], "X-Demo-Role"), "reviewer");
});

test("a denied reviewer image raises with the server's status", async () => {
  stubFetch(403, { detail: "reviewer access denied" });
  await assert.rejects(fetchReviewerImage("dlv_1", "viewer"), (err: unknown) => {
    return (err as { status?: number }).status === 403;
  });
});

test("verdict, trace and audit requests send the demo role", async () => {
  const calls = stubFetch(200, { deliveries: [], entries: [] });
  await recordGateVerdict("dlv_1", "quarantine", "researcher");
  await fetchTraceRun("run_1", "reviewer");
  await fetchReviewAudit("run_1", "researcher");
  assert.deepEqual(
    calls.map((c) => header(c, "X-Demo-Role")),
    ["researcher", "reviewer", "researcher"],
  );
  assert.equal(header(calls[0], "Content-Type"), "application/json");
});

test("role picker warns when the server has demo roles switched off", () => {
  const roles = [
    { role: "viewer", actorId: "demo-viewer" },
    { role: "researcher", actorId: "demo-researcher" },
  ];
  const off = renderToStaticMarkup(
    <DemoRoleView roles={roles} role="researcher" onChange={() => {}} enabled={false} permissions={null} />,
  );
  assert.match(off, /data-testid="demo-roles-off"/);
  assert.match(off, /not authentication/);
  const on = renderToStaticMarkup(
    <DemoRoleView roles={roles} role="viewer" onChange={() => {}} enabled permissions={[]} />,
  );
  assert.doesNotMatch(on, /demo-roles-off/);
  assert.match(on, /none \(deny-by-default\)/);
});

// Conflict regression: preserve main's declared-channel API and useful errors
// alongside the plain-English session wording.
test("starting a session forwards openly declared shape measurements", async () => {
  const calls = stubFetch(200, { run_id: "session-1" });
  assert.equal(await createGateRun("session-1", ["height", "gap"]), "session-1");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    run_id: "session-1",
    declared_channels: ["height", "gap"],
  });
});

test("session errors retain the server's reason and status", async () => {
  stubFetch(409, { detail: "Channels cannot change after the first delivery." });
  await assert.rejects(createGateRun("session-1", ["height"]), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.match(error.message, /session could not be started/);
    assert.match(error.message, /Channels cannot change after the first delivery/);
    return true;
  });
});
