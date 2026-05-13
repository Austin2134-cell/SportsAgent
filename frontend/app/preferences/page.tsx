"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";

const SPORTS = ["NBA", "MLB", "NHL", "NFL", "NCAAB", "NCAAF"];
const BET_TYPES = [
  { key: "player_props", label: "PLAYER PROPS" },
  { key: "straight", label: "STRAIGHT BETS" },
  { key: "parlays", label: "PARLAYS" },
  { key: "live", label: "LIVE BETTING" },
];
const RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"];

export default function PreferencesPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [prefs, setPrefs] = useState({
    sports: ["MLB", "NBA", "NHL"],
    bet_types: ["player_props", "straight"],
    risk_level: "MEDIUM",
    max_plays: 5,
    unit_size: 50,
    include_parlays: false,
    notification_email: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.push("/login"); return; }
      const t = data.session.access_token;
      setToken(t);
      api.getPreferences(t).then((res) => {
        if (res.preferences) {
          setPrefs({
            sports: res.preferences.sports || ["MLB", "NBA", "NHL"],
            bet_types: res.preferences.bet_types || ["player_props", "straight"],
            risk_level: res.preferences.risk_level || "MEDIUM",
            max_plays: res.preferences.max_plays || 5,
            unit_size: res.preferences.unit_size || 50,
            include_parlays: res.preferences.include_parlays || false,
            notification_email: res.preferences.notification_email || "",
          });
        }
        setLoading(false);
      }).catch(() => setLoading(false));
    });
  }, [router]);

  function toggleSport(sport: string) {
    setPrefs(p => ({
      ...p,
      sports: p.sports.includes(sport)
        ? p.sports.filter(s => s !== sport)
        : [...p.sports, sport],
    }));
  }

  function toggleBetType(key: string) {
    setPrefs(p => ({
      ...p,
      bet_types: p.bet_types.includes(key)
        ? p.bet_types.filter(b => b !== key)
        : [...p.bet_types, key],
    }));
  }

  async function handleSave() {
    if (!token) return;
    setSaving(true);
    setError("");
    try {
      await api.updatePreferences(token, prefs);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <span className="text-[#71717a] text-xs tracking-widest">LOADING...</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a]">
      <header className="border-b border-[#222] px-4 md:px-6 py-3 flex items-center justify-between sticky top-0 bg-[#0a0a0a] z-10">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-[#00d084] font-bold tracking-widest glow-green">EDGEBET</Link>
          <span className="text-[#2a2a2a] text-xs hidden sm:block">|</span>
          <span className="text-[#71717a] text-xs tracking-widest hidden sm:block">PREFERENCES</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">CARD</Link>
          <Link href="/history" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">HISTORY</Link>
        </div>
      </header>

      <div className="max-w-lg mx-auto px-4 py-6 space-y-6 fade-in">
        {/* Sports */}
        <div className="bg-[#111] border border-[#222] rounded p-4">
          <div className="text-[10px] text-[#71717a] tracking-widest mb-3">SPORTS</div>
          <div className="grid grid-cols-3 gap-2">
            {SPORTS.map((sport) => (
              <button
                key={sport}
                onClick={() => toggleSport(sport)}
                className={`text-xs py-2 px-3 rounded border transition-colors tracking-wider ${
                  prefs.sports.includes(sport)
                    ? "bg-[#00d084]/10 border-[#00d084]/30 text-[#00d084]"
                    : "bg-transparent border-[#222] text-[#71717a] hover:border-[#444]"
                }`}
              >
                {sport}
              </button>
            ))}
          </div>
        </div>

        {/* Bet Types */}
        <div className="bg-[#111] border border-[#222] rounded p-4">
          <div className="text-[10px] text-[#71717a] tracking-widest mb-3">BET TYPES</div>
          <div className="grid grid-cols-2 gap-2">
            {BET_TYPES.map((bt) => (
              <button
                key={bt.key}
                onClick={() => toggleBetType(bt.key)}
                className={`text-xs py-2 px-3 rounded border transition-colors tracking-wider ${
                  prefs.bet_types.includes(bt.key)
                    ? "bg-[#00d084]/10 border-[#00d084]/30 text-[#00d084]"
                    : "bg-transparent border-[#222] text-[#71717a] hover:border-[#444]"
                }`}
              >
                {bt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Risk Level */}
        <div className="bg-[#111] border border-[#222] rounded p-4">
          <div className="text-[10px] text-[#71717a] tracking-widest mb-3">RISK LEVEL</div>
          <div className="grid grid-cols-3 gap-2">
            {RISK_LEVELS.map((level) => (
              <button
                key={level}
                onClick={() => setPrefs(p => ({ ...p, risk_level: level }))}
                className={`text-xs py-2 px-3 rounded border transition-colors tracking-wider ${
                  prefs.risk_level === level
                    ? level === "HIGH"
                      ? "bg-[#ff4d4d]/10 border-[#ff4d4d]/30 text-[#ff4d4d]"
                      : level === "MEDIUM"
                      ? "bg-[#f59e0b]/10 border-[#f59e0b]/30 text-[#f59e0b]"
                      : "bg-[#00d084]/10 border-[#00d084]/30 text-[#00d084]"
                    : "bg-transparent border-[#222] text-[#71717a] hover:border-[#444]"
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>

        {/* Max Plays & Unit Size */}
        <div className="bg-[#111] border border-[#222] rounded p-4 space-y-4">
          <div>
            <label className="block text-[10px] text-[#71717a] tracking-widest mb-2">
              MAX PLAYS PER DAY: <span className="text-[#e4e4e7]">{prefs.max_plays}</span>
            </label>
            <input
              type="range" min={1} max={15} value={prefs.max_plays}
              onChange={(e) => setPrefs(p => ({ ...p, max_plays: Number(e.target.value) }))}
              className="w-full accent-[#00d084]"
            />
            <div className="flex justify-between text-[10px] text-[#2a2a2a] mt-1">
              <span>1</span><span>15</span>
            </div>
          </div>
          <div>
            <label className="block text-[10px] text-[#71717a] tracking-widest mb-2">UNIT SIZE ($)</label>
            <input
              type="number" min={1} value={prefs.unit_size}
              onChange={(e) => setPrefs(p => ({ ...p, unit_size: Number(e.target.value) }))}
              className="w-full bg-[#0a0a0a] border border-[#222] rounded px-3 py-2 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084] transition-colors"
            />
          </div>
        </div>

        {/* Include Parlays */}
        <div className="bg-[#111] border border-[#222] rounded p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-[#e4e4e7] tracking-wider">INCLUDE PARLAYS</div>
              <div className="text-[10px] text-[#71717a] mt-0.5">Add correlated parlay suggestions to your card</div>
            </div>
            <button
              onClick={() => setPrefs(p => ({ ...p, include_parlays: !p.include_parlays }))}
              className={`relative w-10 h-5 rounded-full transition-colors ${prefs.include_parlays ? "bg-[#00d084]" : "bg-[#222]"}`}
            >
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${prefs.include_parlays ? "translate-x-5" : "translate-x-0.5"}`} />
            </button>
          </div>
        </div>

        {/* Notification Email */}
        <div className="bg-[#111] border border-[#222] rounded p-4">
          <label className="block text-[10px] text-[#71717a] tracking-widest mb-2">NOTIFICATION EMAIL (OPTIONAL)</label>
          <input
            type="email" value={prefs.notification_email}
            onChange={(e) => setPrefs(p => ({ ...p, notification_email: e.target.value }))}
            placeholder="Receive daily card by email"
            className="w-full bg-[#0a0a0a] border border-[#222] rounded px-3 py-2 text-sm text-[#e4e4e7] focus:outline-none focus:border-[#00d084] transition-colors"
          />
        </div>

        {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-3 py-2 text-xs text-[#ff4d4d]">{error}</div>}

        <button
          onClick={handleSave}
          disabled={saving}
          className={`w-full text-xs font-bold py-3 rounded tracking-widest transition-colors ${
            saved
              ? "bg-[#00d084]/20 border border-[#00d084]/30 text-[#00d084]"
              : "bg-[#00d084] text-black hover:bg-[#00b872] disabled:opacity-50"
          }`}
        >
          {saving ? "SAVING..." : saved ? "SAVED ✓" : "SAVE PREFERENCES"}
        </button>
      </div>
    </div>
  );
}
