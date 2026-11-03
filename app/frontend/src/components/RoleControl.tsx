// Role control for evidence pages (CL-67). OIDC mode shows who you
// are signed in as; the demo picker exists only in demo builds and is
// shown only when the server is in demo mode.
import type { AuthInfo } from "../auth";
import { loginHref, signOut, useAuth } from "../auth";
import { DEMO_BUILD } from "../build";
import { DemoRoleSelect } from "./DemoRoleSelect";

export function RoleControl({
  role,
  onChange,
  disabled,
  hint,
}: {
  role: string;
  onChange: (role: string) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const [info, refresh] = useAuth();
  if (DEMO_BUILD && info?.auth_mode !== "oidc") {
    return <DemoRoleSelect role={role} onChange={onChange} disabled={disabled} hint={hint} />;
  }
  return (
    <SignInStatus
      info={info}
      path={typeof window === "undefined" ? "/" : window.location.pathname}
      hint={hint}
      onSignOut={() => {
        void signOut().then(refresh);
      }}
    />
  );
}

// Pure view, exported for server-side render tests.
export function SignInStatus({
  info,
  path,
  hint,
  onSignOut,
}: {
  info: AuthInfo | null;
  path: string;
  hint?: string;
  onSignOut?: () => void;
}) {
  if (info === null) {
    return <p className="note">Checking sign-in…</p>;
  }
  if (info.auth_mode !== "oidc") {
    return (
      <p className="alert" role="alert" data-testid="auth-off">
        Sign-in is not configured on this server, so every request acts as a
        viewer and evidence stays closed. Set COVERTLENS_AUTH_MODE=oidc with
        your identity provider to enable real roles.
      </p>
    );
  }
  if (!info.authenticated) {
    return (
      <div className="demo-role" data-testid="signed-out">
        <p>
          You are not signed in, so evidence stays closed.{" "}
          <a className="button" href={loginHref(info, path)}>
            Sign in
          </a>
        </p>
        {hint && <p className="note">{hint}</p>}
      </div>
    );
  }
  const roles = info.roles && info.roles.length > 0 ? info.roles.join(", ") : "viewer";
  const scopes =
    info.dataset_patterns && info.dataset_patterns.length > 0
      ? info.dataset_patterns.join(", ")
      : "none";
  return (
    <div className="demo-role" data-testid="signed-in">
      <p>
        Signed in as <strong>{info.display_name || info.actor_id}</strong> ({info.actor_id})
        {" · "}roles: {roles}{" · "}runs: {scopes}{" "}
        {onSignOut && (
          <button type="button" className="button" onClick={onSignOut}>
            Sign out
          </button>
        )}
      </p>
      {hint && <p className="note">{hint}</p>}
    </div>
  );
}
