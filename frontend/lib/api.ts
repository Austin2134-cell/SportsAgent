import { getApiUrl } from "./env";

const BACKEND_ERROR =
  "Cannot reach the AgentEdge backend. Check NEXT_PUBLIC_API_URL in Vercel points to your Railway URL, then redeploy.";

async function parseResponse(res: Response) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    if (text.trimStart().startsWith("<!DOCTYPE") || text.trimStart().startsWith("<html")) {
      throw new Error(BACKEND_ERROR);
    }
    throw new Error(text.slice(0, 120) || "Request failed");
  }
}

export async function apiPostPublic(path: string, body: object) {
  const res = await fetch(`${getApiUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await parseResponse(res);
  if (!res.ok) throw new Error(data.detail || data.message || "Request failed");
  return data;
}

async function apiFetch(path: string, token: string, options: RequestInit = {}) {
  const res = await fetch(`${getApiUrl()}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...options.headers },
  });
  const data = await parseResponse(res);
  if (!res.ok) throw new Error(data.detail || data.message || "Request failed");
  return data;
}

export const api = {
  getTodayCard:   (token: string) => apiFetch("/api/card/today", token),
  getCardByDate:  (token: string, d: string) => apiFetch(`/api/card/${d}`, token),
  getBets:        (token: string, limit = 50) => apiFetch(`/api/bets?limit=${limit}`, token),
  getRecord:      (token: string) => apiFetch("/api/record", token),
  getDailyRecord: (token: string) => apiFetch("/api/record/daily", token),
  getProfile:     (token: string) => apiFetch("/api/profile", token),
  getPreferences: (token: string) => apiFetch("/api/preferences", token),
  updatePreferences: (token: string, prefs: object) => apiFetch("/api/preferences", token, { method: "PUT", body: JSON.stringify(prefs) }),
  getSports:      async () => {
    const res = await fetch(`${getApiUrl()}/api/sports`);
    return parseResponse(res);
  },
  getAgent:       (token: string) => apiFetch("/api/agent", token),
  setupAgent:     (token: string, setup: object) => apiFetch("/api/agent/setup", token, { method: "POST", body: JSON.stringify(setup) }),
  getAgentFeed:   (token: string, limit = 50) => apiFetch(`/api/agent/feed?limit=${limit}`, token),
  triggerScan:    (token: string) => apiFetch("/api/agent/scan", token, { method: "POST" }),
  pauseAgent:     (token: string) => apiFetch("/api/agent/pause", token, { method: "PUT" }),
  resumeAgent:    (token: string) => apiFetch("/api/agent/resume", token, { method: "PUT" }),
  runCard:    (token: string) => apiFetch("/api/admin/run-card", token, { method: "POST" }),
  gradeAll:   (token: string) => apiFetch("/api/admin/grade-all", token, { method: "POST" }),
  gradeBet:   (token: string, bet_id: string, result: string, units_result: number) => apiFetch("/api/admin/grade", token, { method: "POST", body: JSON.stringify({ bet_id, result, units_result }) }),
  listUsers:  (token: string) => apiFetch("/api/admin/users", token),
  pendingBets:(token: string) => apiFetch("/api/admin/pending-bets", token),
  createInvite:(token: string, code: string, max_uses = 1) => apiFetch(`/api/admin/invite?code=${code}&max_uses=${max_uses}`, token, { method: "POST" }),
};
