"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";

interface Bet {
  id: string;
  date: string;
  sport: string;
  game: string;
  bet: string;
  odds: number;
  units: number;
  result: string;
  units_result: number;
  confidence: string;
  post_slate_tag: string;
  notes: string;
}

function resultColor(result: string) {
  if (result === "W") return "text-[#00d084]";
  if (result === "L") return "text-[#ff4d4d]";
  if (result === "P") return "text-[#71717a]";
  return "text-[#f59e0b]";
}

function resultBg(result: string) {
  if (result === "W") return "bg-[#00d084]/10 border-[#00d084]/20";
  if (result === "L") return "bg-[#ff4d4d]/10 border-[#ff4d4d]/20";
  if (result === "P") return "bg-[#222]/50 border-[#222]";
  return "bg-[#f59e0b]/10 border-[#f59e0b]/20";
}

export default function HistoryPage() {
  const router = useRouter();
  const [bets, setBets] = useState<Bet[]>([]);
  const [record, setRecord] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.push("/login"); return; }
      const t = data.session.access_token;
      Promise.all([
        api.getBets(t, 200),
        api.getRecord(t),
      ]).then(([betsRes, recordRes]) => {
        setBets(betsRes.bets || []);
        setRecord(recordRes);
        setLoading(false);
      }).catch((e) => {
        setError(e.message);
        setLoading(false);
      });
    });
  }, [router]);

  // Group bets by date
  const grouped: Record<string, Bet[]> = {};
  for (const bet of bets) {
    if (!grouped[bet.date]) grouped[bet.date] = [];
    grouped[bet.date].push(bet);
  }
  const dates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  return (
    <div className="min-h-screen bg-[#0a0a0a]">
      <header className="border-b border-[#222] px-4 md:px-6 py-3 flex items-center justify-between sticky top-0 bg-[#0a0a0a] z-10">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-[#00d084] font-bold tracking-widest glow-green">EDGEBET</Link>
          <span className="text-[#2a2a2a] text-xs hidden sm:block">|</span>
          <span className="text-[#71717a] text-xs tracking-widest hidden sm:block">BET HISTORY</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">CARD</Link>
          <Link href="/preferences" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">PREFS</Link>
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-4 py-6">
        {/* Record Summary */}
        {record && (
          <div className="bg-[#111] border border-[#222] rounded p-4 mb-6">
            <div className="text-[10px] text-[#71717a] tracking-widest mb-3">ALL-TIME RECORD</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xl font-bold text-[#e4e4e7]">{record.record_str}</div>
                <div className="text-[10px] text-[#71717a]">W-L-P</div>
              </div>
              <div>
                <div className={`text-xl font-bold ${record.net_units >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]"}`}>{record.units_str}</div>
                <div className="text-[10px] text-[#71717a]">NET UNITS</div>
              </div>
              <div>
                <div className={`text-xl font-bold ${record.roi_pct >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]"}`}>{record.roi_pct > 0 ? "+" : ""}{record.roi_pct}%</div>
                <div className="text-[10px] text-[#71717a]">ROI</div>
              </div>
              <div>
                <div className="text-xl font-bold text-[#e4e4e7]">{record.total}</div>
                <div className="text-[10px] text-[#71717a]">TOTAL GRADED</div>
              </div>
            </div>
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-16">
            <span className="text-[#71717a] text-xs tracking-widest">LOADING...</span>
          </div>
        )}

        {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-4 py-3 text-xs text-[#ff4d4d] mb-4">{error}</div>}

        {!loading && bets.length === 0 && (
          <div className="text-center py-16">
            <div className="text-[#00d084] text-3xl mb-4">◈</div>
            <div className="text-sm text-[#e4e4e7] mb-2">No bet history yet</div>
            <div className="text-xs text-[#71717a]">Your graded bets will appear here</div>
          </div>
        )}

        {/* Bets grouped by date */}
        <div className="space-y-6">
          {dates.map((date) => {
            const dayBets = grouped[date];
            const dayWins = dayBets.filter(b => b.result === "W").length;
            const dayLosses = dayBets.filter(b => b.result === "L").length;
            const dayNet = dayBets.reduce((sum, b) => sum + (b.result !== "pending" ? Number(b.units_result) : 0), 0);
            const pending = dayBets.filter(b => b.result === "pending").length;

            return (
              <div key={date}>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[10px] text-[#71717a] tracking-widest">
                    {new Date(date + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).toUpperCase()}
                  </div>
                  <div className="flex items-center gap-3 text-[10px]">
                    {pending > 0 && <span className="text-[#f59e0b]">{pending} PENDING</span>}
                    {(dayWins + dayLosses) > 0 && (
                      <>
                        <span className="text-[#71717a]">{dayWins}-{dayLosses}</span>
                        <span className={dayNet >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]"}>
                          {dayNet >= 0 ? "+" : ""}{dayNet.toFixed(1)}u
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <div className="space-y-1.5">
                  {dayBets.map((bet) => (
                    <div key={bet.id} className={`border rounded p-3 ${resultBg(bet.result)}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className="text-[10px] bg-[#222] text-[#71717a] px-1.5 py-0.5 rounded tracking-wider">{bet.sport}</span>
                            {bet.post_slate_tag && (
                              <span className="text-[10px] text-[#71717a] italic">{bet.post_slate_tag}</span>
                            )}
                          </div>
                          <div className="text-xs text-[#e4e4e7]">{bet.bet}</div>
                          <div className="text-[11px] text-[#71717a] mt-0.5">{bet.game}</div>
                        </div>
                        <div className="text-right flex-shrink-0">
                          <div className={`text-sm font-bold ${resultColor(bet.result)}`}>{bet.result.toUpperCase()}</div>
                          {bet.result !== "pending" && bet.result !== "P" && (
                            <div className={`text-[10px] ${Number(bet.units_result) >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]"}`}>
                              {Number(bet.units_result) >= 0 ? "+" : ""}{Number(bet.units_result).toFixed(2)}u
                            </div>
                          )}
                          <div className="text-[10px] text-[#71717a]">
                            {bet.odds > 0 ? "+" : ""}{bet.odds} · {bet.units}u
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
