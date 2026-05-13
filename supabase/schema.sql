-- EdgeBet Platform — Supabase Schema
-- Run this in Supabase SQL Editor (Database → SQL Editor → New Query)

-- ── Profiles (extends Supabase auth.users) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
  id          UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  email       TEXT,
  full_name   TEXT,
  is_admin    BOOLEAN DEFAULT false,
  is_active   BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO profiles (id, email)
  VALUES (NEW.id, NEW.email);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ── Invite Codes ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invite_codes (
  id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  code         TEXT UNIQUE NOT NULL,
  created_by   UUID REFERENCES profiles(id),
  max_uses     INTEGER DEFAULT 1,
  current_uses INTEGER DEFAULT 0,
  is_active    BOOLEAN DEFAULT true,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── User Preferences ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS preferences (
  id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id            UUID REFERENCES profiles(id) ON DELETE CASCADE UNIQUE,
  sports             TEXT[]  DEFAULT ARRAY['MLB', 'NBA', 'NHL'],
  bet_types          TEXT[]  DEFAULT ARRAY['player_props', 'straight'],
  risk_level         TEXT    DEFAULT 'MEDIUM',
  max_plays          INTEGER DEFAULT 5,
  unit_size          DECIMAL DEFAULT 50,
  include_parlays    BOOLEAN DEFAULT false,
  notification_email TEXT,
  updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ── Daily Cards ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cards (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     UUID REFERENCES profiles(id) ON DELETE CASCADE,
  date        DATE NOT NULL,
  slate_grade TEXT,
  slate_note  TEXT,
  plays       JSONB DEFAULT '[]',
  leans       JSONB DEFAULT '[]',
  quick_reads JSONB DEFAULT '[]',
  pass_notes  JSONB DEFAULT '[]',
  raw_card    JSONB,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, date)
);

-- ── Bets ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bets (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id         UUID REFERENCES profiles(id) ON DELETE CASCADE,
  card_id         UUID REFERENCES cards(id) ON DELETE CASCADE,
  date            DATE NOT NULL,
  sport           TEXT,
  game            TEXT,
  bet             TEXT,
  market          TEXT,
  odds            INTEGER,
  book            TEXT,
  units           DECIMAL DEFAULT 2,
  confidence      TEXT,
  result          TEXT DEFAULT 'pending',
  units_result    DECIMAL DEFAULT 0,
  post_slate_tag  TEXT DEFAULT '',
  notes           TEXT DEFAULT '',
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Row Level Security ──────────────────────────────────────────────────────
ALTER TABLE profiles    ENABLE ROW LEVEL SECURITY;
ALTER TABLE preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE cards       ENABLE ROW LEVEL SECURITY;
ALTER TABLE bets        ENABLE ROW LEVEL SECURITY;
ALTER TABLE invite_codes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own profile"   ON profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update own profile" ON profiles FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "Users can manage own preferences" ON preferences FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users can view own cards" ON cards FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can view own bets"  ON bets  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Anyone can read invite codes" ON invite_codes FOR SELECT USING (true);

INSERT INTO invite_codes (code, max_uses, is_active)
VALUES ('EDGEBET2026', 10, true)
ON CONFLICT (code) DO NOTHING;
