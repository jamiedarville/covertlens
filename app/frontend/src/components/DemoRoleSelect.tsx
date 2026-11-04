// Demo-role picker for pages that read evidence or change gate state
// (CL-78). Permissions shown come from the server's runtime policy.

import { useEffect, useState } from "react";
import type { DemoRoles } from "../types";
import { fetchDemoRoles } from "../api";
import { DEMO_ROLES } from "../demoRole";
import { ROLE_PLAIN } from "../format";
import { TechDetails } from "./Help";

export function DemoRoleSelect({
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
  const [info, setInfo] = useState<DemoRoles | null>(null);

  useEffect(() => {
    fetchDemoRoles()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  const roles = info?.roles ?? DEMO_ROLES.map((r) => ({ role: r, actor_id: `demo-${r}`, label: "", permissions: [] }));
  const active = info?.roles.find((r) => r.role === role);

  return (
    <DemoRoleView
      roles={roles.map((r) => ({ role: r.role, actorId: r.actor_id }))}
      role={role}
      onChange={onChange}
      disabled={disabled}
      hint={hint}
      enabled={info?.enabled ?? true}
      permissions={active ? active.permissions : null}
    />
  );
}

// Pure view, exported for server-side render tests.
export function DemoRoleView({
  roles,
  role,
  onChange,
  disabled,
  hint,
  enabled,
  permissions,
}: {
  roles: { role: string; actorId: string }[];
  role: string;
  onChange: (role: string) => void;
  disabled?: boolean;
  hint?: string;
  enabled: boolean;
  permissions: string[] | null;
}) {
  const active = roles.find((r) => r.role === role);
  return (
    <div className="demo-role">
      <label>
        Who are you in this demo?
        <select value={role} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          {roles.map((r) => (
            <option key={r.role} value={r.role}>
              {ROLE_PLAIN[r.role] ?? r.role}
            </option>
          ))}
        </select>
      </label>
      {hint && <p className="note">{hint}</p>}
      <p className="note">
        This is only a demonstration (a demo role — not authentication):
        anyone can pick any role, and everything a role opens is recorded.
      </p>
      <TechDetails summary="Exact permissions for this role">
        <p className="note">
          Acting as {active?.actorId ?? role}.{" "}
          {permissions
            ? `This kind of user may (exact permission names): ${permissions.length > 0 ? permissions.join(", ") : "none (deny-by-default)"}.`
            : "The server’s permission list is not available right now."}
        </p>
      </TechDetails>
      {!enabled && (
        <p className="alert" role="alert" data-testid="demo-roles-off">
          The demo role picker is switched off on this server, so you are
          treated as a viewer and held-back images stay closed. What to do:
          ask whoever runs this server to turn it on for a demonstration
          (they set COVERTLENS_DEMO_ROLES=on, which is only for demos,
          never for real use).
        </p>
      )}
    </div>
  );
}
