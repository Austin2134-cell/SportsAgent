const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function apiFetch(path: string, token: string, options: RequestInit = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...options.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
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
  runCard:    (token: string) => apiFetch("/api/admin/run-card", token, { method: "POST" }),
  gradeAll:   (token: string) => apiFetch("/api/admin/grade-all", token, { method: "POST" }),
  gradeBet:   (token: string, bet_id: string, result: string, units_result: number) => apiFetch("/api/admin/grade", token, { method: "POST", body: JSON.stringify({ bet_id, result, units_result }) }),
  listUsers:  (token: string) => apiFetch("/api/admin/users", token),
  pendingBets:(token: string) => apiFetch("/api/admin/pending-bets", token),
  createInvite:(token: string, code: string, max_uses = 1) => apiFetch(`/api/admin/invite?code=${code}&max_uses=${max_uses}`, token, { method: "POST" }),
};
