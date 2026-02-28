-- ═══════════════════════════════════════════════════════════════════════════
-- NCHETA DATABASE MIGRATIONS
-- Run this entire file in: Supabase → SQL Editor → New Query
-- ═══════════════════════════════════════════════════════════════════════════

-- ── Helpers ─────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Auto-update updated_at trigger function (shared by all tables)
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 1: schools
-- Every user belongs to a school. Access codes gate registration.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS schools (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT        NOT NULL,
  location    TEXT        NOT NULL,
  access_code TEXT        NOT NULL UNIQUE,
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER schools_updated_at
  BEFORE UPDATE ON schools
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 2: users
-- Mirrors auth.users with app-specific fields.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS users (
  id          UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name        TEXT        NOT NULL,
  email       TEXT        NOT NULL UNIQUE,
  role        TEXT        NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
  school_id   UUID        REFERENCES schools(id),
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_school ON users(school_id);
CREATE INDEX IF NOT EXISTS idx_users_role   ON users(role);

CREATE TRIGGER users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 3: student_accessibility
-- Written by onboarding. Updated by settings page.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS student_accessibility (
  id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID    NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,

  -- Core accessibility choices
  disability_profile  TEXT    NOT NULL DEFAULT 'visual'
                      CHECK (disability_profile IN ('visual','hearing','dyslexia','motor')),
  language            TEXT    NOT NULL DEFAULT 'english'
                      CHECK (language IN ('english','hausa','yoruba','igbo')),

  -- Settings page controls
  font_size           TEXT    NOT NULL DEFAULT 'large'
                      CHECK (font_size IN ('small','medium','large','extra-large')),
  voice_speed         TEXT    NOT NULL DEFAULT 'normal'
                      CHECK (voice_speed IN ('slow','normal','fast')),
  high_contrast       BOOLEAN NOT NULL DEFAULT TRUE,

  -- Onboarding state
  onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE,
  setup_guide_type    TEXT    CHECK (setup_guide_type IN ('teacher','family','self')),

  last_active_at      TIMESTAMPTZ,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER student_accessibility_updated_at
  BEFORE UPDATE ON student_accessibility
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 4: lessons
-- Teacher uploads. Processing pipeline updates processing_status.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS lessons (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  title               TEXT        NOT NULL,
  subject             TEXT        NOT NULL CHECK (subject IN ('Science','Math','History','English','Geography','Biology','Other')),
  teacher_id          UUID        NOT NULL REFERENCES users(id),
  school_id           UUID        NOT NULL REFERENCES schools(id),

  -- Storage
  original_file_path  TEXT,
  original_file_name  TEXT,
  file_type           TEXT        CHECK (file_type IN ('pdf','docx','pptx')),

  -- Metadata
  page_count          INTEGER,
  icon_emoji          TEXT        NOT NULL DEFAULT '📄',
  is_published        BOOLEAN     NOT NULL DEFAULT FALSE,

  -- AI processing state
  processing_status   TEXT        NOT NULL DEFAULT 'pending'
                      CHECK (processing_status IN ('pending','extracting','generating_audio','simplifying','done','failed')),

  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lessons_teacher ON lessons(teacher_id);
CREATE INDEX IF NOT EXISTS idx_lessons_school  ON lessons(school_id);
CREATE INDEX IF NOT EXISTS idx_lessons_status  ON lessons(processing_status);

CREATE TRIGGER lessons_updated_at
  BEFORE UPDATE ON lessons
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 5: lesson_pages
-- One row per page. Lesson reader fetches one at a time.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS lesson_pages (
  id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id           UUID    NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  page_number         INTEGER NOT NULL,

  content_original    TEXT,
  content_simplified  TEXT,
  image_description   TEXT,

  UNIQUE (lesson_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_lesson_pages_lesson ON lesson_pages(lesson_id, page_number);


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 6: lesson_audio
-- One row per lesson per language. URL points to public Supabase storage.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS lesson_audio (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id    UUID        NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  language     TEXT        NOT NULL CHECK (language IN ('english','hausa','yoruba','igbo')),
  audio_url    TEXT        NOT NULL,
  duration_sec INTEGER,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (lesson_id, language)
);

CREATE INDEX IF NOT EXISTS idx_lesson_audio_lesson ON lesson_audio(lesson_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 7: lesson_assignments
-- Teacher assigns specific lessons to specific students.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS lesson_assignments (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id   UUID        NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  student_id  UUID        NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  assigned_by UUID        NOT NULL REFERENCES users(id),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (lesson_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_assignments_student ON lesson_assignments(student_id);
CREATE INDEX IF NOT EXISTS idx_assignments_lesson  ON lesson_assignments(lesson_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 8: student_progress
-- Most-read table. Updated on every page turn.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS student_progress (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id          UUID        NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  lesson_id           UUID        NOT NULL REFERENCES lessons(id)  ON DELETE CASCADE,

  current_page        INTEGER     NOT NULL DEFAULT 1,
  is_completed        BOOLEAN     NOT NULL DEFAULT FALSE,
  completed_at        TIMESTAMPTZ,
  last_accessed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  time_spent_seconds  INTEGER     NOT NULL DEFAULT 0,

  UNIQUE (student_id, lesson_id)
);

CREATE INDEX IF NOT EXISTS idx_progress_student ON student_progress(student_id);
CREATE INDEX IF NOT EXISTS idx_progress_lesson  ON student_progress(lesson_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 9: activity_log
-- Append-only. Drives "Recent Activity" on progress page.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS activity_log (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id UUID        NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  lesson_id  UUID        NOT NULL REFERENCES lessons(id)  ON DELETE CASCADE,
  action     TEXT        NOT NULL CHECK (action IN ('started','read_pages','completed')),
  pages_read INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_student_recent ON activity_log(student_id, created_at DESC);


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 10: teacher_notes
-- One note per teacher-student pair (upserted on save).
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS teacher_notes (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  teacher_id UUID        NOT NULL REFERENCES users(id),
  student_id UUID        NOT NULL REFERENCES users(id),
  note_text  TEXT        NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (teacher_id, student_id)
);

CREATE TRIGGER teacher_notes_updated_at
  BEFORE UPDATE ON teacher_notes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ═══════════════════════════════════════════════════════════════════════════
-- TABLE 11: processing_jobs
-- AI pipeline state. Frontend polls this during upload wizard step 3.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS processing_jobs (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id     UUID        NOT NULL UNIQUE REFERENCES lessons(id) ON DELETE CASCADE,
  status        TEXT        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','done','failed')),

  steps         JSONB       NOT NULL DEFAULT '{
    "extract_text":       false,
    "audio_english":      false,
    "audio_hausa":        false,
    "audio_yoruba":       false,
    "audio_igbo":         false,
    "simplify_dyslexia":  false,
    "image_descriptions": false
  }'::jsonb,

  error_message TEXT,
  started_at    TIMESTAMPTZ,
  completed_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ═══════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY (RLS)
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE schools              ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_accessibility ENABLE ROW LEVEL SECURITY;
ALTER TABLE lessons              ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_pages         ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_audio         ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_assignments   ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_progress     ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE teacher_notes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE processing_jobs      ENABLE ROW LEVEL SECURITY;

-- Service role bypasses ALL RLS (used by FastAPI backend)
-- No explicit policy needed — service_role automatically bypasses RLS.

-- Anon/authenticated cannot read other people's rows.
-- These minimal policies only allow read/write on own data.
-- FastAPI backend uses service_role key so these policies don't apply to it.

-- users: can read own row only
CREATE POLICY "users_own" ON users
  FOR SELECT USING (id = auth.uid());

-- student_accessibility: own row only
CREATE POLICY "accessibility_own" ON student_accessibility
  FOR ALL USING (user_id = auth.uid());

-- student_progress: own rows only
CREATE POLICY "progress_own" ON student_progress
  FOR ALL USING (student_id = auth.uid());


-- ═══════════════════════════════════════════════════════════════════════════
-- SEED DATA
-- Demo school so the register page works out of the box.
-- ═══════════════════════════════════════════════════════════════════════════
INSERT INTO schools (id, name, location, access_code, is_active)
VALUES (
  'aaaaaaaa-0000-0000-0000-000000000001',
  'Ncheta Demo School',
  'Lagos',
  'NCH-DEMO',
  TRUE
)
ON CONFLICT (access_code) DO NOTHING;

-- You can add more seed schools here for testing:
INSERT INTO schools (name, location, access_code)
VALUES
  ('GSS Kano Central',        'Kano',     'NCH-KANO'),
  ('LGEA Primary Kaduna',      'Kaduna',   'NCH-KAD'),
  ('Islamiyya School Zaria',   'Zaria',    'NCH-ZAR'),
  ('Nassarawa Science School', 'Nassarawa','NCH-NAS')
ON CONFLICT (access_code) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════════════════
-- DONE. Verify with:
--   SELECT table_name FROM information_schema.tables
--   WHERE table_schema = 'public';
-- ═══════════════════════════════════════════════════════════════════════════
