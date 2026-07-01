"use client";
import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { CONFIG_ERROR, getSupabaseConfig } from "@/lib/env";
import { clearAuthHash, parseAuthHash, redirectAfterAuth } from "@/lib/auth-routing";

type VerifyState = "loading" | "ready" | "error";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [verifyState, setVerifyState] = useState<VerifyState>("loading");

  useEffect(() => {
    if (!getSupabaseConfig()) {
      setError(CONFIG_ERROR);
      setVerifyState("error");
      return;
    }

    const urlError = searchParams.get("error");
    if (urlError) {
      setError(decodeURIComponent(urlError === "auth_config" ? CONFIG_ERROR : urlError));
      setVerifyState("error");
      return;
    }

    const supabase = createClient();
    let cancelled = false;

    async function establishSession() {
      // 1) Hash tokens (#access_token=...&type=recovery)
      const tokens = parseAuthHash();
      if (tokens) {
        const { error: sessionError } = await supabase.auth.setSession({
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
        });
        clearAuthHash();
        if (!sessionError && !cancelled) {
          setVerifyState("ready");
          return;
        }
        if (sessionError && !cancelled) {
          setError(sessionError.message);
          setVerifyState("error");
          return;
        }
      }

      // 2) Query OTP (token_hash=...&type=recovery)
      const tokenHash = searchParams.get("token_hash");
      const otpType = searchParams.get("type");
      if (tokenHash && otpType === "recovery") {
        const { error: otpError } = await supabase.auth.verifyOtp({
          token_hash: tokenHash,
          type: "recovery",
        });
        if (!otpError && !cancelled) {
          setVerifyState("ready");
          router.replace("/reset-password");
          return;
        }
        if (otpError && !cancelled) {
          setError(otpError.message);
          setVerifyState("error");
          return;
        }
      }

      // 3) PKCE code (?code=...) — client fallback if callback route was skipped
      const code = searchParams.get("code");
      if (code) {
        const { error: codeError } = await supabase.auth.exchangeCodeForSession(code);
        if (!codeError && !cancelled) {
          setVerifyState("ready");
          router.replace("/reset-password");
          return;
        }
        if (codeError && !cancelled) {
          setError(codeError.message);
          setVerifyState("error");
          return;
        }
      }

      // 4) Existing session (e.g. after /auth/callback)
      const { data: { session } } = await supabase.auth.getSession();
      if (session && !cancelled) {
        setVerifyState("ready");
        return;
      }

      if (!cancelled) {
        setError("This reset link is invalid or has expired. Request a new one from the login page.");
        setVerifyState("error");
      }
    }

    establishSession();

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") {
        setVerifyState("ready");
      }
    });

    const timeout = window.setTimeout(() => {
      if (!cancelled) {
        setVerifyState((prev) => {
          if (prev === "loading") {
            setError("Could not verify reset link. Try opening the link in the same browser where you requested it, or request a new link.");
            return "error";
          }
          return prev;
        });
      }
    }, 12000);

    return () => {
      cancelled = true;
      subscription.unsubscribe();
      window.clearTimeout(timeout);
    };
  }, [router, searchParams]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (!getSupabaseConfig()) {
        setError(CONFIG_ERROR);
        return;
      }
      const supabase = createClient();
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) {
        setError(updateError.message);
        return;
      }
      const { data: { session } } = await supabase.auth.getSession();
      if (session) {
        await redirectAfterAuth(session.access_token, router);
      } else {
        router.push("/login");
      }
      router.refresh();
    } catch {
      setError("Could not update password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm fade-in">
      <div className="text-center mb-8">
        <Link href="/" className="text-[#00d084] text-2xl font-bold tracking-widest glow-green">AGENTEDGE</Link>
        <p className="text-[#71717a] text-xs mt-2 tracking-widest">SET NEW PASSWORD</p>
      </div>

      {verifyState === "loading" && (
        <div className="text-center text-xs text-[#71717a]">
          <p>Verifying reset link...</p>
        </div>
      )}

      {verifyState === "error" && (
        <div className="space-y-4">
          <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d] leading-relaxed">
            {error || "Reset link invalid or expired."}
          </div>
          <Link
            href="/login"
            className="block w-full text-center bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872]"
          >
            BACK TO LOGIN →
          </Link>
        </div>
      )}

      {verifyState === "ready" && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-[#71717a] tracking-widest mb-1">NEW PASSWORD</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoFocus
              className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]"
              placeholder="••••••••"
            />
          </div>
          <div>
            <label className="block text-xs text-[#71717a] tracking-widest mb-1">CONFIRM PASSWORD</label>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={8}
              className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]"
              placeholder="••••••••"
            />
          </div>
          {error && (
            <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50"
          >
            {loading ? "UPDATING..." : "UPDATE PASSWORD →"}
          </button>
        </form>
      )}
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col items-center justify-center px-4">
      <Suspense fallback={
        <div className="text-center text-xs text-[#71717a]">Verifying reset link...</div>
      }>
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}
