export function getSupabaseConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey || url === "undefined" || anonKey === "undefined") {
    return null;
  }
  return { url, anonKey };
}

export function getApiUrl() {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

/** Canonical public app URL (custom domain). Falls back to browser origin on client. */
export function getAppUrl(): string {
  const configured = process.env.NEXT_PUBLIC_APP_URL?.trim().replace(/\/$/, "");
  if (configured) return configured;
  if (typeof window !== "undefined") return window.location.origin;
  return "http://localhost:3000";
}

export const CONFIG_ERROR =
  "App configuration missing. In Vercel, set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY, then redeploy.";
