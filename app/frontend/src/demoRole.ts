// Demo role shared by the Live Gate, Trace and Reviewer pages (CL-78).
// It is a demo role, not authentication: the server honours the
// X-Demo-Role header only when COVERTLENS_DEMO_ROLES is on, and
// otherwise treats every request as a viewer. The choice is kept for
// the browser tab so it carries across pages.

import { useCallback, useState } from "react";

export const DEMO_ROLES = ["viewer", "researcher", "reviewer"] as const;
const STORAGE_KEY = "covertlens:demo-role";

export function loadDemoRole(): string {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored && (DEMO_ROLES as readonly string[]).includes(stored)) return stored;
  } catch {
    // Storage unavailable: fall back to the least-privileged role.
  }
  return "viewer";
}

export function useDemoRole(): [string, (role: string) => void] {
  const [role, setRoleState] = useState(loadDemoRole);
  const setRole = useCallback((next: string) => {
    setRoleState(next);
    try {
      sessionStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage unavailable: the role still applies on this page.
    }
  }, []);
  return [role, setRole];
}

export function roleHeaders(role: string): Record<string, string> {
  return { "X-Demo-Role": role };
}
