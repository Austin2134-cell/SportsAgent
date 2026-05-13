"use client";
import Link from "next/link";
export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col">
      <header className="border-b border-[#222] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[#00d084] text-xl font-bold tracking-widest glow-green">EDGEBET</span>
          <span className="text-[#2a2a2a] text-xs">|</span>
          <span className="text-[#71717a] text-xs tracking-widest">AI SPORTS INTELLIGENCE</span>
        </div>
        <Link href="/login" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">SIGN IN &rarr;</Link>
      </header>
      <main className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="fade-in max-w-2xl">
          <div className="flex items-center justify-center gap-2 mb-8">
            <span className="w-2 h-2 rounded-full bg-[#00d084] blink" />
            <span className="text-[#00d084] text-xs tracking-widest">SYSTEM ACTIVE</span>
          </div>
          <h1 className="text-4xl md:text-6xl font-bold text-[#e4e4e7] mb-4 tracking-tight">
            Your AI<br /><span className="text-[#00d084] glow-green">Betting Analyst</span>
          </h1>
          <p className="text-[#71717a] text-sm md:text-base max-w-lg mx-auto mb-10 leading-relaxed">
            Every morning at 9:30 AM, EdgeBet analyzes live odds across NBA, MLB, NHL, and NFL — then delivers a personalized daily card built around your preferences.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10 text-left">
            {[
              { icon: "◈", label: "PLAYER PROPS", sub: "K lines, pts, rebounds" },
              { icon: "◉", label: "STRAIGHT BETS", sub: "ML, spread, totals" },
              { icon: "◆", label: "PARLAY BUILDER", sub: "Correlated legs" },
              { icon: "▲", label: "LIVE RECORD", sub: "W-L, units, ROI" },
            ].map((f) => (
              <div key={f.label} className="bg-[#111] border border-[#222] rounded p-3">
                <span className="text-[#00d084] text-lg">{f.icon}</span>
                <div className="text-[10px] font-bold tracking-widest text-[#e4e4e7] mt-1">{f.label}</div>
                <div className="text-[10px] text-[#71717a] mt-0.5">{f.sub}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/register" className="bg-[#00d084] text-black text-xs font-bold px-8 py-3 rounded tracking-widest hover:bg-[#00b872] transition-colors w-full sm:w-auto">REQUEST ACCESS</Link>
            <Link href="/login" className="border border-[#222] text-[#71717a] text-xs px-8 py-3 rounded tracking-widest hover:border-[#00d084] hover:text-[#00d084] transition-colors w-full sm:w-auto">SIGN IN</Link>
          </div>
          <p className="text-[#2a2a2a] text-xs mt-6 tracking-wider">INVITE ONLY &mdash; BETA ACCESS</p>
        </div>
      </main>
      <footer className="border-t border-[#222] px-6 py-4 flex items-center justify-between">
        <span className="text-[#2a2a2a] text-xs tracking-wider">&copy; 2026 EDGEBET</span>
        <span className="text-[#2a2a2a] text-xs">FOR ENTERTAINMENT PURPOSES</span>
      </footer>
    </div>
  );
}
