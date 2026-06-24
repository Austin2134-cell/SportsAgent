"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { CONFIG_ERROR, getSupabaseConfig } from "@/lib/env";
import { clearAuthHash, parseAuthHash, redirectAfterAuth } from "@/lib/auth-routing";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getSupabaseConfig()) return;

    const supabase = createClient();

    async function establishSession() {
      const tokens = parseAuthHash();
      if (tokens) {
        const { error: sessionError } = await supabase.auth.setSession({
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
        });
        clearAuthHash();
        if (!sessionError) {
          setReady(true);
          return;
        }
      }

      const { data: { session } } = await supabase.auth.getSession();
      if (session) setReady(true);
    }

    establishSession();

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") setReady(true);
    });

    return () => subscription.unsubscribe();
  }, []);

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
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm fade-in">
        <div className="text-center mb-8">
          <Link href="/" className="text-[#00d084] text-2xl font-bold tracking-widest glow-green">AGENTEDGE</Link>
          <p className="text-[#71717a] text-xs mt-2 tracking-widest">SET NEW PASSWORD</p>
        </div>

        {!ready ? (
          <div className="text-center text-xs text-[#71717a]">
            <p>Verifying reset link...</p>
            <p className="mt-4">
              Link expired?{" "}
              <Link href="/login" className="text-[#00d084] hover:underline">Request a new one</Link>
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">NEW PASSWORD</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" placeholder="••••••••" />
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">CONFIRM PASSWORD</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={8} className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" placeholder="••••••••" />
            </div>
            {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>}
            <button type="submit" disabled={loading} className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50">
              {loading ? "UPDATING..." : "UPDATE PASSWORD →"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
