-- ============================================================
--  NCHETA DATABASE MIGRATION
--  Run this ONCE in Supabase SQL Editor (Database → SQL Editor)
--  Order matters — do not rearrange.
-- ============================================================


-- ── 1. SCHOOLS ────────────────────────────────────────────────────────────────
-- Every teacher and student belongs to a school.
-- Access codes are used during teacher registration.
CREATE TABLE IF NOT EXISTS public.schools (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT        NOT NULL,
  location     TEXT        NOT NULL,
  access_code  TEXT        NOT NULL UNIQUE,
  is_active    BOOLEAN     NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Seed: Create a demo school so registration works immediately
INSERT INTO public.schools (name, location, access_code)
VALUES ('Ncheta Demo School', 'Abuja, FCT', 'NCH-DEMO')
ON CONFLICT (access_code) DO NOTHING;


-- ── 2. USERS ──────────────────────────────────────────────────────────────────
-- App-level user profiles. Mirrors auth.users (Supabase manages passwords).
CREATE TABLE IF NOT EXISTS public.users (
  id          UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name        TEXT        NOT NULL,
  email       TEXT        NOT NULL UNIQUE,
  role        TEXT        NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
  school_id   UUID        REFERENCES public.schools(id) ON DELETE SET NULL,
  is_active   BOOLEAN     NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_school ON public.users(school_id);
CREATE INDEX IF NOT EXISTS idx_users_role   ON public.users(role);


-- ── 3. STUDENT ACCESSIBILITY ──────────────────────────────────────────────────
-- Stores each student's disability profile, language, and UI preferences.
-- Set during onboarding. Updated via Settings page.
CREATE TABLE IF NOT EXISTS public.student_accessibility (
  id                   UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              UUID    NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,

  disability_profile   TEXT    NOT NULL DEFAULT 'visual'
                       CHECK  (disability_profile IN ('visual','hearing','dyslexia','motor')),
  language             TEXT    NOT NULL DEFAULT 'english'
                       CHECK  (language IN ('english','hausa','yoruba','igbo')),

  font_size            TEXT    NOT NULL DEFAULT 'large'
                       CHECK  (font_size IN ('small','medium','large','extra-large')),
  voice_speed          TEXT    NOT NULL DEFAULT 'normal'
                       CHECK  (voice_speed IN ('slow','normal','fast')),
  high_contrast        BOOLEAN NOT NULL DEFAULT true,

  onboarding_complete  BOOLEAN NOT NULL DEFAULT false,
  setup_guide_type     TEXT    CHECK (setup_guide_type IN ('teacher','family','self')),
  last_active_at       TIMESTAMPTZ,
  updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_accessibility_user ON public.student_accessibility(user_id);
CREATE INDEX IF NOT EXISTS idx_accessibility_profile ON public.student_accessibility(disability_profile);


-- ── 4. LESSONS ────────────────────────────────────────────────────────────────
-- Each lesson uploaded by a teacher. Original file stored in Supabase Storage.
CREATE TABLE IF NOT EXISTS public.lessons (
  id                   UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  title                TEXT    NOT NULL,
  subject              TEXT    NOT NULL
                       CHECK  (subject IN ('Science','Math','History','English',
                                           'Geography','Biology','Other')),
  teacher_id           UUID    NOT NULL REFERENCES public.users(id),
  school_id            UUID    NOT NULL REFERENCES public.schools(id),

  -- Storage reference
  original_file_path   TEXT,
  original_file_name   TEXT,
  file_type            TEXT    CHECK (file_type IN ('pdf','docx','pptx')),

  -- Metadata
  page_count           INTEGER,
  icon_emoji           TEXT    DEFAULT '📄',
  is_published         BOOLEAN NOT NULL DEFAULT false,

  -- AI processing state
  processing_status    TEXT    NOT NULL DEFAULT 'pending'
                       CHECK  (processing_status IN
                               ('pending','extracting','generating_audio',
                                'simplifying','done','failed')),

  created_at           TIMESTAMPTZ DEFAULT NOW(),
  updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lessons_teacher  ON public.lessons(teacher_id);
CREATE INDEX IF NOT EXISTS idx_lessons_school   ON public.lessons(school_id);
CREATE INDEX IF NOT EXISTS idx_lessons_subject  ON public.lessons(subject);
CREATE INDEX IF NOT EXISTS idx_lessons_published ON public.lessons(is_published);


-- ── 5. LESSON PAGES ───────────────────────────────────────────────────────────
-- One row per page of each lesson.
-- content_simplified  → used by dyslexia mode
-- image_description   → used by visual impairment mode
CREATE TABLE IF NOT EXISTS public.lesson_pages (
  id                   UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id            UUID    NOT NULL REFERENCES public.lessons(id) ON DELETE CASCADE,
  page_number          INTEGER NOT NULL,
  content_original     TEXT,
  content_simplified   TEXT,
  image_description    TEXT,

  UNIQUE (lesson_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_pages_lesson ON public.lesson_pages(lesson_id, page_number);


-- ── 6. LESSON AUDIO ───────────────────────────────────────────────────────────
-- One row per lesson per language. MP3 stored in lesson-audio bucket.
CREATE TABLE IF NOT EXISTS public.lesson_audio (
  id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id    UUID    NOT NULL REFERENCES public.lessons(id) ON DELETE CASCADE,
  language     TEXT    NOT NULL CHECK (language IN ('english','hausa','yoruba','igbo')),
  audio_url    TEXT    NOT NULL,
  duration_sec INTEGER,
  created_at   TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE (lesson_id, language)
);

CREATE INDEX IF NOT EXISTS idx_audio_lesson ON public.lesson_audio(lesson_id);


-- ── 7. LESSON ASSIGNMENTS ─────────────────────────────────────────────────────
-- Teacher assigns specific lessons to specific students.
-- Controls what appears on each student's dashboard.
CREATE TABLE IF NOT EXISTS public.lesson_assignments (
  id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id    UUID    NOT NULL REFERENCES public.lessons(id) ON DELETE CASCADE,
  student_id   UUID    NOT NULL REFERENCES public.users(id)   ON DELETE CASCADE,
  assigned_by  UUID    NOT NULL REFERENCES public.users(id),
  assigned_at  TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE (lesson_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_assignments_student ON public.lesson_assignments(student_id);
CREATE INDEX IF NOT EXISTS idx_assignments_lesson  ON public.lesson_assignments(lesson_id);


-- ── 8. STUDENT PROGRESS ───────────────────────────────────────────────────────
-- The most-read table. One row per student per lesson.
-- Updated on every page turn from the lesson reader.
CREATE TABLE IF NOT EXISTS public.student_progress (
  id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id          UUID    NOT NULL REFERENCES public.users(id)   ON DELETE CASCADE,
  lesson_id           UUID    NOT NULL REFERENCES public.lessons(id) ON DELETE CASCADE,

  current_page        INTEGER NOT NULL DEFAULT 1,
  is_completed        BOOLEAN NOT NULL DEFAULT false,
  completed_at        TIMESTAMPTZ,
  last_accessed_at    TIMESTAMPTZ DEFAULT NOW(),
  time_spent_seconds  INTEGER NOT NULL DEFAULT 0,

  UNIQUE (student_id, lesson_id)
);

CREATE INDEX IF NOT EXISTS idx_progress_student ON public.student_progress(student_id);
CREATE INDEX IF NOT EXISTS idx_progress_lesson  ON public.student_progress(lesson_id);
CREATE INDEX IF NOT EXISTS idx_progress_completed ON public.student_progress(is_completed);


-- ── 9. ACTIVITY LOG ───────────────────────────────────────────────────────────
-- Append-only event log. Drives the "Recent Activity" section.
CREATE TABLE IF NOT EXISTS public.activity_log (
  id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id   UUID    NOT NULL REFERENCES public.users(id)   ON DELETE CASCADE,
  lesson_id    UUID    NOT NULL REFERENCES public.lessons(id) ON DELETE CASCADE,
  action       TEXT    NOT NULL CHECK (action IN ('started','read_pages','completed')),
  pages_read   INTEGER,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Performance-critical index: students' dashboards fetch the latest 10 events
CREATE INDEX IF NOT EXISTS idx_activity_student_recent
  ON public.activity_log(student_id, created_at DESC);


-- ── 10. TEACHER NOTES ─────────────────────────────────────────────────────────
-- One note per teacher-student pair. Upserted (not appended) from student detail page.
CREATE TABLE IF NOT EXISTS public.teacher_notes (
  id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  teacher_id   UUID    NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  student_id   UUID    NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  note_text    TEXT    NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE (teacher_id, student_id)
);


-- ── 11. PROCESSING JOBS ───────────────────────────────────────────────────────
-- Tracks the AI pipeline for each uploaded lesson.
-- The upload wizard polls /teacher/processing/{lesson_id} which reads this table.
CREATE TABLE IF NOT EXISTS public.processing_jobs (
  id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id       UUID    NOT NULL UNIQUE REFERENCES public.lessons(id) ON DELETE CASCADE,
  status          TEXT    NOT NULL DEFAULT 'pending'
                  CHECK  (status IN ('pending','running','done','failed')),

  steps           JSONB   NOT NULL DEFAULT '{
    "extract_text":        false,
    "audio_english":       false,
    "audio_hausa":         false,
    "audio_yoruba":        false,
    "audio_igbo":          false,
    "simplify_dyslexia":   false,
    "image_descriptions":  false
  }'::jsonb,

  error_message   TEXT,
  started_at      TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
--  ROW LEVEL SECURITY
--  Enabled on all user-facing tables.
--  FastAPI uses SERVICE_ROLE key which bypasses RLS.
--  These policies protect direct Supabase client access.
-- ============================================================

ALTER TABLE public.users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_accessibility ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lessons              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lesson_pages         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lesson_audio         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lesson_assignments   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_progress     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.activity_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.teacher_notes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_jobs      ENABLE ROW LEVEL SECURITY;

-- Users: can only read/update their own row
CREATE POLICY "users_own_row_select" ON public.users
  FOR SELECT USING (id = auth.uid());

CREATE POLICY "users_own_row_update" ON public.users
  FOR UPDATE USING (id = auth.uid());

-- Accessibility: students manage only their own row
CREATE POLICY "accessibility_own_row" ON public.student_accessibility
  FOR ALL USING (user_id = auth.uid());

-- Lessons: students see only lessons assigned to them
CREATE POLICY "lessons_student_select" ON public.lessons
  FOR SELECT USING (
    id IN (
      SELECT lesson_id FROM public.lesson_assignments
      WHERE  student_id = auth.uid()
    )
    OR teacher_id = auth.uid()
  );

-- Lesson pages: same as lessons
CREATE POLICY "pages_via_lesson" ON public.lesson_pages
  FOR SELECT USING (
    lesson_id IN (
      SELECT lesson_id FROM public.lesson_assignments
      WHERE  student_id = auth.uid()
    )
    OR lesson_id IN (
      SELECT id FROM public.lessons WHERE teacher_id = auth.uid()
    )
  );

-- Audio: same rule
CREATE POLICY "audio_via_lesson" ON public.lesson_audio
  FOR SELECT USING (
    lesson_id IN (
      SELECT lesson_id FROM public.lesson_assignments
      WHERE  student_id = auth.uid()
    )
    OR lesson_id IN (
      SELECT id FROM public.lessons WHERE teacher_id = auth.uid()
    )
  );

-- Assignments: students see their own; teachers see their school's
CREATE POLICY "assignments_student" ON public.lesson_assignments
  FOR SELECT USING (student_id = auth.uid());

-- Progress: students see only their own
CREATE POLICY "progress_own" ON public.student_progress
  FOR ALL USING (student_id = auth.uid());

-- Activity log: own only
CREATE POLICY "activity_own" ON public.activity_log
  FOR ALL USING (student_id = auth.uid());

-- Teacher notes: teachers read/write their own notes
CREATE POLICY "notes_teacher" ON public.teacher_notes
  FOR ALL USING (teacher_id = auth.uid());

-- Processing jobs: teacher who owns the lesson
CREATE POLICY "jobs_teacher" ON public.processing_jobs
  FOR SELECT USING (
    lesson_id IN (
      SELECT id FROM public.lessons WHERE teacher_id = auth.uid()
    )
  );


-- ============================================================
--  STORAGE BUCKET POLICIES
--  Run these AFTER creating buckets in Supabase Dashboard.
--  Supabase Dashboard → Storage → [bucket] → Policies
-- ============================================================

-- lesson-audio (public): anyone with URL can read, only service role writes
-- (Bucket is already set to public in dashboard — no extra policy needed)

-- lesson-originals (private): only service role can read/write
-- (Service role bypasses all policies — no extra policy needed)

-- ============================================================
--  HELPFUL VIEWS (optional but useful in Supabase Table Editor)
-- ============================================================

CREATE OR REPLACE VIEW public.v_student_overview AS
  SELECT
    u.id,
    u.name,
    u.email,
    s.name          AS school_name,
    a.disability_profile,
    a.language,
    a.onboarding_complete,
    a.last_active_at,
    COUNT(DISTINCT la.lesson_id) AS assigned_lessons,
    COUNT(DISTINCT CASE WHEN sp.is_completed THEN sp.lesson_id END) AS completed_lessons
  FROM public.users u
  LEFT JOIN public.schools              s  ON s.id = u.school_id
  LEFT JOIN public.student_accessibility a ON a.user_id = u.id
  LEFT JOIN public.lesson_assignments   la ON la.student_id = u.id
  LEFT JOIN public.student_progress     sp ON sp.student_id = u.id
  WHERE u.role = 'student'
  GROUP BY u.id, u.name, u.email, s.name,
           a.disability_profile, a.language, a.onboarding_complete, a.last_active_at;


-- ============================================================
--  DONE ✓
--  Your Ncheta database is ready.
--  Next step: add your environment variables and deploy.
-- ============================================================
