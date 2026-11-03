// CL-67: sign-in status in OIDC mode; demo builds keep the demo header.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { SignInStatus } from "../src/components/RoleControl";
import { loginHref } from "../src/auth";
import { roleHeaders } from "../src/demoRole";
import { DEMO_BUILD } from "../src/build";

test("signed-out OIDC users get a sign-in link that returns to the page", () => {
  const info = { auth_mode: "oidc" as const, demo_build: true, authenticated: false, login_url: "/api/auth/login" };
  const html = renderToStaticMarkup(<SignInStatus info={info} path="/review" />);
  assert.match(html, /data-testid="signed-out"/);
  assert.match(html, /href="\/api\/auth\/login\?next=%2Freview"/);
  assert.equal(loginHref(info, "/trace"), "/api/auth/login?next=%2Ftrace");
});

test("signed-in users see their actor, roles and run scopes", () => {
  const html = renderToStaticMarkup(
    <SignInStatus
      info={{
        auth_mode: "oidc",
        demo_build: false,
        authenticated: true,
        actor_id: "oidc:rita",
        display_name: "Rita",
        roles: ["researcher"],
        dataset_patterns: ["run_*"],
      }}
      path="/review"
      onSignOut={() => undefined}
    />,
  );
  assert.match(html, /Signed in as <strong>Rita<\/strong> \(oidc:rita\)/);
  assert.match(html, /roles: researcher/);
  assert.match(html, /runs: run_\*/);
  assert.match(html, /Sign out/);
});

test("a non-demo build without OIDC says sign-in is not configured", () => {
  const html = renderToStaticMarkup(
    <SignInStatus info={{ auth_mode: "off", demo_build: false, authenticated: false }} path="/" />,
  );
  assert.match(html, /data-testid="auth-off"/);
});

test("the demo build (tests' default) still sends X-Demo-Role", () => {
  assert.equal(DEMO_BUILD, true);
  assert.deepEqual(roleHeaders("reviewer"), { "X-Demo-Role": "reviewer" });
});
