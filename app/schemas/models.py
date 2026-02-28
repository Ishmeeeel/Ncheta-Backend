from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# ─── Shared ───────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


# ─── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str           # "teacher" | "admin"
    school_code: str    # Must match a school's access_code


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OnboardingRequest(BaseModel):
    profile: str        # "visual" | "hearing" | "dyslexia" | "motor"
    language: str       # "english" | "hausa" | "yoruba" | "igbo"
    guide_type: Optional[str] = None   # "teacher" | "family" | "self"


class SettingsUpdateRequest(BaseModel):
    profile:       Optional[str] = None
    language:      Optional[str] = None
    font_size:     Optional[str] = None    # "small"|"medium"|"large"|"extra-large"
    voice_speed:   Optional[str] = None    # "slow"|"normal"|"fast"
    high_contrast: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    school_id: Optional[str] = None
    onboarding_complete: bool = False
    profile:  Optional[str] = None
    language: Optional[str] = None


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    token_type: str = "bearer"


# ─── Lessons ──────────────────────────────────────────────────────────────────

class LessonSummary(BaseModel):
    id: str
    title: str
    subject: str
    page_count: int
    icon_emoji: str
    teacher_name: str
    is_published: bool
    processing_status: str
    # Progress fields (null for teacher view)
    progress_percent: Optional[int] = None
    current_page:     Optional[int] = None
    is_completed:     Optional[bool] = None


class LessonDetail(BaseModel):
    id: str
    title: str
    subject: str
    page_count: int
    icon_emoji: str
    teacher_name: str
    current_page: int
    progress_percent: int
    is_completed: bool
    # Audio URL for the user's language (null if not generated yet)
    audio_url: Optional[str] = None


class PageContent(BaseModel):
    page_number: int
    content_original:   Optional[str] = None
    content_simplified: Optional[str] = None
    image_description:  Optional[str] = None


class ProgressUpdateRequest(BaseModel):
    current_page: int


class ProgressUpdateResponse(BaseModel):
    progress_percent: int
    is_completed: bool


# ─── Student Dashboard ────────────────────────────────────────────────────────

class StudentStats(BaseModel):
    total_lessons:    int
    completed:        int
    in_progress:      int
    overall_progress: int   # 0-100


class SubjectBreakdown(BaseModel):
    subject: str
    done:    int
    total:   int


class ActivityEntry(BaseModel):
    action:     str     # "started" | "read_pages" | "completed"
    lesson:     str
    time:       str     # human-readable e.g. "2h ago"


class StudentDashboardResponse(BaseModel):
    stats:             StudentStats
    recent_lessons:    List[LessonSummary]
    available_lessons: List[LessonSummary]
    subject_breakdown: List[SubjectBreakdown]


class StudentProgressResponse(BaseModel):
    stats:             StudentStats
    completed:         List[LessonSummary]
    in_progress:       List[LessonSummary]
    subject_breakdown: List[SubjectBreakdown]
    activity:          List[ActivityEntry]


# ─── Teacher ──────────────────────────────────────────────────────────────────

class StudentSummary(BaseModel):
    id: str
    name: str
    profile:     str
    language:    str
    lessons:     int
    progress:    int    # 0-100 overall
    last_active: Optional[str] = None
    status:      str    # "active" | "inactive"


class CreateStudentRequest(BaseModel):
    name:     str
    email:    EmailStr
    profile:  str
    language: str


class CreateStudentResponse(BaseModel):
    student:       StudentSummary
    temp_password: str   # One-time password for first login


class TeacherStats(BaseModel):
    total_students:  int
    total_lessons:   int
    completions:     int
    need_attention:  int   # Students with progress < 30%


class ProfileBreakdown(BaseModel):
    profile: str
    emoji:   str
    color:   str
    count:   int


class TeacherDashboardResponse(BaseModel):
    stats:             TeacherStats
    recent_students:   List[StudentSummary]
    top_lessons:       List[LessonSummary]
    profile_breakdown: List[ProfileBreakdown]


class StudentDetailResponse(BaseModel):
    student:        StudentSummary
    lessons:        List[LessonSummary]
    accessibility:  dict
    notes:          Optional[str] = None


class SaveNotesRequest(BaseModel):
    note_text: str


class AssignLessonsRequest(BaseModel):
    student_ids: List[str]


# ─── Processing ───────────────────────────────────────────────────────────────

class ProcessingStep(BaseModel):
    extract_text:      bool = False
    audio_english:     bool = False
    audio_hausa:       bool = False
    audio_yoruba:      bool = False
    audio_igbo:        bool = False
    simplify_dyslexia: bool = False
    image_descriptions: bool = False


class ProcessingStatusResponse(BaseModel):
    status:        str             # "pending"|"running"|"done"|"failed"
    steps:         ProcessingStep
    error_message: Optional[str] = None


# ─── Admin ────────────────────────────────────────────────────────────────────

class SchoolSummary(BaseModel):
    id:          str
    name:        str
    location:    str
    access_code: str
    students:    int
    teachers:    int
    is_active:   bool


class PlatformStats(BaseModel):
    total_schools:  int
    total_students: int
    total_teachers: int
    total_lessons:  int


class AdminDashboardResponse(BaseModel):
    stats:             PlatformStats
    schools:           List[SchoolSummary]
    profile_breakdown: List[ProfileBreakdown]


class CreateSchoolRequest(BaseModel):
    name:     str
    location: str


class CreateSchoolResponse(BaseModel):
    school:      SchoolSummary
    access_code: str
