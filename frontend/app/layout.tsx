import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "EdgeBet — AI Sports Intelligence",
  description: "Agentic AI sports betting analysis powered by the ESM framework",
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
