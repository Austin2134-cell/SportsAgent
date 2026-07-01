"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { CONFIG_ERROR, getSupabaseConfig } from "@/lib/env";
import { clearAuthHash, parseAuthHash, redirectAfterAuth } from "@/lib/auth-routing";

/** Handles magic-link sign-in hashes. Password recovery stays on /reset-password. */
export function AuthHashHandler() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const tokens = parseAuthHash();
    if (!tokens || !getSupabaseConfig()) return;

    if (tokens.type === "recovery") {
      if (pathname !== "/reset-password") {
        router.replace(`/reset-password${window.location.hash}`);
      }
      return;
    }

    const supabase = createClient();
    supabase.auth
      .setSession({
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
      })
      .then(({ error }) => {
        clearAuthHash();
        if (error) return;
        redirectAfterAuth(tokens.access_token, router, tokens.type);
      });
  }, [router, pathname]);

  return null;
}
