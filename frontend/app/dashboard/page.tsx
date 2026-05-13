"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";

interface Play {
  bet: string;
  sport: string;
  game: string;
  market: string;
  odds: number;
  book: string;
  units: number;
  confidence: string;
  why: string;
  line_movement?: string;
  sharp_action?: string;
  injury_news?: string;
}

interface Card {
  id: string;
  date: string;
  slate_grade: string;
  slate_note: string;
  plays: Play[];
  leans: any[];
  quick_reads: any[];
  pass_notes: any[];
}

function StatBox({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-[#111] border border-[#222] rounded p-3">
      <div className="text-[10px] text-[#71717a] tracking-widest mb-1">{label}</div>
      <div className={`text-lg font-bold ${color || "text-[#e4e4e7]"}`}>{value}</div>
      {sub && <div className="text-[10px] text-[#71717a] mt-0.5">{sub}</div>}
    </div>
  );
}

function PlayCard({ play, index }: { play: Play; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const oddsStr = play.odds > 0 ? `+${play.odds}` : `${play.odds}`;
  const confColor =
    play.confidence === "HIGH" ? "text-[#00d084]" :
    play.confidence === "MEDIUM" ? "text-[#f59e0b]" :
    "text-[#71717a]";

  return (
    <div className="bg-[#111] border border-[#222] rounded overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left p-4 hover:bg-[#161616] transition-colors"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] bg-[#222] text-[#71717a] px-1.5 py-0.5 rounded tracking-wider">{play.sport}</span>
              <span className={`text-[10px] font-bold tracking-wider ${confColor}`}>{play.confidence}</span>
            </div>
            <div className="text-sm font-medium text-[#e4e4e7] leading-snug">{play.bet}</div>
            <div className="text-[11px] text-[#71717a] mt-1">{play.game}</div>
          </div>
          <div className="text-right flex-shrink-0">
            <div className="text-sm font-bold text-[#00d084]">{oddsStr}</div>
            <div className="text-[10px] text-[#71717a]">{play.units}u</div>
            <div className="text-[10px] text-[#71717a] mt-1">{expanded ? "▲" : "▼"}</div>
          </div>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-[#222] px-4 pb-4 pt-3 space-y-2">
          <div>
            <span className="text-[10px] text-[#71717a] tracking-widest">ANALYSIS</span>
            <p className="text-xs text-[#e4e4e7] mt-1 leading-relaxed">{play.why}</p>
          </div>
          {play.line_movement && (
            <div>
              <span className="text-[10px] text-[#71717a] tracking-widest">LINE MOVEMENT</span>
              <p className="text-xs text-[#e4e4e7] mt-1">{play.line_movement}</p>
            </div>
          )}
          {play.sharp_action && (
            <div>
              <span className="text-[10px] text-[#71717a] tracking-widest">SHARP ACTION</span>
              <p className="text-xs text-[#e4e4e7] mt-1">{play.sharp_action}</p>
            </div>
          )}
          {play.injury_news && (
            <div>
              <span className="text-[10px] text-[#71717a] tracking-widest">INJURY NEWS</span>
              <p className="text-xs text-[#e4e4e7] mt-1">{play.injury_news}</p>
            </div>
          )}
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] text-[#71717a]">BOOK: {play.book}</span>
            <span className="text-[#222]">|</span>
            <span className="text-[10px] text-[#71717a]">MARKET: {play.market}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="flex flex-col items-center justify-center py-20">
      <div className="flex items-center gap-2 mb-4">
        <span className="w-2 h-2 rounded-full bg-[#00d084] blink" />
        <span className="text-[#00d084] text-xs tracking-widest">LOADING CARD...</span>
      </div>
      <div className="text-[#71717a] text-xs">Fetching today&apos;s analysis</div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [card, setCard] = useState<Card | null>(null);
  const [record, setRecord] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.push("/login"); return; }
      const t = data.session.access_token;
      setToken(t);
      Promise.all([
        api.getTodayCard(t),
        api.getRecord(t),
      ]).then(([cardRes, recordRes]) => {
        setCard(cardRes.card || null);
        setRecord(recordRes);
        setLoading(false);
      }).catch((e) => {
        setError(e.message);
        setLoading(false);
      });
    });
  }, [router]);

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  }

  const gradeColor =
    card?.slate_grade === "A" ? "text-[#00d084]" :
    card?.slate_grade === "B" ? "text-[#3b82f6]" :
    card?.slate_grade === "C" ? "text-[#f59e0b]" :
    "text-[#ff4d4d]";

  return (
    <div className="min-h-screen bg-[#0a0a0a]">
      {/* Header */}
      <header className="border-b border-[#222] px-4 md:px-6 py-3 flex items-center justify-between sticky top-0 bg-[#0a0a0a] z-10">
        <div className="flex items-center gap-3">
          <span className="text-[#00d084] font-bold tracking-widest glow-green">EDGEBET</span>
          <span className="text-[#2a2a2a] text-xs hidden sm:block">|</span>
          <span className="text-[#71717a] text-xs tracking-widest hidden sm:block">DAILY CARD</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/history" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">HISTORY</Link>
          <Link href="/preferences" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">PREFS</Link>
          <button onClick={handleSignOut} className="text-xs text-[#71717a] hover:text-[#ff4d4d] transition-colors tracking-wider">OUT</button>
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-4 py-6">
        {/* Record Strip */}
        {record && (
          <div className="grid grid-cols-4 gap-2 mb-6">
            <StatBox label="RECORD" value={record.record_str} />
            <StatBox label="NET UNITS" value={record.units_str} color={record.net_units >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]"} />
            <StatBox label="ROI" value={`${record.roi_pct > 0 ? "+" : ""}${record.roi_pct}%`} color={record.roi_pct >= 0 ? "text-[#00d084]" : "text-[#ff4d4d]"} />
            <StatBox label="PLAYS" value={`${record.total}`} sub="graded" />
          </div>
        )}

        {loading && <LoadingScreen />}
        {error && <div className="bg-[#ff4d4d]/10 border border-[#ff4d4d]/30 rounded px-4 py-3 text-xs text-[#ff4d4d]">{error}</div>}

        {!loading && !card && (
          <div className="text-center py-16">
            <div className="text-[#00d084] text-3xl mb-4">◈</div>
            <div className="text-sm text-[#e4e4e7] mb-2">No card yet today</div>
            <div className="text-xs text-[#71717a]">Check back at 9:30 AM MT for today&apos;s analysis</div>
          </div>
        )}

        {card && (
          <div className="space-y-6 fade-in">
            {/* Slate Header */}
            <div className="bg-[#111] border border-[#222] rounded p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-[10px] text-[#71717a] tracking-widest">TODAY&apos;S SLATE</div>
                  <div className="text-xs text-[#71717a] mt-0.5">{new Date(card.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}</div>
                </div>
                {card.slate_grade && (
                  <div className="text-right">
                    <div className="text-[10px] text-[#71717a] tracking-widest">GRADE</div>
                    <div className={`text-3xl font-bold ${gradeColor}`}>{card.slate_grade}</div>
                  </div>
                )}
              </div>
              {card.slate_note && <p className="text-xs text-[#71717a] leading-relaxed border-t border-[#222] pt-2 mt-2">{card.slate_note}</p>}
            </div>

            {/* Main Plays */}
            {card.plays && card.plays.length > 0 && (
              <div>
                <div className="text-[10px] text-[#71717a] tracking-widest mb-3 flex items-center gap-2">
                  <span className="text-[#00d084]">◈</span> PLAYS ({card.plays.length})
                </div>
                <div className="space-y-2">
                  {card.plays.map((play, i) => (
                    <PlayCard key={i} play={play} index={i} />
                  ))}
                </div>
              </div>
            )}

            {/* Leans */}
            {card.leans && card.leans.length > 0 && (
              <div>
                <div className="text-[10px] text-[#71717a] tracking-widest mb-3 flex items-center gap-2">
                  <span className="text-[#3b82f6]">◉</span> LEANS ({card.leans.length})
                </div>
                <div className="space-y-2">
                  {card.leans.map((lean: any, i: number) => (
                    <div key={i} className="bg-[#111] border border-[#222] rounded p-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-[10px] bg-[#222] text-[#71717a] px-1.5 py-0.5 rounded tracking-wider mr-2">{lean.sport}</span>
                          <span className="text-xs text-[#e4e4e7]">{lean.bet}</span>
                        </div>
                        <span className="text-xs text-[#3b82f6] font-bold">{lean.odds > 0 ? "+" : ""}{lean.odds}</span>
                      </div>
                      {lean.note && <p className="text-[11px] text-[#71717a] mt-2 leading-relaxed">{lean.note}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Quick Reads */}
            {card.quick_reads && card.quick_reads.length > 0 && (
              <div>
                <div className="text-[10px] text-[#71717a] tracking-widest mb-3 flex items-center gap-2">
                  <span className="text-[#f59e0b]">▲</span> QUICK READS
                </div>
                <div className="bg-[#111] border border-[#222] rounded divide-y divide-[#222]">
                  {card.quick_reads.map((qr: any, i: number) => (
                    <div key={i} className="px-4 py-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] bg-[#222] text-[#71717a] px-1.5 py-0.5 rounded tracking-wider">{qr.sport}</span>
                        <span className="text-xs font-medium text-[#e4e4e7]">{qr.game || qr.bet}</span>
                      </div>
                      {qr.note && <p className="text-[11px] text-[#71717a] leading-relaxed">{qr.note}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pass Notes */}
            {card.pass_notes && card.pass_notes.length > 0 && (
              <div>
                <div className="text-[10px] text-[#71717a] tracking-widest mb-3 flex items-center gap-2">
                  <span className="text-[#2a2a2a]">◆</span> PASSES / FADES
                </div>
                <div className="bg-[#111] border border-[#222] rounded divide-y divide-[#222]">
                  {card.pass_notes.map((pn: any, i: number) => (
                    <div key={i} className="px-4 py-3">
                      <div className="flex items-center gap-2 mb-1">
                        {pn.sport && <span className="text-[10px] bg-[#222] text-[#71717a] px-1.5 py-0.5 rounded tracking-wider">{pn.sport}</span>}
                        <span className="text-xs font-medium text-[#71717a]">{pn.bet || pn.game}</span>
                      </div>
                      {pn.reason && <p className="text-[11px] text-[#71717a] leading-relaxed">{pn.reason}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
