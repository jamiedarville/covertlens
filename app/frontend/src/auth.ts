// Who the server says we are (CL-67): GET /api/auth/me.
import { useEffect, useState } from "react";

export interface AuthInfo {
  auth_mode: "oidc" | "demo" | "off";
  demo_build: boolean;
  authenticated: boolean;
  actor_id?: string;
  display_name?: string;
  roles?: string[];
  dataset_patterns?: string[];
  auth_method?: string;
  login_url?: string;
}

export async function fetchAuth(): Promise<AuthInfo> {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (!response.ok) throw new Error(`auth status ${response.status}`);
  return (await response.json()) as AuthInfo;
}

export async function signOut(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
}

export function loginHref(info: AuthInfo, path: string): string {
  const base = info.login_url ?? "/api/auth/login";
  return `${base}?next=${encodeURIComponent(path)}`;
}

export function useAuth(): [AuthInfo | null, () => void] {
  const [info, setInfo] = useState<AuthInfo | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetchAuth()
      .then((next) => {
        if (!cancelled) setInfo(next);
      })
      .catch(() => {
        if (!cancelled) setInfo(null);
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  return [info, () => setVersion((v) => v + 1)];
}
