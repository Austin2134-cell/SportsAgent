import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { api } from "./api";

export async function redirectAfterAuth(
  token: string,
  router: AppRouterInstance,
  type?: string | null,
) {
  if (type === "recovery") {
    router.replace("/reset-password");
    return;
  }
  try {
    const agent = await api.getAgent(token);
    router.replace(agent?.provisioned ? "/agent" : "/setup");
  } catch {
    router.replace("/setup");
  }
}

export function parseAuthHash() {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash || !hash.includes("access_token")) return null;
  const params = new URLSearchParams(hash);
  const access_token = params.get("access_token");
  const refresh_token = params.get("refresh_token");
  if (!access_token || !refresh_token) return null;
  return {
    access_token,
    refresh_token,
    type: params.get("type"),
  };
}

export function clearAuthHash() {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}
