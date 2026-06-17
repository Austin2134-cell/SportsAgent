"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";

interface Episode {
  id: string;
  timestamp: string;
  episode_type: string;
  title: string;
  reasoning: string;
}

interface Hypothesis {
  id: string;
  sport: string;
  game: string;
  market: string;
  player?: string;
  thesis: string;
  status: string;
}

interface Belief {
  id: string;
  category: string;
  belief: string;
  confidence: number;
}

interface AgentStatus {
  provisioned: boolean;
  status: string;
  mode: string;
  bankroll: {
    bankroll_current: number;
    bankroll_starting: number;
    unit_size: number;
    max_daily_units: number;
    units_at_risk: number;
    units_remaining_today: number;
    pnl: number;
    pnl_pct: number;
  };
  last_scan_at?: string;
}

const TYPE_COLORS: Record<string, string> = {
  observation: "text-[#71717a]",
  hypothesis: "text-[#f59e0b]",
  position: "text-[#00d084]",
  pass: "text-[#71717a]",
  mode: "text-[#a78bfa]",
  system: "text-[#00d084]",
  error: "text-[#ff4d4d]",
};

function timeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function AgentPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  const [feed, setFeed] = useState<Episode[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [beliefs, setBeliefs] = useState<Belief[]>([]);
  const [scanning, setScanning] = useState(false);
  const [tab, setTab] = useState<"feed" | "watching" | "beliefs">("feed");

  const load = useCallback(async (t: string) => {
    const [agentRes, feedRes] = await Promise.all([
      api.getAgent(t),
      api.getAgentFeed(t),
    ]);
    if (!agentRes.provisioned) { router.push("/setup"); return; }
    setAgent(agentRes);
    setFeed(feedRes.feed || []);
    setHypotheses(feedRes.hypotheses || []);
    setBeliefs(feedRes.beliefs || []);
  }, [router]);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.push("/login"); return; }
      const t = data.session.access_token;
      setToken(t);
      load(t);
    });
  }, [router, load]);

  async function handleScan() {
    if (!token) return;
    setScanning(true);
    try {
      await api.triggerScan(token);
      await load(token);
    } catch (e) {
      console.error(e);
    } finally {
      setScanning(false);
    }
  }

  const b = agent?.bankroll;
  const pnlColor = (b?.pnl ?? 0) >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]";
  const modeColor = agent?.mode === "defensive" ? "text-[#ff4d4d]" : agent?.mode === "acting" ? "text-[#00d084]" : "text-[#f59e0b]";

  return (
    <div className="min-h-screen bg-[#0a0a0a]">
      <header className="border-b border-[#222] px-4 md:px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-[#00d084] text-sm font-bold tracking-widest glow-green">AGENTEDGE</Link>
          <nav className="hidden sm:flex items-center gap-4 text-[10px] tracking-widest">
            <Link href="/agent" className="text-[#00d084]">AGENT</Link>
            <Link href="/dashboard" className="text-[#71717a] hover:text-[#e4e4e7]">POSITIONS</Link>
            <Link href="/history" className="text-[#71717a] hover:text-[#e4e4e7]">HISTORY</Link>
            <Link href="/preferences" className="text-[#71717a] hover:text-[#e4e4e7]">SETTINGS</Link>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-[#00d084] blink" />
          <span className={`text-[10px] tracking-widest font-bold ${modeColor}`}>{agent?.mode?.toUpperCase() || "..."}</span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6 space-y-6">
        {/* Bankroll bar */}
        {b && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "BANKROLL", value: `$${b.bankroll_current.toLocaleString()}`, sub: `start: $${b.bankroll_starting.toLocaleString()}`, color: "text-[#e4e4e7]" },
              { label: "P&L", value: `${b.pnl >= 0 ? "+" : ""}$${b.pnl.toFixed(0)}`, sub: `${b.pnl_pct >= 0 ? "+" : ""}${b.pnl_pct}%`, color: pnlColor },
              { label: "UNIT SIZE", value: `$${b.unit_size}`, sub: "auto from bankroll", color: "text-[#e4e4e7]" },
              { label: "EXPOSURE TODAY", value: `${b.units_at_risk}/${b.max_daily_units}u`, sub: `${b.units_remaining_today}u remaining`, color: b.units_at_risk >= b.max_daily_units ? "text-[#ff4d4d]" : "text-[#e4e4e7]" },
            ].map(s => (
              <div key={s.label} className="bg-[#111] border border-[#222] rounded p-3">
                <div className="text-[10px] text-[#71717a] tracking-widest">{s.label}</div>
                <div className={`text-lg font-bold ${s.color}`}>{s.value}</div>
                <div className="text-[10px] text-[#71717a]">{s.sub}</div>
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between">
          <div className="text-[10px] text-[#71717a] tracking-widest">
            {agent?.last_scan_at ? `Last scan: ${timeAgo(agent.last_scan_at)}` : "Awaiting first scan"}
          </div>
          <button onClick={handleScan} disabled={scanning}
            className="bg-[#111] border border-[#222] text-[#00d084] text-[10px] font-bold px-4 py-2 rounded tracking-widest hover:border-[#00d084] disabled:opacity-50 transition-colors">
            {scanning ? "SCANNING..." : "RUN SCAN NOW"}
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-[#222]">
          {(["feed", "watching", "beliefs"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`text-[10px] tracking-widest px-4 py-2 border-b-2 transition-colors ${
                tab === t ? "border-[#00d084] text-[#00d084]" : "border-transparent text-[#71717a] hover:text-[#e4e4e7]"
              }`}>
              {t === "feed" ? "LIVE FEED" : t === "watching" ? `WATCHING (${hypotheses.length})` : `MEMORY (${beliefs.length})`}
            </button>
          ))}
        </div>

        {/* Feed */}
        {tab === "feed" && (
          <div className="space-y-2">
            {feed.length === 0 ? (
              <div className="text-center py-12 text-[#71717a] text-xs">
                <p>Your agent is online and scanning.</p>
                <p className="mt-2">Activity will appear here as it analyzes markets.</p>
              </div>
            ) : feed.map(ep => (
              <div key={ep.id} className="bg-[#111] border border-[#222] rounded p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[10px] font-bold tracking-widest ${TYPE_COLORS[ep.episode_type] || "text-[#71717a]"}`}>
                        {ep.episode_type.toUpperCase()}
                      </span>
                    </div>
                    <div className="text-sm text-[#e4e4e7]">{ep.title}</div>
                    {ep.reasoning && <p className="text-xs text-[#71717a] mt-1 leading-relaxed">{ep.reasoning}</p>}
                  </div>
                  <span className="text-[10px] text-[#2a2a2a] flex-shrink-0">{timeAgo(ep.timestamp)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Hypotheses */}
        {tab === "watching" && (
          <div className="space-y-2">
            {hypotheses.length === 0 ? (
              <p className="text-center py-12 text-[#71717a] text-xs">No active hypotheses. Your agent tracks setups here before acting.</p>
            ) : hypotheses.map(h => (
              <div key={h.id} className="bg-[#111] border border-[#f59e0b]/20 rounded p-4">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] bg-[#222] text-[#71717a] px-1.5 py-0.5 rounded">{h.sport}</span>
                  <span className="text-[10px] text-[#f59e0b] tracking-widest">WATCHING</span>
                </div>
                <div className="text-sm text-[#e4e4e7]">{h.game} — {h.market}{h.player ? ` (${h.player})` : ""}</div>
                <p className="text-xs text-[#71717a] mt-1">{h.thesis}</p>
              </div>
            ))}
          </div>
        )}

        {/* Beliefs */}
        {tab === "beliefs" && (
          <div className="space-y-2">
            {beliefs.length === 0 ? (
              <p className="text-center py-12 text-[#71717a] text-xs">Your agent builds memory over time as it learns from outcomes.</p>
            ) : beliefs.map(bel => (
              <div key={bel.id} className="bg-[#111] border border-[#222] rounded p-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-[#71717a] tracking-widest">{bel.category.toUpperCase()}</span>
                  <span className="text-[10px] text-[#00d084]">{Math.round(bel.confidence * 100)}% conf</span>
                </div>
                <p className="text-xs text-[#e4e4e7]">{bel.belief}</p>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
