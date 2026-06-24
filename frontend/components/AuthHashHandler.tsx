"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { getSupabaseConfig } from "@/lib/env";
import { clearAuthHash, parseAuthHash, redirectAfterAuth } from "@/lib/auth-routing";

/** Consumes Supabase auth tokens from the URL hash (password recovery, magic links). */
export function AuthHashHandler() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const tokens = parseAuthHash();
    if (!tokens || !getSupabaseConfig()) return;

    const supabase = createClient();
    supabase.auth
      .setSession({
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
      })
      .then(({ error }) => {
        clearAuthHash();
        if (error) return;

        if (tokens.type === "recovery") {
          if (pathname !== "/reset-password") router.replace("/reset-password");
          return;
        }

        redirectAfterAuth(tokens.access_token, router, tokens.type);
      });
  }, [router, pathname]);

  return null;
}
