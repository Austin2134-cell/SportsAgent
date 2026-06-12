# EdgeBet — Claude Code Context

## What This Is

EdgeBet is a sports betting advisory platform. It runs an AI agent (Claude) once per day per user, analyzes live odds and injury data, and produces a structured daily card of up to 5 official wagers. Users track their record over time.

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

## What Was Built This Session (June 2026)

### 1. Weekly Performance Digest
- Added `run_weekly_digest()` to `main.py` — fires every Monday 8 AM MT, logs 7-day W-L-P, net units, ROI for all active users
- Added `POST /api/admin/weekly-digest` endpoint to trigger manually

### 2. Agent Learning System
- **`backend/learning/memory.py`** (new) — computes 90-day rolling stats from graded bets: win rate by market, sport, confidence tier, odds bucket, and last 10 losses
- **`backend/services/grader.py`** — now calls `refresh_memory()` after grading, so stats update automatically every morning
- **`backend/services/agent_runner.py`** — reads performance context and injects it into each daily prompt above the market data; ESM system prompt now uses `cache_control: {"type": "ephemeral"}` for ~90% token cost reduction

### 3. ESM Prompt Overhaul
Rules removed (were too restrictive for a mispricing model):
- ~~Pitcher K line hard cap (5.5)~~
- ~~3-play-per-sport hard cap~~
- ~~Conservative line below-median mandate~~
- ~~-130 juice ceiling on straight bets~~
- ~~-180 batter hit ceiling~~

Rules replaced with:
- **EV-first framework** — estimated true probability must exceed implied probability. Juice level alone never disqualifies a play.
- **Professional Survival Mandate (Section 0, highest priority)** — week-over-week profitability as singular goal, bankroll protection, fractional Kelly sizing, drawdown awareness, weekly performance context awareness

### 4. Output Schema Updates
Each official play now outputs:
- `implied_prob_pct` — what the odds imply
- `true_prob_pct` — agent's estimate
- `edge_gap_pct` — the difference (drives unit sizing)
- `edge_summary` — now required to note whether agent is in tight or standard operating mode

## Known Issues / Context

- **Only MLB showing up** — Mid-June: NFL/NCAAB off-season, NBA/NHL playoffs over. Correct behavior, not a bug. NBA/NHL will return in Oct/Nov.
- **Pending Supabase migration** — `agent_memory` table must still be created manually (see migration below). Until done, learning loop is not active.
- **Grading is automatic** — `grader.py` uses ESPN box scores. Non-player-prop bets (spreads, moneylines, totals) can't be auto-graded and appear at `/api/admin/pending-bets` for manual review.
- **Performance monitoring** — after the migration is run and a few days of cards generate with memory context, watch ROI trend. The new EV-first + professional mandate framing should produce fewer but sharper plays.

## Last Session Ended (June 12, 2026)

**Status:** All code is built and pushed. One manual step remains before the system is fully live.

**The single blocking task:**
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

Once those two steps are done, the learning loop is fully active. The agent will read its own performance history every morning and adjust sizing/filters accordingly.

**Everything else is already live on branch `claude/recurring-task-creation-dpaexc` — open PR exists in GitHub.**

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

## Cross-Device / Session Sync

- All code changes are committed and pushed to GitHub — pull on any device to sync
- Supabase schema changes require a manual SQL run (not automatic)
- Update the "Known Issues / Context" section above after significant sessions so the next session starts informed
