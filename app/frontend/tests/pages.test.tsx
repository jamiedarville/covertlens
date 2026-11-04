// CL-78: Overlay, Live Gate and Review page rendering.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { Overlay } from "../src/components/Overlay";
import { RecipientPane, ReviewerPane } from "../src/pages/LiveGate";
import { CandidateDecodePanel, QueueTable } from "../src/pages/Review";
import type { AnalyzePayload, GateDelivery, ReviewQueue } from "../src/types";
import structured from "./fixtures/analyze-structured.json";

const payload = structured as unknown as AnalyzePayload;

function delivery(state: string, message: string): GateDelivery {
  return {
    delivery_id: "dlv_0123456789abcdef0123",
    run_id: "run_1",
    episode_id: null,
    artifact_id: "art_1",
    artifact_version_id: "ver_1",
    content_hash: "sha256:" + "0".repeat(64),
    sender_id: "agent-a",
    recipient_id: "agent-b",
    attempt: 1,
    state,
    verdict: state === "withheld" ? "quarantine" : state === "permitted" ? "log" : null,
    verdict_id: null,
    infrastructure_error: null,
    recipient_message: message,
  } as GateDelivery;
}

test("overlay shows the classification and a digest, never the symbol sequence", () => {
  const html = renderToStaticMarkup(
    <Overlay geometric={payload.geometric} imageUrl="blob:scene" imageLabel="scene" />,
  );
  assert.match(html, /Structure claimed/);
  assert.match(html, /Evidence aid — not a decoded message/);
  assert.match(html, /data-testid="symbols-digest"/);
  assert.match(html, /sha256:[0-9a-f]{12}…/);
  assert.match(html, /reviewer-only/);
  // The API carries no symbol list, so nothing can print one.
  for (const channel of Object.values(payload.geometric?.channels ?? {})) {
    assert.equal((channel as Record<string, unknown>).symbols, undefined);
  }
  assert.doesNotMatch(html, /DECAF/);
  assert.doesNotMatch(html, /Grid symbols \(numeric only\)/);
});

test("overlay explains a failed segmentation instead of drawing boxes", () => {
  const html = renderToStaticMarkup(
    <Overlay
      geometric={{
        status: "too_few_elements",
        classification: "no_signal",
        structure: null,
        chart_likeness: null,
        segmentation: null,
      } as unknown as AnalyzePayload["geometric"]}
      imageUrl={null}
      imageLabel="blank"
    />,
  );
  assert.match(html, /too_few_elements/);
  assert.match(html, /No element overlay/);
  assert.doesNotMatch(html, /<canvas/);
});

test("recipient pane never shows an image for a withheld or pending delivery", () => {
  const withheld = renderToStaticMarkup(
    <RecipientPane
      delivery={delivery("withheld", "withheld — quarantine verdict")}
      imageUrl="blob:should-not-render"
      note=""
    />,
  );
  assert.match(withheld, /data-testid="recipient-withheld"/);
  assert.match(withheld, /quarantine verdict/);
  assert.doesNotMatch(withheld, /<img/);
  const pending = renderToStaticMarkup(
    <RecipientPane delivery={delivery("pending", "pending — awaiting analysis")} imageUrl={null} note="" />,
  );
  assert.match(pending, /<strong>pending<\/strong>/);
  assert.doesNotMatch(pending, /<img/);
  const permitted = renderToStaticMarkup(
    <RecipientPane delivery={delivery("permitted", "delivered")} imageUrl="blob:ok" note="delivered" />,
  );
  assert.match(permitted, /<img[^>]*src="blob:ok"/);
});

test("reviewer pane stays closed until opened, as the chosen role", () => {
  const closed = renderToStaticMarkup(
    <ReviewerPane
      delivery={delivery("withheld", "withheld")}
      imageUrl={null}
      note=""
      role="viewer"
      busy={false}
      onOpen={() => {}}
    />,
  );
  assert.match(closed, /Open original as viewer/);
  assert.doesNotMatch(closed, /<img/);
  const denied = renderToStaticMarkup(
    <ReviewerPane
      delivery={delivery("withheld", "withheld")}
      imageUrl={null}
      note="Denied for the viewer demo role"
      role="viewer"
      busy={false}
      onOpen={() => {}}
    />,
  );
  assert.match(denied, /data-testid="reviewer-note"/);
  assert.doesNotMatch(denied, /<img/);
  const opened = renderToStaticMarkup(
    <ReviewerPane
      delivery={delivery("withheld", "withheld")}
      imageUrl="blob:original"
      note="Opened as demo-reviewer"
      role="reviewer"
      busy={false}
      onOpen={() => {}}
    />,
  );
  assert.match(opened, /<img[^>]*src="blob:original"/);
});

test("review queue says a decode exists without showing it", () => {
  const queue: ReviewQueue = {
    run_id: "run_1",
    deliveries: [],
    quarantined: [
      {
        ...delivery("withheld", "withheld"),
        disposition: "unresolved",
        has_candidate_decode: true,
        decode_id: "dec_1",
      },
    ],
  };
  const html = renderToStaticMarkup(
    <QueueTable queue={queue} selectedId={null} busy={false} onSelect={() => {}} />,
  );
  assert.match(html, /available \(reviewer only\)/);
  assert.match(html, /unresolved/);
  assert.doesNotMatch(html, /dec_1/);
});

test("candidate decode text appears only after a reviewer read", () => {
  const none = renderToStaticMarkup(
    <CandidateDecodePanel available={false} decode={null} note="" role="reviewer" busy={false} onRead={() => {}} />,
  );
  assert.match(none, /No candidate decode/);
  const unread = renderToStaticMarkup(
    <CandidateDecodePanel available decode={null} note="Denied for researcher" role="researcher" busy={false} onRead={() => {}} />,
  );
  assert.match(unread, /Read candidate decode as researcher/);
  assert.match(unread, /Denied for researcher/);
  assert.doesNotMatch(unread, /Candidate text/);
  const read = renderToStaticMarkup(
    <CandidateDecodePanel
      available
      decode={{ decode_id: "d", dataset_id: "run_1", artifact_version_id: null, code: "alphabet_position_a0", text: "DECAFDECAFDE" }}
      note=""
      role="reviewer"
      busy={false}
      onRead={() => {}}
    />,
  );
  assert.match(read, /Candidate text/);
  assert.match(read, /DECAFDECAFDE/);
});
