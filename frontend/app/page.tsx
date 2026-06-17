"use client";
import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col">
      <header className="border-b border-[#222] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[#00d084] text-xl font-bold tracking-widest glow-green">AGENTEDGE</span>
          <span className="text-[#2a2a2a] text-xs">|</span>
          <span className="text-[#71717a] text-xs tracking-widest">BY EDGESPORTSMEDIA</span>
        </div>
        <Link href="/login" className="text-xs text-[#71717a] hover:text-[#00d084] transition-colors tracking-wider">SIGN IN &rarr;</Link>
      </header>
      <main className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="fade-in max-w-2xl">
          <div className="flex items-center justify-center gap-2 mb-8">
            <span className="w-2 h-2 rounded-full bg-[#00d084] blink" />
            <span className="text-[#00d084] text-xs tracking-widest">AGENT INFRASTRUCTURE ONLINE</span>
          </div>
          <h1 className="text-4xl md:text-6xl font-bold text-[#e4e4e7] mb-4 tracking-tight">
            Your Personal<br /><span className="text-[#00d084] glow-green">Sports Betting AI</span>
          </h1>
          <p className="text-[#71717a] text-sm md:text-base max-w-lg mx-auto mb-10 leading-relaxed">
            AgentEdge watches MLB, NBA, NHL, NFL, and World Cup markets around the clock.
            It learns from every bet, adapts to your bankroll, and only acts when it finds real edge — built around how you bet.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10 text-left">
            {[
              { icon: "◈", label: "LIVE FEED", sub: "Watch your agent think" },
              { icon: "◉", label: "AUTO BANKROLL", sub: "Units sized from %" },
              { icon: "◆", label: "LIVING MEMORY", sub: "Learns as it goes" },
              { icon: "▲", label: "YOUR SPORTS", sub: "MLB · NBA · NHL · NFL · WC" },
            ].map((f) => (
              <div key={f.label} className="bg-[#111] border border-[#222] rounded p-3">
                <span className="text-[#00d084] text-lg">{f.icon}</span>
                <div className="text-[10px] font-bold tracking-widest text-[#e4e4e7] mt-1">{f.label}</div>
                <div className="text-[10px] text-[#71717a] mt-0.5">{f.sub}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/register" className="bg-[#00d084] text-black text-xs font-bold px-8 py-3 rounded tracking-widest hover:bg-[#00b872] transition-colors w-full sm:w-auto">CREATE YOUR AGENT</Link>
            <Link href="/login" className="border border-[#222] text-[#71717a] text-xs px-8 py-3 rounded tracking-widest hover:border-[#00d084] hover:text-[#00d084] transition-colors w-full sm:w-auto">SIGN IN</Link>
          </div>
          <p className="text-[#2a2a2a] text-xs mt-6 tracking-wider">INVITE ONLY &mdash; BETA ACCESS</p>
        </div>
      </main>
      <footer className="border-t border-[#222] px-6 py-4 flex items-center justify-between">
        <span className="text-[#2a2a2a] text-xs tracking-wider">&copy; 2026 EDGESPORTSMEDIA</span>
        <span className="text-[#2a2a2a] text-xs">FOR ENTERTAINMENT PURPOSES</span>
      </footer>
    </div>
  );
}
