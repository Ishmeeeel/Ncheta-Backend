"""
Teacher Router
===============
GET    /teacher/dashboard                — Stats + student list + top lessons
GET    /teacher/lessons                  — All uploaded lessons
POST   /teacher/lessons                  — Upload + trigger AI processing
PUT    /teacher/lessons/{id}             — Edit lesson title/subject/emoji
DELETE /teacher/lessons/{id}             — Delete lesson + Storage files
POST   /teacher/lessons/{id}/assign      — Assign lesson to students
GET    /teacher/students                 — All students in the teacher's school
POST   /teacher/students                 — Create a student account
GET    /teacher/students/{id}            — Student detail + lesson progress
PUT    /teacher/students/{id}/notes      — Save/update teacher note
GET    /teacher/processing/{lesson_id}   — Poll AI processing status
"""
import uuid
import secrets
import string
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks, status
from app.database import admin_client
from app.deps import TeacherUser
from app.schemas.models import (
    TeacherDashboardResponse, TeacherStats, ProfileBreakdown, StudentSummary,
    LessonSummary, CreateStudentRequest, CreateStudentResponse,
    StudentDetailResponse, SaveNotesRequest, AssignLessonsRequest,
    ProcessingStatusResponse, ProcessingStep, MessageResponse,
)
from app.processing.pipeline import run_pipeline

router = APIRouter(prefix="/teacher", tags=["teacher"])

PROFILE_META = {
    "visual":   {"emoji": "👁️", "color": "#F59E0B", "label": "Visual"},
    "hearing":  {"emoji": "👂", "color": "#6366F1", "label": "Hearing"},
    "dyslexia": {"emoji": "🧠", "color": "#10B981", "label": "Dyslexia"},
    "motor":    {"emoji": "🖐️", "color": "#EF4444", "label": "Motor"},
}

ALLOWED_TYPES = {
    "application/pdf":      "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}


def _time_ago(dt_str: str | None) -> str:
    if not dt_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 3600:  return f"{diff // 60}m ago"
        if diff < 86400: return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return "Recently"


def _make_temp_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _build_student_summary(user: dict, accessibility: dict | None, progress_rows: list) -> StudentSummary:
    total_lessons = len(progress_rows)
    overall = (
        round(sum(p.get("current_page", 0) / max(1, p.get("page_count", 1)) * 100 for p in progress_rows) / total_lessons)
        if total_lessons else 0
    )
    last_active = max(
        (p.get("last_accessed_at", "") for p in progress_rows),
        default=None,
    )
    return StudentSummary(
        id=user["id"],
        name=user["name"],
        profile=accessibility.get("disability_profile", "visual") if accessibility else "visual",
        language=accessibility.get("language", "english") if accessibility else "english",
        lessons=total_lessons,
        progress=min(100, overall),
        last_active=_time_ago(last_active) if last_active else "Never",
        status="active" if user.get("is_active", True) else "inactive",
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=TeacherDashboardResponse)
async def teacher_dashboard(current_user: TeacherUser):
    school_id = current_user.get("school_id")
    teacher_id = current_user["id"]

    # Students in school
    students_result = (
        admin_client.table("users")
        .select("*")
        .eq("school_id", school_id)
        .eq("role", "student")
        .execute()
    )
    students = students_result.data or []
    student_ids = [s["id"] for s in students]

    # Accessibility for each student
    acc_result = (
        admin_client.table("student_accessibility")
        .select("*")
        .in_("user_id", student_ids)
        .execute()
    ) if student_ids else type("R", (), {"data": []})()
    acc_map = {a["user_id"]: a for a in (acc_result.data or [])}

    # Teacher's lessons
    lessons_result = (
        admin_client.table("lessons")
        .select("*, users(name)")
        .eq("teacher_id", teacher_id)
        .order("created_at", desc=True)
        .execute()
    )
    lessons = lessons_result.data or []

    # Total completions across all lessons
    completions_result = (
        admin_client.table("student_progress")
        .select("id")
        .in_("lesson_id", [l["id"] for l in lessons])
        .eq("is_completed", True)
        .execute()
    ) if lessons else type("R", (), {"data": []})()
    completions = len(completions_result.data or [])

    # Need attention: students who haven't opened any lesson in 7+ days
    need_attention = 0  # Simplified — would do date comparison in production

    stats = TeacherStats(
        total_students=len(students),
        total_lessons=len(lessons),
        completions=completions,
        need_attention=need_attention,
    )

    # Profile breakdown
    profile_breakdown = []
    for pid, meta in PROFILE_META.items():
        count = sum(1 for s in students if acc_map.get(s["id"], {}).get("disability_profile") == pid)
        profile_breakdown.append(ProfileBreakdown(
            profile=pid,
            emoji=meta["emoji"],
            color=meta["color"],
            count=count,
        ))

    # Recent students (first 5)
    recent_students = []
    for s in students[:5]:
        acc = acc_map.get(s["id"])
        recent_students.append(_build_student_summary(s, acc, []))

    # Top lessons (first 4)
    top_lessons = []
    for l in lessons[:4]:
        top_lessons.append(LessonSummary(
            id=l["id"],
            title=l["title"],
            subject=l["subject"],
            page_count=l.get("page_count") or 0,
            icon_emoji=l.get("icon_emoji", "📄"),
            teacher_name=current_user["name"],
            is_published=l.get("is_published", False),
            processing_status=l.get("processing_status", "done"),
        ))

    return TeacherDashboardResponse(
        stats=stats,
        recent_students=recent_students,
        top_lessons=top_lessons,
        profile_breakdown=profile_breakdown,
    )


# ── Lessons ───────────────────────────────────────────────────────────────────

@router.get("/lessons", response_model=list[LessonSummary])
async def teacher_lessons(current_user: TeacherUser):
    result = (
        admin_client.table("lessons")
        .select("*")
        .eq("teacher_id", current_user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    summaries = []
    for l in (result.data or []):
        summaries.append(LessonSummary(
            id=l["id"],
            title=l["title"],
            subject=l["subject"],
            page_count=l.get("page_count") or 0,
            icon_emoji=l.get("icon_emoji", "📄"),
            teacher_name=current_user["name"],
            is_published=l.get("is_published", False),
            processing_status=l.get("processing_status", "pending"),
        ))
    return summaries


@router.post("/lessons", status_code=status.HTTP_201_CREATED)
async def upload_lesson(
    background_tasks: BackgroundTasks,
    current_user: TeacherUser,
    file:       UploadFile = File(...),
    title:      str        = Form(...),
    subject:    str        = Form(...),
    icon_emoji: str        = Form(default="📄"),
    assign_to:  str        = Form(default=""),  # comma-separated student UUIDs
):
    """
    Upload a lesson file and trigger the AI processing pipeline.
    Returns immediately with lesson_id — client polls /teacher/processing/{lesson_id}.
    """
    # Validate file type
    content_type = file.content_type or ""
    file_type = ALLOWED_TYPES.get(content_type)
    if not file_type:
        ext = (file.filename or "").split(".")[-1].lower()
        type_map = {"pdf": "pdf", "docx": "docx", "doc": "docx", "pptx": "pptx", "ppt": "pptx"}
        file_type = type_map.get(ext)
        if not file_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file type. Please upload PDF, DOCX, or PPTX.",
            )

    file_bytes  = await file.read()
    school_id   = current_user.get("school_id", "default")
    lesson_id   = str(uuid.uuid4())
    job_id      = str(uuid.uuid4())
    storage_key = f"{school_id}/{lesson_id}/original.{file_type}"

    # Upload original file to private bucket
    admin_client.storage.from_("lesson-originals").upload(
        path=storage_key,
        file=file_bytes,
        file_options={"content-type": content_type or "application/octet-stream"},
    )

    # Insert lesson row
    admin_client.table("lessons").insert({
        "id":                 lesson_id,
        "title":              title,
        "subject":            subject,
        "teacher_id":         current_user["id"],
        "school_id":          school_id,
        "original_file_path": storage_key,
        "original_file_name": file.filename,
        "file_type":          file_type,
        "icon_emoji":         icon_emoji,
        "processing_status":  "pending",
        "is_published":       False,
    }).execute()

    # Insert processing job row
    admin_client.table("processing_jobs").insert({
        "id":        job_id,
        "lesson_id": lesson_id,
        "status":    "pending",
    }).execute()

    # Assign lesson to students
    if assign_to.strip():
        student_ids = [s.strip() for s in assign_to.split(",") if s.strip()]
        assignments = [
            {"lesson_id": lesson_id, "student_id": sid, "assigned_by": current_user["id"]}
            for sid in student_ids
        ]
        if assignments:
            admin_client.table("lesson_assignments").upsert(assignments).execute()

    # Launch AI pipeline as background task
    background_tasks.add_task(
        asyncio.run,
        run_pipeline(lesson_id, job_id, file_bytes, file_type, school_id),
    )

    return {"lesson_id": lesson_id, "job_id": job_id, "message": "Processing started."}


@router.delete("/lessons/{lesson_id}", response_model=MessageResponse)
async def delete_lesson(lesson_id: str, current_user: TeacherUser):
    """Delete lesson, its pages, audio, and Storage files."""
    lesson = (
        admin_client.table("lessons")
        .select("id, teacher_id, school_id, file_type")
        .eq("id", lesson_id)
        .eq("teacher_id", current_user["id"])
        .maybe_single()
        .execute()
    )
    if not lesson.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

    school_id = lesson.data["school_id"]
    ft        = lesson.data["file_type"]

    # Delete Storage files
    try:
        admin_client.storage.from_("lesson-originals").remove([f"{school_id}/{lesson_id}/original.{ft}"])
        for lang in ["english", "hausa", "yoruba", "igbo"]:
            admin_client.storage.from_("lesson-audio").remove([f"{school_id}/{lesson_id}/{lang}.mp3"])
    except Exception:
        pass  # Don't block DB deletion if Storage fails

    # Cascade deletes via FK constraints in DB
    admin_client.table("lessons").delete().eq("id", lesson_id).execute()
    return {"message": "Lesson deleted successfully."}


@router.post("/lessons/{lesson_id}/assign", response_model=MessageResponse)
async def assign_lesson(lesson_id: str, body: AssignLessonsRequest, current_user: TeacherUser):
    """Assign a lesson to a list of students."""
    assignments = [
        {"lesson_id": lesson_id, "student_id": sid, "assigned_by": current_user["id"]}
        for sid in body.student_ids
    ]
    admin_client.table("lesson_assignments").upsert(assignments).execute()
    return {"message": f"Lesson assigned to {len(body.student_ids)} students."}


# ── Students ──────────────────────────────────────────────────────────────────

@router.get("/students", response_model=list[StudentSummary])
async def teacher_students(current_user: TeacherUser):
    school_id = current_user.get("school_id")
    students_result = (
        admin_client.table("users")
        .select("*")
        .eq("school_id", school_id)
        .eq("role", "student")
        .execute()
    )
    students = students_result.data or []
    if not students:
        return []

    student_ids = [s["id"] for s in students]
    acc_result = (
        admin_client.table("student_accessibility")
        .select("*")
        .in_("user_id", student_ids)
        .execute()
    )
    acc_map = {a["user_id"]: a for a in (acc_result.data or [])}

    summaries = []
    for s in students:
        acc = acc_map.get(s["id"])
        summaries.append(_build_student_summary(s, acc, []))
    return summaries


@router.post("/students", response_model=CreateStudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(body: CreateStudentRequest, current_user: TeacherUser):
    """
    Create a student account. Teacher provides name, email, profile, language.
    Returns the student + a temporary password for first login.
    """
    school_id     = current_user.get("school_id")
    temp_password = _make_temp_password()

    # Create Supabase auth user
    try:
        auth_response = admin_client.auth.admin.create_user({
            "email":         body.email,
            "password":      temp_password,
            "email_confirm": True,
        })
    except Exception as e:
        if "already" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    auth_user_id = auth_response.user.id

    # Insert public.users
    admin_client.table("users").insert({
        "id":        auth_user_id,
        "name":      body.name,
        "email":     body.email,
        "role":      "student",
        "school_id": school_id,
    }).execute()

    # Pre-populate accessibility with teacher's choices
    admin_client.table("student_accessibility").insert({
        "user_id":             auth_user_id,
        "disability_profile":  body.profile,
        "language":            body.language,
        "onboarding_complete": False,
    }).execute()

    student = StudentSummary(
        id=auth_user_id,
        name=body.name,
        profile=body.profile,
        language=body.language,
        lessons=0,
        progress=0,
        last_active="Never",
        status="active",
    )
    return CreateStudentResponse(student=student, temp_password=temp_password)


@router.get("/students/{student_id}", response_model=StudentDetailResponse)
async def get_student(student_id: str, current_user: TeacherUser):
    """Student detail — full lesson progress + accessibility + teacher notes."""
    school_id = current_user.get("school_id")

    # Verify student belongs to this school
    student_result = (
        admin_client.table("users")
        .select("*")
        .eq("id", student_id)
        .eq("school_id", school_id)
        .eq("role", "student")
        .maybe_single()
        .execute()
    )
    if not student_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    student_row = student_result.data

    # Accessibility
    acc_result = (
        admin_client.table("student_accessibility")
        .select("*")
        .eq("user_id", student_id)
        .maybe_single()
        .execute()
    )
    acc = acc_result.data or {}

    # All assigned lessons with progress
    assignments = (
        admin_client.table("lesson_assignments")
        .select("lesson_id")
        .eq("student_id", student_id)
        .execute()
    )
    lesson_ids = [a["lesson_id"] for a in (assignments.data or [])]

    lesson_summaries = []
    if lesson_ids:
        lessons = (
            admin_client.table("lessons")
            .select("*")
            .in_("id", lesson_ids)
            .execute()
        )
        progress_result = (
            admin_client.table("student_progress")
            .select("*")
            .eq("student_id", student_id)
            .in_("lesson_id", lesson_ids)
            .execute()
        )
        progress_map = {p["lesson_id"]: p for p in (progress_result.data or [])}

        for l in (lessons.data or []):
            p = progress_map.get(l["id"])
            page_count   = l.get("page_count") or 1
            current_page = p["current_page"] if p else 0
            is_completed = p["is_completed"] if p else False
            pct          = 100 if is_completed else round((current_page / page_count) * 100)
            lesson_summaries.append(LessonSummary(
                id=l["id"],
                title=l["title"],
                subject=l["subject"],
                page_count=page_count,
                icon_emoji=l.get("icon_emoji", "📄"),
                teacher_name=current_user["name"],
                is_published=l.get("is_published", False),
                processing_status=l.get("processing_status", "done"),
                progress_percent=pct,
                current_page=current_page,
                is_completed=is_completed,
            ))

    # Teacher notes
    notes_result = (
        admin_client.table("teacher_notes")
        .select("note_text")
        .eq("teacher_id", current_user["id"])
        .eq("student_id", student_id)
        .maybe_single()
        .execute()
    )
    notes_text = notes_result.data["note_text"] if notes_result.data else None

    student_summary = _build_student_summary(student_row, acc, [])

    return StudentDetailResponse(
        student=student_summary,
        lessons=lesson_summaries,
        accessibility={
            "profile":        acc.get("disability_profile", "visual"),
            "language":       acc.get("language", "english"),
            "font_size":      acc.get("font_size", "large"),
            "voice_speed":    acc.get("voice_speed", "normal"),
            "high_contrast":  acc.get("high_contrast", True),
        },
        notes=notes_text,
    )


@router.put("/students/{student_id}/notes", response_model=MessageResponse)
async def save_notes(student_id: str, body: SaveNotesRequest, current_user: TeacherUser):
    """Save or update teacher's note for a student."""
    admin_client.table("teacher_notes").upsert({
        "teacher_id":  current_user["id"],
        "student_id":  student_id,
        "note_text":   body.note_text,
        "updated_at":  "now()",
    }).execute()
    return {"message": "Notes saved."}


# ── Processing poll ───────────────────────────────────────────────────────────

@router.get("/processing/{lesson_id}", response_model=ProcessingStatusResponse)
async def get_processing_status(lesson_id: str, current_user: TeacherUser):
    """
    Poll endpoint called by the upload wizard Step 3.
    Returns current processing status and which steps are done.
    """
    result = (
        admin_client.table("processing_jobs")
        .select("*")
        .eq("lesson_id", lesson_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found.")

    job   = result.data
    steps = job.get("steps") or {}

    return ProcessingStatusResponse(
        status=job["status"],
        steps=ProcessingStep(**steps),
        error_message=job.get("error_message"),
    )
