import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import { getSupabaseConfig } from "../env";

export function createServerSupabaseClient() {
  const config = getSupabaseConfig();
  if (!config) {
    throw new Error("Supabase is not configured.");
  }

  const cookieStore = cookies();

  return createServerClient(config.url, config.anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        } catch {
          // setAll can fail in Server Components; route handlers are fine.
        }
      },
    },
  });
}
