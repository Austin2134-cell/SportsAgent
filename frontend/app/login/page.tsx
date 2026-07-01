"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { CONFIG_ERROR, getAppUrl, getSupabaseConfig } from "@/lib/env";
import { redirectAfterAuth } from "@/lib/auth-routing";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [showForgot, setShowForgot] = useState(false);

  useEffect(() => {
    if (!getSupabaseConfig()) return;
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) redirectAfterAuth(session.access_token, router);
    });
  }, [router]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setInfo("");
    try {
      if (!getSupabaseConfig()) {
        setError(CONFIG_ERROR);
        return;
      }
      const supabase = createClient();
      const { data: { session }, error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password,
      });
      if (authError) {
        setError(authError.message);
        return;
      }
      if (session) {
        await redirectAfterAuth(session.access_token, router);
        router.refresh();
      }
    } catch {
      setError("Sign in failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleForgotPassword(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setInfo("");
    try {
      if (!getSupabaseConfig()) {
        setError(CONFIG_ERROR);
        return;
      }
      if (!email.trim()) {
        setError("Enter your email above first.");
        return;
      }
      const supabase = createClient();
      const { error: resetError } = await supabase.auth.resetPasswordForEmail(
        email.trim().toLowerCase(),
        {
          redirectTo: `${getAppUrl()}/auth/callback?next=${encodeURIComponent("/reset-password")}`,
        },
      );
      if (resetError) {
        setError(resetError.message);
        return;
      }
      setInfo("Password reset email sent. Check your inbox, then use the link to set a new password.");
      setShowForgot(false);
    } catch {
      setError("Could not send reset email.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm fade-in">
        <div className="text-center mb-8">
          <Link href="/" className="text-[#00d084] text-2xl font-bold tracking-widest glow-green">AGENTEDGE</Link>
          <p className="text-[#71717a] text-xs mt-2 tracking-widest">SIGN IN TO YOUR AGENT</p>
        </div>

        {showForgot ? (
          <form onSubmit={handleForgotPassword} className="space-y-4">
            <p className="text-xs text-[#71717a] leading-relaxed">
              We&apos;ll email a reset link to <span className="text-[#e4e4e7]">{email || "your email"}</span>
            </p>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">EMAIL</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" placeholder="you@example.com" />
            </div>
            {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>}
            {info && <div className="bg-[#00d084]/10 border border-[#00d084]/30 rounded px-3 py-2 text-xs text-[#00d084]">{info}</div>}
            <button type="submit" disabled={loading} className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50">
              {loading ? "SENDING..." : "SEND RESET LINK →"}
            </button>
            <button type="button" onClick={() => setShowForgot(false)} className="w-full text-xs text-[#71717a] hover:text-[#e4e4e7]">← Back to sign in</button>
          </form>
        ) : (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">EMAIL</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" placeholder="you@example.com" />
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">PASSWORD</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" placeholder="••••••••" />
            </div>
            {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d] leading-relaxed">{error}</div>}
            {info && <div className="bg-[#00d084]/10 border border-[#00d084]/30 rounded px-3 py-2 text-xs text-[#00d084]">{info}</div>}
            <button type="submit" disabled={loading} className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50">
              {loading ? "SIGNING IN..." : "SIGN IN →"}
            </button>
          </form>
        )}

        {!showForgot && (
          <p className="text-center text-xs text-[#71717a] mt-4">
            <button type="button" onClick={() => setShowForgot(true)} className="text-[#71717a] hover:text-[#00d084]">Forgot password?</button>
          </p>
        )}
        <p className="text-center text-xs text-[#71717a] mt-4">
          Need access? <Link href="/register" className="text-[#00d084] hover:underline">Register with invite code</Link>
        </p>
      </div>
    </div>
  );
}
