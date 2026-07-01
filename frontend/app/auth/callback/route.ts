import { NextResponse } from "next/server";
import { createServerSupabaseClient } from "@/lib/supabase/server";

/** Exchange Supabase PKCE `code` for a session cookie, then redirect (password reset, OAuth). */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/dashboard";
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";

  if (!code) {
    return NextResponse.redirect(`${origin}/reset-password?error=missing_code`);
  }

  try {
    const supabase = createServerSupabaseClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      console.error("[auth/callback] exchangeCodeForSession:", error.message);
      return NextResponse.redirect(
        `${origin}/reset-password?error=${encodeURIComponent(error.message)}`,
      );
    }
  } catch (e) {
    console.error("[auth/callback] setup failed:", e);
    return NextResponse.redirect(`${origin}/reset-password?error=auth_config`);
  }

  return NextResponse.redirect(`${origin}${safeNext}`);
}
