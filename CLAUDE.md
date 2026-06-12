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
│   └── services/
│       ├── agent_runner.py  # Per-user card generation (calls Claude)
│       ├── grader.py        # Auto-grades pending bets via ESPN box scores
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

## Known Issues / Context

- **Only MLB showing up** — Mid-June: NFL/NCAAB off-season, NBA/NHL playoffs over. The ESM system prompt also explicitly tells the agent to pass on NFL/NCAAB May–August. This is correct behavior, not a bug.
- **Performance has been poor** — The learning system (memory.py) was just added to address this. Monitor ROI after the memory table is seeded and a few days of cards run with context.
- **Grading is automatic** — `grader.py` uses ESPN box scores. Bets that can't be auto-graded (no ESPN match, non-player-prop markets) are left as "pending" and show up at `/api/admin/pending-bets` for manual grading.

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

## Cross-Device / Session Sync

- All code changes are committed and pushed to GitHub — pull on any device to sync
- Supabase schema changes require a manual SQL run (not automatic)
- Update the "Known Issues / Context" section above after significant sessions so the next session starts informed
