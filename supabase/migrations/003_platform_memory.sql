-- Platform agent brain — collective performance memory (single global row)
-- Run in Supabase SQL Editor after 001/002

CREATE TABLE IF NOT EXISTS platform_memory (
  key        TEXT PRIMARY KEY DEFAULT 'global',
  stats      JSONB DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Service role writes; no user-facing RLS needed for prompt injection via backend
INSERT INTO platform_memory (key, stats)
VALUES ('global', '{}')
ON CONFLICT (key) DO NOTHING;
