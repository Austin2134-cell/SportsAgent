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

export const CONFIG_ERROR =
  "App configuration missing. In Vercel, set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY, then redeploy.";
