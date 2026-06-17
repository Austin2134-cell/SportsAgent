import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "AgentEdge — Sports Betting AI Agent",
  description: "Your personal AI sports betting agent by EdgeSportsMedia. Continuous market analysis, living memory, auto bankroll sizing.",
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-[#0a0a0a] text-[#e4e4e7] font-mono antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
