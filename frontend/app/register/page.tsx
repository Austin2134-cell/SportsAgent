"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", invite_code: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/auth/register`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Registration failed");
      router.push("/login?registered=1");
    } catch (err: any) { setError(err.message); }
    finally { setLoading(false); }
  }
  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm fade-in">
        <div className="text-center mb-8">
          <Link href="/" className="text-[#00d084] text-2xl font-bold tracking-widest glow-green">EDGEBET</Link>
          <p className="text-[#71717a] text-xs mt-2 tracking-widest">CREATE YOUR ACCOUNT</p>
        </div>
        <form onSubmit={handleRegister} className="space-y-4">
          {[
            { key: "full_name", label: "FULL NAME", type: "text", placeholder: "Austin Noyes" },
            { key: "email", label: "EMAIL", type: "email", placeholder: "you@example.com" },
            { key: "password", label: "PASSWORD", type: "password", placeholder: "Min 8 characters" },
            { key: "invite_code", label: "INVITE CODE", type: "text", placeholder: "EDGEBET2026" },
          ].map((field) => (
            <div key={field.key}>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">{field.label}</label>
              <input type={field.type} value={form[field.key as keyof typeof form]} onChange={(e) => setForm({ ...form, [field.key]: e.target.value })} required className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084] transition-colors" placeholder={field.placeholder} />
            </div>
          ))}
          {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>}
          <button type="submit" disabled={loading} className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50 transition-colors">
            {loading ? "CREATING ACCOUNT..." : "CREATE ACCOUNT →"}
          </button>
        </form>
        <p className="text-center text-xs text-[#71717a] mt-6">Already have an account? <Link href="/login" className="text-[#00d084] hover:underline">Sign in</Link></p>
      </div>
    </div>
  );
}
