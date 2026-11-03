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
        Acting as (demo role — not authentication)
        <select value={role} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          {roles.map((r) => (
            <option key={r.role} value={r.role}>
              {r.role} ({r.actorId})
            </option>
          ))}
        </select>
      </label>
      {permissions && (
        <p className="note">
          Permissions: {permissions.length > 0 ? permissions.join(", ") : "none (deny-by-default)"}.
        </p>
      )}
      {hint && <p className="note">{hint}</p>}
      {!enabled && (
        <p className="alert" role="alert" data-testid="demo-roles-off">
          Demo roles are switched off on this server, so every request acts
          as viewer and evidence stays closed. Set COVERTLENS_DEMO_ROLES=on
          only for a demo deployment.
        </p>
      )}
    </div>
  );
}
