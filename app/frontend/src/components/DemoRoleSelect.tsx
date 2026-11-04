// Demo-role picker for pages that read evidence or change gate state
// (CL-78). Permissions shown come from the server's runtime policy.

import { useEffect, useState } from "react";
import type { DemoRoles } from "../types";
import { fetchDemoRoles } from "../api";
import { DEMO_ROLES } from "../demoRole";

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
  return (
    <div className="demo-role">
      <label>
        Pretend to be this kind of user, for this demonstration only (demo role — not authentication, anyone can pick any role here)
        <select value={role} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          {roles.map((r) => (
            <option key={r.role} value={r.role}>
              {r.role} ({r.actorId})
            </option>
          ))}
        </select>
      </label>
      <p className="note">
        A <strong>viewer</strong> can only look at public pages. A{" "}
        <strong>researcher</strong> can run the experiment, decide
        deliveries and export records. A <strong>reviewer</strong> can open
        held-back originals and record judgements. Everything a role opens
        is written into an audit record.
      </p>
      {permissions && (
        <p className="note">
          This kind of user may (exact permission names):{" "}
          {permissions.length > 0 ? permissions.join(", ") : "none (deny-by-default)"}.
        </p>
      )}
      {hint && <p className="note">{hint}</p>}
      {!enabled && (
        <p className="alert" role="alert" data-testid="demo-roles-off">
          The demonstration user-picker is switched off on this server, so
          you are treated as a viewer and the originals stay closed. What
          to do: ask whoever runs this server to enable it for a
          demonstration (they set COVERTLENS_DEMO_ROLES=on — only
          appropriate for a demo, never for real use).
        </p>
      )}
    </div>
  );
}
