from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, field_validator


# ─── Auth ─────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:        str
    email:       EmailStr
    password:    str
    role:        Literal["teacher", "admin"]
    school_code: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class OnboardingRequest(BaseModel):
    guide_type:         Literal["teacher", "family", "self"]
    disability_profile: Literal["visual", "hearing", "dyslexia", "motor"]
    language:           Literal["english", "hausa", "yoruba", "igbo"]


class SettingsRequest(BaseModel):
    profile:      Optional[Literal["visual", "hearing", "dyslexia", "motor"]] = None
    language:     Optional[Literal["english", "hausa", "yoruba", "igbo"]] = None
    font_size:    Optional[Literal["small", "medium", "large", "extra-large"]] = None
    voice_speed:  Optional[Literal["slow", "normal", "fast"]] = None
    high_contrast: Optional[bool] = None


class UserResponse(BaseModel):
    id:                  str
    name:                str
    email:               str
    role:                str
    school_id:           Optional[str] = None
    disability_profile:  Optional[str] = None
    language:            Optional[str] = None
    font_size:           str = "large"
    voice_speed:         str = "normal"
    high_contrast:       bool = True
    onboarding_complete: bool = False


class RegisterResponse(BaseModel):
    user: UserResponse


# ─── Shared lesson summary (student views) ────────────────────────────────

class LessonSummary(BaseModel):
    id:              str
    title:           str
    subject:         str
    page_count:      int
    icon_emoji:      str
    teacher_name:    str
    progress_percent: int = 0
    current_page:    int = 1
    is_completed:    bool = False


# ─── Student ──────────────────────────────────────────────────────────────

class SubjectBreakdown(BaseModel):
    subject: str
    done:    int
    total:   int


class DashboardStats(BaseModel):
    total_lessons:    int
    completed:        int
    in_progress:      int
    overall_progress: int   # 0-100 average across all assigned lessons


class StudentDashboard(BaseModel):
    stats:             DashboardStats
    recent_lessons:    list[LessonSummary]
    available_lessons: list[LessonSummary]
    subject_breakdown: list[SubjectBreakdown]


class PageContent(BaseModel):
    page_number:        int
    content_original:   Optional[str] = None
    content_simplified: Optional[str] = None
    image_description:  Optional[str] = None


class AudioResponse(BaseModel):
    audio_url: Optional[str] = None
    language:  str


class ProgressUpdateRequest(BaseModel):
    current_page: int
    is_completed: bool = False


class ActivityItem(BaseModel):
    action:     str
    lesson_title: str
    created_at: str


class StudentProgressPage(BaseModel):
    stats:             DashboardStats
    completed_lessons: list[LessonSummary]
    inprogress_lessons: list[LessonSummary]
    subject_breakdown: list[SubjectBreakdown]
    activity_log:      list[ActivityItem]


# ─── Teacher ──────────────────────────────────────────────────────────────

class StudentSummary(BaseModel):
    id:         str
    name:       str
    profile:    str
    lessons:    int
    progress:   int
    last_active: str
    status:     str


class TeacherLesson(BaseModel):
    id:               str
    title:            str
    subject:          str
    page_count:       int
    icon_emoji:       str
    is_published:     bool
    processing_status: str
    student_count:    int
    created_at:       str


class ProcessingSteps(BaseModel):
    extract_text:       bool = False
    audio_english:      bool = False
    audio_hausa:        bool = False
    audio_yoruba:       bool = False
    audio_igbo:         bool = False
    simplify_dyslexia:  bool = False
    image_descriptions: bool = False


class ProcessingStatus(BaseModel):
    lesson_id:     str
    status:        str
    steps:         ProcessingSteps
    error_message: Optional[str] = None


class UploadResponse(BaseModel):
    lesson_id: str
    message:   str = "Upload received. Processing started."


class CreateStudentRequest(BaseModel):
    name:               str
    email:              EmailStr
    disability_profile: Literal["visual", "hearing", "dyslexia", "motor"]
    language:           Literal["english", "hausa", "yoruba", "igbo"]


class CreateStudentResponse(BaseModel):
    student: StudentSummary
    temp_password: str


class StudentDetail(BaseModel):
    id:          str
    name:        str
    profile:     str
    language:    str
    progress:    int
    lessons:     int
    status:      str
    last_active: str
    lesson_progress: list[LessonSummary]
    font_size:   str
    voice_speed: str
    high_contrast: bool


class TeacherNoteRequest(BaseModel):
    note_text: str


class AssignRequest(BaseModel):
    student_ids: list[str]


class TeacherDashboard(BaseModel):
    stats: dict                       # total_students, total_lessons, completions, need_attention
    recent_students: list[StudentSummary]
    profile_breakdown: list[dict]     # {"profile": "visual", "count": 3}
    top_lessons: list[TeacherLesson]


# ─── Admin ────────────────────────────────────────────────────────────────

class SchoolSummary(BaseModel):
    id:          str
    name:        str
    location:    str
    access_code: str
    students:    int
    teachers:    int
    is_active:   bool


class AdminDashboard(BaseModel):
    stats: dict                       # total_schools, total_students, total_teachers, total_lessons
    schools: list[SchoolSummary]
    profile_breakdown: list[dict]
