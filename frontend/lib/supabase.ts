import { createBrowserClient } from "@supabase/ssr";
import { getSupabaseConfig } from "./env";

export function createClient() {
  const config = getSupabaseConfig();
  if (!config) {
    throw new Error("Supabase is not configured. Check Vercel environment variables.");
  }
  return createBrowserClient(config.url, config.anonKey);
}
