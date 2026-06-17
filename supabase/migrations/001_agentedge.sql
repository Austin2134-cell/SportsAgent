-- AgentEdge — per-user agent infrastructure
-- Run in Supabase SQL Editor after base schema.sql

-- ── Agent Instances (one per user) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_instances (
  user_id            UUID REFERENCES profiles(id) ON DELETE CASCADE PRIMARY KEY,
  status             TEXT NOT NULL DEFAULT 'pending_setup',
  mode               TEXT NOT NULL DEFAULT 'scanning',
  bankroll_starting  DECIMAL NOT NULL DEFAULT 1000,
  bankroll_current   DECIMAL NOT NULL DEFAULT 1000,
  unit_pct           DECIMAL NOT NULL DEFAULT 0.02,
  max_daily_pct      DECIMAL NOT NULL DEFAULT 0.06,
  units_at_risk      DECIMAL NOT NULL DEFAULT 0,
  subscription_tier  TEXT NOT NULL DEFAULT 'beta',
  last_active_at     TIMESTAMPTZ,
  last_scan_at       TIMESTAMPTZ,
  setup_completed_at TIMESTAMPTZ,
  created_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ── Agent Episodes (decision log / live feed) ───────────────────────────────
CREATE TABLE IF NOT EXISTS agent_episodes (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id          UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  timestamp        TIMESTAMPTZ DEFAULT NOW(),
  trigger_type     TEXT NOT NULL DEFAULT 'scheduled_scan',
  trigger_payload  JSONB DEFAULT '{}',
  episode_type     TEXT NOT NULL DEFAULT 'observation',
  title            TEXT NOT NULL DEFAULT '',
  reasoning        TEXT DEFAULT '',
  action_payload   JSONB DEFAULT '{}',
  outcome          TEXT,
  lesson           TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_episodes_user_time
  ON agent_episodes(user_id, timestamp DESC);

-- ── Agent Beliefs (learned insights per user) ───────────────────────────────
CREATE TABLE IF NOT EXISTS agent_beliefs (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id          UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  category         TEXT NOT NULL DEFAULT 'general',
  belief           TEXT NOT NULL,
  confidence       DECIMAL NOT NULL DEFAULT 0.5,
  evidence_count   INTEGER NOT NULL DEFAULT 1,
  last_validated   TIMESTAMPTZ DEFAULT NOW(),
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_beliefs_user
  ON agent_beliefs(user_id, category);

-- ── Agent Hypotheses (watching, not yet acting) ─────────────────────────────
CREATE TABLE IF NOT EXISTS agent_hypotheses (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id          UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  sport            TEXT NOT NULL DEFAULT '',
  game             TEXT NOT NULL DEFAULT '',
  market           TEXT NOT NULL DEFAULT '',
  player           TEXT DEFAULT '',
  thesis           TEXT NOT NULL DEFAULT '',
  status           TEXT NOT NULL DEFAULT 'watching',
  expires_at       TIMESTAMPTZ,
  created_at       TIMESTAMPTZ DEFAULT NOW(),
  updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_hypotheses_user_status
  ON agent_hypotheses(user_id, status);

-- ── Market Snapshots (shared perception layer) ─────────────────────────────
CREATE TABLE IF NOT EXISTS market_snapshots (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  sport_key        TEXT NOT NULL,
  snapshot         JSONB NOT NULL DEFAULT '{}',
  captured_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_sport_time
  ON market_snapshots(sport_key, captured_at DESC);

-- ── Preferences extensions ──────────────────────────────────────────────────
ALTER TABLE preferences
  ADD COLUMN IF NOT EXISTS bankroll_starting DECIMAL DEFAULT 1000,
  ADD COLUMN IF NOT EXISTS unit_pct DECIMAL DEFAULT 0.02,
  ADD COLUMN IF NOT EXISTS max_daily_pct DECIMAL DEFAULT 0.06;

-- Expand default sports to include World Cup
ALTER TABLE preferences
  ALTER COLUMN sports SET DEFAULT ARRAY['MLB', 'NBA', 'NHL', 'NFL', 'WC'];

-- ── RLS ─────────────────────────────────────────────────────────────────────
ALTER TABLE agent_instances  ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_episodes   ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_beliefs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_hypotheses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own agent" ON agent_instances
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can view own episodes" ON agent_episodes
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can view own beliefs" ON agent_beliefs
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can view own hypotheses" ON agent_hypotheses
  FOR SELECT USING (auth.uid() = user_id);
