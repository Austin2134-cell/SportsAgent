# AgentEdge

A per-user sports betting AI agent platform. FastAPI (Python) backend + Next.js 14 (TypeScript) frontend, backed by hosted Supabase (Postgres + Auth), with Anthropic Claude for agent/card generation and The Odds API / SportsGameOdds for odds data.

See `CLAUDE.md` for product architecture, module map, and DB schema details.

## Cursor Cloud specific instructions

### Services
- **Backend** (`backend/`): FastAPI. Run with `python3 -m uvicorn main:app --reload --port 8000` from `backend/`. Health: `GET http://localhost:8000/health`. Standard run commands are in `CLAUDE.md`.
- **Frontend** (`frontend/`): Next.js. Run with `npm run dev` from `frontend/` (serves `http://localhost:3000`). Scripts in `frontend/package.json`.

### Non-obvious caveats
- **`uvicorn`/`fastapi` console scripts are not on PATH** (pip installs them to `~/.local/bin`). Always launch the backend via `python3 -m uvicorn ...`.
- **Backend fails to import without Supabase env.** `backend/database.py` calls `create_client()` at module import, so `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` must be set (in `backend/.env`) or the app crashes on startup before serving anything. The Supabase client validates the key is JWT-shaped at creation (no network call), so a JWT-shaped string is enough to *boot*, but any DB-backed route (`/auth/register`, `/api/*`, cards, agent scans) needs the **real** keys for the hosted project to return 200 instead of 500.
- **Required secrets for real functionality** (set in `backend/.env`; frontend needs the `NEXT_PUBLIC_*` ones in `frontend/.env.local`): `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, and one odds key (`SGO_API_KEY` is primary per `ODDS_PRIMARY_SOURCE=sgo`, or `ODDS_API_KEY`). Frontend: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`). `SUPABASE_URL` for the project is `https://nlfalrpuspdezfnlakrv.supabase.co`. Env templates: `backend/.env.template` / `backend/.env.example` (frontend has no template).
- **Registration is invite-only**: `/auth/register` requires a valid row in the `invite_codes` table, so creating an account end-to-end needs both real Supabase keys and a seeded invite code.
- **Starting the backend auto-starts APScheduler cron jobs** (market polling, grading, daily/WC cards) that call external APIs on a schedule. Set `WC_CARD_ENABLED=false` and use the manual admin endpoints (`/api/admin/run-card`, `/api/admin/grade-all`, `/api/agent/scan`) for isolated testing.
- **Supabase schema/migrations are applied manually** in the Supabase SQL Editor (`supabase/schema.sql`, `supabase/migrations/*.sql`) — there is no automated migration on boot. The `agent_memory` / platform-memory tables are a known pending migration (see `CLAUDE.md`).

### Lint / build
- Frontend: `npm run build` runs Next.js ESLint + TypeScript checks as part of the build. Standalone `npm run lint` (`next lint`) is **interactive on first run** because no ESLint config is committed — prefer `npm run build` to validate lint/types non-interactively.
- Backend: no configured linter or test suite in the repo.
