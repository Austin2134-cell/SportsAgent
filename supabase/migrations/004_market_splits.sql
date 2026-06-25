-- Phase 2: external betting splits (public %, money %, sharp indicators)
-- Populated by Action Network / SportsDataIO / OddsJam sync job when configured.

CREATE TABLE IF NOT EXISTS market_splits (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  sport_key        TEXT NOT NULL,
  event_id         TEXT NOT NULL,
  home_team        TEXT,
  away_team        TEXT,
  market           TEXT NOT NULL,
  public_bet_pct   DECIMAL,
  public_money_pct DECIMAL,
  sharp_indicator  TEXT,
  source           TEXT NOT NULL,
  raw              JSONB DEFAULT '{}',
  captured_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_splits_event_time
  ON market_splits(sport_key, event_id, captured_at DESC);

ALTER TABLE market_splits ENABLE ROW LEVEL SECURITY;
