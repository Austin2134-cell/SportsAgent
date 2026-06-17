"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";
import { CONFIG_ERROR, getSupabaseConfig } from "@/lib/env";

const BET_TYPES = [
  { key: "player_props", label: "PLAYER PROPS" },
  { key: "straight", label: "STRAIGHT BETS" },
  { key: "parlays", label: "PARLAYS" },
];
const RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"];

const DEFAULT_SPORTS = [
  { id: "MLB", label: "MLB", season_active: true },
  { id: "WC", label: "World Cup Soccer", season_active: true },
  { id: "NBA", label: "NBA", season_active: false },
  { id: "NHL", label: "NHL", season_active: false },
  { id: "NFL", label: "NFL", season_active: false },
];

export default function SetupPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  const [sports, setSports] = useState(DEFAULT_SPORTS);
  const [configError, setConfigError] = useState("");
  const [form, setForm] = useState({
    bankroll_starting: 1000,
    unit_pct: 0.02,
    max_daily_pct: 0.06,
    sports: ["MLB", "WC"] as string[],
    bet_types: ["player_props", "straight"] as string[],
    risk_level: "MEDIUM",
    max_plays: 5,
    include_parlays: false,
    notification_email: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getSupabaseConfig()) {
      setConfigError(CONFIG_ERROR);
      return;
    }
    try {
      const supabase = createClient();
      supabase.auth.getSession().then(({ data }) => {
        if (!data.session) { router.push("/login"); return; }
        setToken(data.session.access_token);
        api.getAgent(data.session.access_token).then((res) => {
          if (res.provisioned) router.push("/agent");
        }).catch(() => { /* backend unreachable — stay on setup */ });
      }).catch(() => setConfigError(CONFIG_ERROR));
    } catch {
      setConfigError(CONFIG_ERROR);
      return;
    }
    api.getSports()
      .then((res) => setSports(res.sports?.length ? res.sports : DEFAULT_SPORTS))
      .catch(() => setSports(DEFAULT_SPORTS));
  }, [router]);

  const unitSize = Math.round(form.bankroll_starting * form.unit_pct);
  const maxUnits = Math.max(1, Math.floor((form.bankroll_starting * form.max_daily_pct) / unitSize));

  function toggleSport(id: string) {
    setForm(f => ({
      ...f,
      sports: f.sports.includes(id) ? f.sports.filter(s => s !== id) : [...f.sports, id],
    }));
  }

  function toggleBetType(key: string) {
    setForm(f => ({
      ...f,
      bet_types: f.bet_types.includes(key) ? f.bet_types.filter(b => b !== key) : [...f.bet_types, key],
    }));
  }

  async function handleLaunch() {
    if (!token) return;
    if (form.sports.length === 0) { setError("Select at least one sport"); return; }
    setLoading(true);
    setError("");
    try {
      await api.setupAgent(token, form);
      router.push("/agent");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Setup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg fade-in">
        <div className="text-center mb-8">
          <Link href="/" className="text-[#00d084] text-2xl font-bold tracking-widest glow-green">AGENTEDGE</Link>
          <p className="text-[#71717a] text-xs mt-2 tracking-widest">CONFIGURE YOUR AGENT — STEP {step} OF 3</p>
        </div>

        {configError && (
          <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-4 py-3 text-xs text-[#ff4d4d] mb-6 leading-relaxed">
            {configError}
          </div>
        )}

        {!configError && step === 1 && (
          <div className="space-y-5">
            <h2 className="text-sm font-bold text-[#e4e4e7] tracking-widest">BANKROLL</h2>
            <p className="text-xs text-[#71717a]">Your agent auto-calculates unit size from your bankroll. No manual unit sizing.</p>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">STARTING BANKROLL ($)</label>
              <input type="number" min={100} step={100} value={form.bankroll_starting}
                onChange={e => setForm({ ...form, bankroll_starting: Number(e.target.value) })}
                className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" />
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">UNIT SIZE — {Math.round(form.unit_pct * 100)}% OF BANKROLL</label>
              <input type="range" min={0.5} max={5} step={0.5} value={form.unit_pct * 100}
                onChange={e => setForm({ ...form, unit_pct: Number(e.target.value) / 100 })}
                className="w-full accent-[#00d084]" />
              <div className="flex justify-between text-[10px] text-[#71717a] mt-1">
                <span>Conservative (0.5%)</span>
                <span className="text-[#00d084] font-bold">1 unit = ${unitSize}</span>
                <span>Aggressive (5%)</span>
              </div>
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">MAX DAILY EXPOSURE — {Math.round(form.max_daily_pct * 100)}% OF BANKROLL</label>
              <input type="range" min={3} max={15} step={1} value={form.max_daily_pct * 100}
                onChange={e => setForm({ ...form, max_daily_pct: Number(e.target.value) / 100 })}
                className="w-full accent-[#00d084]" />
              <p className="text-[10px] text-[#71717a] mt-1">Max ~{maxUnits} units per day (${Math.round(form.bankroll_starting * form.max_daily_pct)} exposure)</p>
            </div>
            <button onClick={() => setStep(2)} className="w-full bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] transition-colors">
              NEXT: SPORTS & MARKETS →
            </button>
          </div>
        )}

        {!configError && step === 2 && (
          <div className="space-y-5">
            <h2 className="text-sm font-bold text-[#e4e4e7] tracking-widest">SPORTS & MARKETS</h2>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-2">SPORTS TO TRACK</label>
              <div className="grid grid-cols-2 gap-2">
                {sports.map(s => (
                  <button key={s.id} type="button" onClick={() => toggleSport(s.id)}
                    className={`text-xs py-2 px-3 rounded border tracking-wider transition-colors ${
                      form.sports.includes(s.id)
                        ? "border-[#00d084] text-[#00d084] bg-[#00d084]/10"
                        : "border-[#222] text-[#71717a] hover:border-[#333]"
                    }`}>
                    {s.label}{!s.season_active && <span className="text-[#2a2a2a] ml-1">(off)</span>}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-[#71717a] mt-2">Off-season sports stay in your profile — your agent activates them when games return.</p>
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-2">BET TYPES</label>
              <div className="flex flex-wrap gap-2">
                {BET_TYPES.map(bt => (
                  <button key={bt.key} type="button" onClick={() => toggleBetType(bt.key)}
                    className={`text-xs py-2 px-3 rounded border tracking-wider transition-colors ${
                      form.bet_types.includes(bt.key)
                        ? "border-[#00d084] text-[#00d084] bg-[#00d084]/10"
                        : "border-[#222] text-[#71717a]"
                    }`}>{bt.label}</button>
                ))}
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={() => setStep(1)} className="flex-1 border border-[#222] text-[#71717a] text-xs py-3 rounded tracking-widest">← BACK</button>
              <button onClick={() => setStep(3)} className="flex-1 bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest">NEXT: RISK →</button>
            </div>
          </div>
        )}

        {!configError && step === 3 && (
          <div className="space-y-5">
            <h2 className="text-sm font-bold text-[#e4e4e7] tracking-widest">RISK & LAUNCH</h2>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-2">RISK PROFILE</label>
              <div className="flex gap-2">
                {RISK_LEVELS.map(r => (
                  <button key={r} type="button" onClick={() => setForm({ ...form, risk_level: r })}
                    className={`flex-1 text-xs py-2 rounded border tracking-wider ${
                      form.risk_level === r ? "border-[#00d084] text-[#00d084] bg-[#00d084]/10" : "border-[#222] text-[#71717a]"
                    }`}>{r}</button>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">MAX PLAYS PER DAY</label>
              <input type="number" min={1} max={10} value={form.max_plays}
                onChange={e => setForm({ ...form, max_plays: Number(e.target.value) })}
                className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" />
            </div>
            <div>
              <label className="block text-xs text-[#71717a] tracking-widest mb-1">NOTIFICATION EMAIL (optional)</label>
              <input type="email" value={form.notification_email}
                onChange={e => setForm({ ...form, notification_email: e.target.value })}
                placeholder="you@example.com"
                className="w-full bg-[#111] border border-[#222] rounded px-3 py-2.5 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084]" />
            </div>
            <div className="bg-[#111] border border-[#222] rounded p-4 text-xs text-[#71717a] space-y-1">
              <p className="text-[#e4e4e7] font-bold tracking-widest mb-2">AGENT SUMMARY</p>
              <p>Bankroll: ${form.bankroll_starting.toLocaleString()}</p>
              <p>Unit size: ${unitSize} ({Math.round(form.unit_pct * 100)}% auto-calculated)</p>
              <p>Max daily: {maxUnits} units</p>
              <p>Sports: {form.sports.join(", ")}</p>
              <p>Risk: {form.risk_level}</p>
            </div>
            {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>}
            <div className="flex gap-3">
              <button onClick={() => setStep(2)} className="flex-1 border border-[#222] text-[#71717a] text-xs py-3 rounded tracking-widest">← BACK</button>
              <button onClick={handleLaunch} disabled={loading}
                className="flex-1 bg-[#00d084] text-black text-xs font-bold py-3 rounded tracking-widest hover:bg-[#00b872] disabled:opacity-50">
                {loading ? "LAUNCHING..." : "LAUNCH AGENT →"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
