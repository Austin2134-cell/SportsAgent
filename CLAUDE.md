# AgentEdge — Claude Code Context

## What This Is

**AgentEdge** (by EdgeSportsMedia) is a per-user sports betting AI agent platform. Each user provisions their own agent with a bankroll, sports preferences, and risk profile. The agent runs continuously — polling markets, writing to a live feed, tracking hypotheses, recommending positions, and learning from outcomes.

Legacy name "EdgeBet" may still appear in some deployment URLs.

## Agent Architecture (v2)

```
Shared layer:  market poller (every 15 min) → market_snapshots
Per-user:      agent scan (every 30 min) → episodes / hypotheses / positions / beliefs
On signup:     /setup wizard → agent_instances + seeded beliefs
UI:            /agent cockpit (live feed) | /dashboard (positions) | /history
```

Key backend modules:
- `backend/agent/kernel.py` — per-user scan loop
- `backend/agent/provision.py` — agent setup on onboarding
- `backend/agent/bankroll.py` — auto unit sizing from bankroll %
- `backend/agent/sports.py` — sport registry (MLB, NBA, NHL, NFL, WC)
- `backend/workers/market_poller.py` — shared odds polling

**Pending migration:** Run `supabase/migrations/001_agentedge.sql` in Supabase SQL Editor.

## What This Was (EdgeBet v1)

EdgeBet was a sports betting advisory platform. It ran an AI agent (Claude) once per day per user, analyzed live odds and injury data, and produced a structured daily card of up to 5 official wagers. Users track their record over time.

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI (Python), deployed on Railway via `uvicorn` |
| Frontend | Next.js 14, Tailwind CSS, `lucide-react` |
| Database | Supabase (PostgreSQL + Auth + RLS) |
| AI | Anthropic SDK — `claude-sonnet-4-6` |
| Scheduling | APScheduler (AsyncIOScheduler) |
| Odds data | The Odds API (`ODDS_API_KEY`) |
| Sports context | ESPN public API (no key needed) |

## Repo Structure

```
SportsAgent/
├── backend/
│   ├── main.py              # FastAPI app, APScheduler jobs, all API routes
│   ├── auth.py              # JWT auth via Supabase
│   ├── database.py          # Supabase client singleton
│   ├── esm/
│   │   ├── system_prompt.py # Full ESM framework (~3000 tokens, prompt-cached)
│   │   ├── odds_client.py   # Wraps The Odds API
│   │   ├── stats_client.py  # Wraps ESPN API
│   │   └── config.py        # Active sports, prop markets, API keys
│   ├── services/
│   │   ├── agent_runner.py  # Per-user card generation (calls Claude)
│   │   └── grader.py        # Auto-grades pending bets via ESPN box scores
│   └── learning/
│       └── memory.py        # Performance stats: compute, store, format for prompt
├── frontend/                # Next.js app
└── supabase/
    └── schema.sql           # Full DB schema — run manually in Supabase SQL Editor
```

## Scheduled Jobs

| Job | Schedule | What it does |
|---|---|---|
| `run_daily_cards` | Daily 9:30 AM MT | Grades yesterday's bets → generates today's card for all active users |
| `run_weekly_digest` | Monday 8:00 AM MT | Logs 7-day record for all active users |

## Agent Philosophy (as of June 2026)

The agent is framed as a **professional sports gambler whose livelihood depends on the bankroll**. The singular goal is week-over-week profitability — not finding interesting picks. Key principles baked into the system prompt:

- **0-play days are valid** — passing on a weak slate protects capital
- **Never chase losses** — losing streaks trigger tighter filters and smaller unit sizes
- **Fractional Kelly sizing** — units scaled by edge gap (true prob minus implied prob): strong edge (10%+) = 2.5–3u, solid (5–9%) = 2u, moderate (2–4%) = 1–1.5u, thin = lean only
- **EV-first, no arbitrary juice ceilings** — a mispriced -200 line is better than a correctly priced -110 line. All plays show `implied_prob_pct`, `true_prob_pct`, and `edge_gap_pct`
- **Market-level learning** — if memory shows a market losing consistently, avoid it until data recovers

## Key Architecture Decisions

**Agent is stateless per-call by design** — Claude gets a fresh context each day built from:
1. Live odds snapshot (The Odds API)
2. Injury/team context (ESPN)
3. Performance memory (90-day rolling stats from `agent_memory` table)
4. User preferences (max plays, unit size, risk level, sports)

**Prompt caching** — The static ESM system prompt (~3000 tokens) uses `cache_control: {"type": "ephemeral"}`. On repeat calls within the cache window, token cost drops ~90% for that section.

**Learning loop** — `grader.py` grades bets → calls `memory.refresh_memory()` → stats written to `agent_memory` table → next day's prompt includes performance history by market/sport/confidence/odds bucket + recent losses.

## Database Tables

- `profiles` — extends Supabase auth.users (email, full_name, is_admin, is_active)
- `preferences` — per-user settings (sports, bet_types, risk_level, max_plays, unit_size)
- `cards` — daily AI-generated cards (plays, leans, quick_reads, pass_notes, raw JSON)
- `bets` — individual wagers extracted from cards (result starts as "pending")
- `invite_codes` — invite-only registration
- `agent_memory` — 90-day rolling performance stats JSON per user ← **requires migration below**

## Pending Supabase Migration

The `agent_memory` table does not exist yet in production. Run this in Supabase SQL Editor:

```sql
CREATE TABLE IF NOT EXISTS agent_memory (
  id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id    UUID REFERENCES profiles(id) ON DELETE CASCADE UNIQUE,
  stats      JSONB DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own memory" ON agent_memory FOR SELECT USING (auth.uid() = user_id);
```

After running: trigger `POST /api/admin/grade-all` once to seed memory from existing graded bets.

## Current Status / Next Step

**Status:** Learning module, weekly digest, EV-first prompt rewrite, and **World Cup card pipeline** are all merged to `main` and live. WC cards run daily at 9:30 AM MDT via GitHub Actions (`wc-card.yml`) and can be triggered manually from the Actions tab.

**The single blocking task before the learning loop actually does anything:**
1. Go to Supabase dashboard → SQL Editor → New query, run:
```sql
CREATE TABLE IF NOT EXISTS agent_memory (
  id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id    UUID REFERENCES profiles(id) ON DELETE CASCADE UNIQUE,
  stats      JSONB DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own memory" ON agent_memory FOR SELECT USING (auth.uid() = user_id);
```
2. Then call `POST /api/admin/grade-all` (with admin auth token) to seed memory from existing graded bets.

Once those two steps are done, the agent will read its own performance history every morning and adjust sizing/filters accordingly.

## Known Issues / Context

- **Only MLB showing up** — Mid-June: NFL/NCAAB off-season, NBA/NHL playoffs over. Correct behavior, not a bug. NBA/NHL will return in Oct/Nov.
- **Pending Supabase migration** — `agent_memory` table must still be created manually (see "Current Status / Next Step" above). Until done, learning loop is not active.
- **Grading is automatic** — `grader.py` uses ESPN box scores. Non-player-prop bets (spreads, moneylines, totals) can't be auto-graded and appear at `/api/admin/pending-bets` for manual review.
- **Performance monitoring** — after the migration is run and a few days of cards generate with memory context, watch ROI trend. The new EV-first + professional mandate framing should produce fewer but sharper plays.

## Production URLs

| Service | URL |
|---|---|
| Frontend (Vercel) | `https://sports-agent-phi.vercel.app` |
| Backend (Railway) | configured via `NEXT_PUBLIC_API_URL` in Vercel env vars |
| Supabase | `https://nlfalrpuspdezfnlakrv.supabase.co` |

## Open Pull Requests

None currently open. PR #10 merged to main (Session 4).

## Session Log

Newest entries first. Each session should append a short entry here before ending.

### 2026-06-17 (Session 4)
- Built and merged **PR #10**: email redesign, password reset page, WC pipeline polish.
  - `backend/services/mailer.py` — full HTML email template rebuild to match ESM_Daily_Card_v2.pdf spec: "DAILY CARD" 42px title, "EDGE SPORTS MEDIA · PRECISION ANALYTICS" header, 5px gradient accent bar, amber section bars with left border + right play count badge, sport pill badges per sport, 22px bet name, 52px grade letter, passes with red left border, footer with full disclaimer.
  - `frontend/app/reset-password/page.tsx` — new: handles Supabase `PASSWORD_RECOVERY` auth event; form to set new password; redirects to `/dashboard` on success.
  - `frontend/public/card-preview.html` — static mock card for design preview at `/card-preview.html` on Vercel.
  - `backend/run_world_cup_card.py` — fixed default email to `Austin.noyes21@gmail.com`.
  - `.github/workflows/wc-card.yml` — removed hardcoded `ref: claude/claude-md-review-jye8vi` from checkout step so workflow always runs from `main`.
- Fixed Gmail SMTP auth (BadCredentials): root cause was 2FA not enabled; fix was enabling 2FA + generating app password `zvczukgsbcdjvnsa`, stored in `EMAIL_SMTP_PASS` GitHub Secret.
- Identified production Vercel URL: `https://sports-agent-phi.vercel.app`. Updated Supabase Site URL to match.
- **Next up:** run the Supabase `agent_memory` migration (still pending — see "Current Status / Next Step" above).

### 2026-06-17 (Session 3)
- Built and merged **PR #9**: complete World Cup card pipeline — superseded the older PR #2 (now closed).
  - `backend/esm/system_prompt.py` — rewrote FIFA WC section with tiered market hierarchy: DNB (Tier 1, 65-75% hit rate), U2.5 Goals (Tier 1, 57-62%), straight ML only within -130 (Tier 2), leans only for Double Chance / BTTS / AH -0.5. Embedded 3-way vig removal math so Claude can evaluate DNB value vs straight ML on every play. Added situational filters (opener/must-win/dead rubber/host nations/altitude). Soccer is now sport = "SOCCER" in schema.
  - `backend/esm/config.py` — added `soccer_fifa_world_cup` to ACTIVE_SPORTS and PROP_MARKETS (`player_goal_scorer_anytime`, `player_shots_on_target`).
  - `backend/esm/odds_client.py` — added WC SGO league mapping, soccer stat maps, "WC"/"FIFAWC" SGO sport tokens.
  - `backend/services/mailer.py` — new: HTML email delivery via SMTP or SendGrid; dark-theme card template; falls back to `/tmp/esm_card_DATE.html`.
  - `backend/services/social.py` — new: Twitter/X thread formatter (280-char enforced per tweet, WC hashtags, one tweet per play).
  - `backend/run_world_cup_card.py` — new standalone runner: TOA → SGO fallback, dynamic tournament day calc, Claude ESM call, console card print, Twitter thread print, optional email delivery.
  - `.github/workflows/wc-card.yml` — new: `workflow_dispatch` (date/email/no_email inputs) + daily schedule `30 15 * * *` (9:30 AM MDT). Runs on `ubuntu-latest` to bypass remote-environment network egress restrictions. All API keys from GitHub Secrets.
- First successful end-to-end GitHub Actions run: June 17 card generated + emailed to anoyes@spokeo.com (2m 1s, green).

### 2026-06-12 (Session 2)
- Merged **PR #1**: agent learning module, weekly digest, EV-first ESM prompt rewrite (removed juice ceilings / hard caps in favor of true-prob-vs-implied-prob sizing).
- Restructured: moved `services/memory.py` → **`backend/learning/memory.py`** and updated all imports.
- Added `CLAUDE.md` to repo root (PR #3) and a keyword index + module docstrings (PR #4).

### 2026-06-12 (Session 1)
- Built the learning module, weekly digest, and ESM prompt rewrite (became PR #1, merged in Session 2).
- Built World Cup support + email/social formatting (became PR #2, superseded by PR #9).

## Environment Variables (backend)

```
ANTHROPIC_API_KEY
SUPABASE_URL
SUPABASE_SERVICE_KEY
ODDS_API_KEY
FRONTEND_URL
TIMEZONE=America/Denver
```

## Running Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Where Things Live (Keyword Index)

| If you're looking for... | Go to |
|---|---|
| Learning module, performance memory, win/loss stats by market | `backend/learning/memory.py` |
| Betting rules, juice ceiling, unit sizing, edge thresholds | `backend/esm/system_prompt.py` |
| Odds, lines, player props (The Odds API) | `backend/esm/odds_client.py` |
| Active sports, prop markets, API keys config | `backend/esm/config.py` |
| Injury/team context, scoreboard (ESPN) | `backend/esm/stats_client.py` |
| Grading bets, auto-grading via box scores, W/L results | `backend/services/grader.py` |
| Daily card generation, Claude API call | `backend/services/agent_runner.py` |
| API routes, admin endpoints, invite codes, scheduler jobs | `backend/main.py` |
| Auth, JWT validation, admin check | `backend/auth.py` |
| Supabase client setup | `backend/database.py` |
| DB schema, tables, RLS policies | `supabase/schema.sql` |
| Frontend pages (dashboard, login, history, preferences) | `frontend/app/` |
| API calls from frontend | `frontend/lib/api.ts` |
| World Cup standalone card runner | `backend/run_world_cup_card.py` |
| WC GitHub Actions workflow | `.github/workflows/wc-card.yml` |
| Email delivery (HTML card) | `backend/services/mailer.py` |
| Twitter/X thread formatter | `backend/services/social.py` |
| Password reset page (Supabase recovery flow) | `frontend/app/reset-password/page.tsx` |
| Card design preview (static HTML) | `frontend/public/card-preview.html` |

## Session Log Maintenance

- Keep the **Session Log** above to roughly the **last 5-10 entries**. At the start of a session, if it's getting long:
  - Fold any still-relevant facts from older entries into the permanent sections (Repo Structure, Current Status, Known Issues, Open PRs).
  - Delete the entries you folded in, oldest first.
- For an unusually long/complex session, write the full detail to `docs/sessions/YYYY-MM-DD.md` and link it from that day's log entry (e.g. `- 2026-06-12: ... (details: docs/sessions/2026-06-12.md)`). Most sessions don't need a separate file — the one-line summary in the log is enough.

## Cross-Device / Session Sync

- All code changes are committed and pushed to GitHub — pull on any device to sync
- Supabase schema changes require a manual SQL run (not automatic)
- Update the "Known Issues / Context" section above after significant sessions so the next session starts informed
