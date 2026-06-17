"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) { setError(error.message); setLoading(false); }
    else { router.push("/dashboard"); }
  }

  async function handleGoogleLogin() {
    setGoogleLoading(true);
    setError("");
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/dashboard`,
      },
    });
    if (error) { setError(error.message); setGoogleLoading(false); }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm fade-in">
        <div className="text-center mb-8">
          <Link href="/" className="text-[#00d084] text-2xl font-bold tracking-widest glow-green">EDGEBET</Link>
          <p className="text-[#71717a] text-xs mt-2 tracking-widest">SIGN IN TO YOUR ACCOUNT</p>
        </div>

        {/* Google Sign In */}
        <button
          onClick={handleGoogleLogin}
          disabled={googleLoading}
          className="w-full flex items-center justify-center gap-3 bg-[#111] border border-[#333] rounded py-3 text-sm text-[#e4e4e7] hover:border-[#555] hover:bg-[#181818] disabled:opacity-50 transition-all mb-6"
        >
          {googleLoading ? (
            <span className="text-xs tracking-widest text-[#71717a]">REDIRECTING...</span>
          ) : (
            <>
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
                <path d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
                <path d="M3.964 10.707A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.039l3.007-2.332z" fill="#FBBC05"/>
                <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
              </svg>
              <span className="text-sm font-medium">Continue with Google</span>
            </>
          )}
        </button>

        <div className="flex items-center gap-3 mb-6">
          <div className="flex-1 h-px bg-[#1a1a1a]"></div>
          <span className="text-xs text-[#333] tracking-widest">OR</span>
          <div className="flex-1 h-px bg-[#1a1a1a]"></div>
        </div>

        {/* Email/Password */}
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

        <div className="flex justify-between mt-4">
          <Link href="/reset-password" className="text-xs text-[#333] hover:text-[#71717a] transition-colors">Forgot password?</Link>
          <Link href="/register" className="text-xs text-[#333] hover:text-[#71717a] transition-colors">Register with invite</Link>
        </div>
      </div>
    </div>
  );
}
