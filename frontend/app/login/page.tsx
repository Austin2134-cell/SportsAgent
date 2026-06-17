"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { CONFIG_ERROR, getSupabaseConfig } from "@/lib/env";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (!getSupabaseConfig()) {
        setError(CONFIG_ERROR);
        return;
      }
      const supabase = createClient();
      const { error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password,
      });
      if (authError) {
        setError(authError.message);
        return;
      }
      // Don't block login on backend — redirect immediately; /setup and /agent handle routing
      router.push("/setup");
      router.refresh();
    } catch {
      setError("Sign in failed. Please try again.");
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
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs text-[#71717a] tracking-widest mb-1">EMAIL</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084] transition-colors" placeholder="you@example.com" />
          </div>
          <div>
            <label className="block text-xs text-[#71717a] tracking-widest mb-1">PASSWORD</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084] transition-colors" placeholder="••••••••" />
          </div>
          {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>}
          <button type="submit" disabled={loading} className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50 transition-colors">
            {loading ? "SIGNING IN..." : "SIGN IN →"}
          </button>
        </form>
        <p className="text-center text-xs text-[#71717a] mt-4">
          <Link href="/reset-password" className="text-[#71717a] hover:text-[#00d084]">Forgot password?</Link>
        </p>
        <p className="text-center text-xs text-[#71717a] mt-4">Need access? <Link href="/register" className="text-[#00d084] hover:underline">Register with invite code</Link></p>
      </div>
    </div>
  );
}
