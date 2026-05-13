import type { Config } from "tailwindcss";
const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        edge: {
          bg: "#0a0a0a", surface: "#111111", card: "#161616", border: "#222222",
          muted: "#2a2a2a", green: "#00d084", red: "#ff4d4d", amber: "#f59e0b",
          blue: "#3b82f6", text: "#e4e4e7", sub: "#71717a",
        },
      },
      fontFamily: { mono: ["'JetBrains Mono'", "ui-monospace", "monospace"] },
    },
  },
  plugins: [],
};
export default config;
