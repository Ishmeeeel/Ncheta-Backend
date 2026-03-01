"""
Teacher router
--------------
GET  /teacher/dashboard
GET  /teacher/lessons
POST /teacher/lessons          (multipart upload)
DELETE /teacher/lessons/{id}
POST /teacher/lessons/{id}/assign
GET  /teacher/processing/{id}  (poll processing status)
GET  /teacher/students
POST /teacher/students
GET  /teacher/students/{id}
PUT  /teacher/students/{id}/notes
"""
import secrets
import string
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Path, UploadFile

from core.deps import require_teacher
from core.supabase_client import get_service_client
from models.schemas import (
    AssignRequest, CreateStudentRequest, CreateStudentResponse,
    ProcessingStatus, ProcessingSteps, StudentDetail,
    StudentSummary, TeacherDashboard, TeacherLesson,
    TeacherNoteRequest, UploadResponse, LessonSummary,
)
from services.processor import process_lesson_pipeline

router = APIRouter(prefix="/teacher", tags=["teacher"])


# ── Helpers ──────────────────────────────────────────────────────────────

def _relative_time(dt_str: str | None) -> str:
    if not dt_str:
        return "Never"
    try:
        dt   = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        diff = datetime.now(dt.tzinfo) - dt
        secs = int(diff.total_seconds())
        if secs < 3600:  return f"{secs // 60}m ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return "Recently"


def _build_teacher_lesson(row: dict, student_count: int) -> TeacherLesson:
    return TeacherLesson(
        id                = row["id"],
        title             = row["title"],
        subject           = row["subject"],
        page_count        = row.get("page_count") or 0,
        icon_emoji        = row.get("icon_emoji") or "📄",
        is_published      = row.get("is_published", False),
        processing_status = row.get("processing_status", "pending"),
        student_count     = student_count,
        created_at        = row.get("created_at", ""),
    )


def _gen_temp_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _unwrap_acc(s: dict) -> dict:
    """
    Supabase returns related rows as a list even when there is only one row.
    This helper safely unwraps student_accessibility into a plain dict
    so we can call .get() on it without crashing.
    """
    acc = s.get("student_accessibility") or {}
    if isinstance(acc, list):
        acc = acc[0] if acc else {}
    return acc


# ── GET /teacher/dashboard ────────────────────────────────────────────────

@router.get("/dashboard", response_model=TeacherDashboard)
async def teacher_dashboard(teacher: Annotated[dict, Depends(require_teacher)]):
    sb        = get_service_client()
    tid       = teacher["id"]
    school_id = teacher.get("school_id")

    if not school_id:
        raise HTTPException(400, "Teacher is not associated with a school")

    # All students in the school
    students_resp = (
        sb.table("users")
        .select("id, name, is_active, student_accessibility(disability_profile,language,last_active_at)")
        .eq("school_id", school_id)
        .eq("role", "student")
        .execute()
    ).data or []

    # All lessons by this teacher
    lessons_resp = (
        sb.table("lessons")
        .select("id, title, subject, page_count, icon_emoji, is_published, processing_status, created_at")
        .eq("teacher_id", tid)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    lesson_ids = [l["id"] for l in lessons_resp]

    # Assignment counts per lesson
    assign_resp = (
        sb.table("lesson_assignments")
        .select("lesson_id")
        .in_("lesson_id", lesson_ids)
        .execute()
    ).data or [] if lesson_ids else []
    assign_count: dict[str, int] = {}
    for a in assign_resp:
        lid = a["lesson_id"]
        assign_count[lid] = assign_count.get(lid, 0) + 1

    # Progress rows to compute completions
    all_progress = (
        sb.table("student_progress")
        .select("is_completed, lesson_id")
        .in_("lesson_id", lesson_ids)
        .execute()
    ).data or [] if lesson_ids else []

    total_completions = sum(1 for p in all_progress if p["is_completed"])

    # Students who have never been active need attention
    # Uses _unwrap_acc to safely handle Supabase returning a list
    need_attention = sum(
        1 for s in students_resp
        if not _unwrap_acc(s).get("last_active_at")
    )

    # Recent students list
    recent_students: list[StudentSummary] = []
    for s in students_resp[:10]:
        acc = _unwrap_acc(s)
        recent_students.append(StudentSummary(
            id          = s["id"],
            name        = s["name"],
            profile     = acc.get("disability_profile", "visual"),
            lessons     = 0,
            progress    = 0,
            last_active = _relative_time(acc.get("last_active_at")),
            status      = "active" if s.get("is_active") else "inactive",
        ))

    # Profile breakdown
    profile_counts: dict[str, int] = {}
    for s in students_resp:
        acc     = _unwrap_acc(s)
        profile = acc.get("disability_profile", "visual")
        profile_counts[profile] = profile_counts.get(profile, 0) + 1
    profile_breakdown = [{"profile": k, "count": v} for k, v in profile_counts.items()]

    top_lessons = [_build_teacher_lesson(l, assign_count.get(l["id"], 0)) for l in lessons_resp[:4]]

    return TeacherDashboard(
        stats={
            "total_students": len(students_resp),
            "total_lessons":  len(lessons_resp),
            "completions":    total_completions,
            "need_attention": need_attention,
        },
        recent_students   = recent_students,
        profile_breakdown = profile_breakdown,
        top_lessons       = top_lessons,
    )


# ── GET /teacher/lessons ──────────────────────────────────────────────────

@router.get("/lessons", response_model=list[TeacherLesson])
async def teacher_lessons(teacher: Annotated[dict, Depends(require_teacher)]):
    sb  = get_service_client()
    tid = teacher["id"]

    lessons = (
        sb.table("lessons")
        .select("*")
        .eq("teacher_id", tid)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    lesson_ids = [l["id"] for l in lessons]
    if not lesson_ids:
        return []

    assign_resp = (
        sb.table("lesson_assignments")
        .select("lesson_id")
        .in_("lesson_id", lesson_ids)
        .execute()
    ).data or []
    assign_count: dict[str, int] = {}
    for a in assign_resp:
        lid = a["lesson_id"]
        assign_count[lid] = assign_count.get(lid, 0) + 1

    return [_build_teacher_lesson(l, assign_count.get(l["id"], 0)) for l in lessons]


# ── POST /teacher/lessons (upload) ────────────────────────────────────────

@router.post("/lessons", response_model=UploadResponse, status_code=202)
async def upload_lesson(
    background_tasks: BackgroundTasks,
    teacher:   Annotated[dict, Depends(require_teacher)],
    file:      UploadFile = File(...),
    title:     str        = Form(...),
    subject:   str        = Form(...),
    assign_to: str        = Form(""),   # comma-separated student UUIDs
):
    sb        = get_service_client()
    tid       = teacher["id"]
    school_id = teacher.get("school_id")

    if not school_id:
        raise HTTPException(400, "Teacher must belong to a school")

    # Validate file type
    fname = file.filename or "upload"
    ext   = fname.rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "docx", "pptx"):
        raise HTTPException(400, "Only PDF, DOCX, and PPTX files are supported")

    # Read file bytes
    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:   # 50 MB limit
        raise HTTPException(413, "File too large. Maximum size is 50 MB")

    # Upload to Supabase Storage (lesson-originals bucket)
    from services.storage import upload_original_file
    storage_path = upload_original_file(file_bytes, fname, tid)

    # Create lesson row
    lesson_row = (
        sb.table("lessons")
        .insert({
            "title":              title,
            "subject":            subject,
            "teacher_id":         tid,
            "school_id":          school_id,
            "original_file_path": storage_path,
            "original_file_name": fname,
            "file_type":          ext,
            "processing_status":  "pending",
        })
        .execute()
    ).data[0]
    lesson_id = lesson_row["id"]

    # Create processing_jobs row
    sb.table("processing_jobs").insert({"lesson_id": lesson_id}).execute()

    # Assign to requested students
    student_ids = [s.strip() for s in assign_to.split(",") if s.strip()]
    if student_ids:
        sb.table("lesson_assignments").insert(
            [{"lesson_id": lesson_id, "student_id": sid, "assigned_by": tid} for sid in student_ids]
        ).execute()

    # Kick off background processing
    background_tasks.add_task(
        process_lesson_pipeline,
        lesson_id  = lesson_id,
        file_bytes = file_bytes,
        file_type  = ext,
    )

    return UploadResponse(lesson_id=lesson_id)


# ── DELETE /teacher/lessons/{id} ──────────────────────────────────────────

@router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson(
    lesson_id: Annotated[str, Path()],
    teacher:   Annotated[dict, Depends(require_teacher)],
):
    sb  = get_service_client()
    tid = teacher["id"]

    existing = (
        sb.table("lessons")
        .select("id, teacher_id")
        .eq("id", lesson_id)
        .single()
        .execute()
    ).data
    if not existing:
        raise HTTPException(404, "Lesson not found")
    if existing["teacher_id"] != tid:
        raise HTTPException(403, "You can only delete your own lessons")

    sb.table("lessons").delete().eq("id", lesson_id).execute()


# ── POST /teacher/lessons/{id}/assign ────────────────────────────────────

@router.post("/lessons/{lesson_id}/assign")
async def assign_lesson(
    lesson_id: Annotated[str, Path()],
    body:      AssignRequest,
    teacher:   Annotated[dict, Depends(require_teacher)],
):
    sb  = get_service_client()
    tid = teacher["id"]

    rows = [
        {"lesson_id": lesson_id, "student_id": sid, "assigned_by": tid}
        for sid in body.student_ids
    ]
    sb.table("lesson_assignments").upsert(rows, on_conflict="lesson_id,student_id").execute()
    return {"ok": True, "assigned": len(rows)}


# ── GET /teacher/processing/{id} (poll) ──────────────────────────────────

@router.get("/processing/{lesson_id}", response_model=ProcessingStatus)
async def poll_processing(
    lesson_id: Annotated[str, Path()],
    teacher:   Annotated[dict, Depends(require_teacher)],
):
    sb = get_service_client()

    job = (
        sb.table("processing_jobs")
        .select("*")
        .eq("lesson_id", lesson_id)
        .single()
        .execute()
    ).data

    if not job:
        raise HTTPException(404, "Processing job not found")

    raw_steps = job.get("steps") or {}
    return ProcessingStatus(
        lesson_id     = lesson_id,
        status        = job["status"],
        steps         = ProcessingSteps(**raw_steps),
        error_message = job.get("error_message"),
    )


# ── GET /teacher/students ─────────────────────────────────────────────────

@router.get("/students", response_model=list[StudentSummary])
async def teacher_students(teacher: Annotated[dict, Depends(require_teacher)]):
    sb        = get_service_client()
    school_id = teacher.get("school_id")
    if not school_id:
        return []

    students = (
        sb.table("users")
        .select("id, name, is_active, student_accessibility(disability_profile,last_active_at)")
        .eq("school_id", school_id)
        .eq("role", "student")
        .execute()
    ).data or []

    result = []
    for s in students:
        acc = _unwrap_acc(s)
        result.append(StudentSummary(
            id          = s["id"],
            name        = s["name"],
            profile     = acc.get("disability_profile", "visual"),
            lessons     = 0,
            progress    = 0,
            last_active = _relative_time(acc.get("last_active_at")),
            status      = "active" if s.get("is_active") else "inactive",
        ))
    return result


# ── POST /teacher/students (create student) ───────────────────────────────

@router.post("/students", response_model=CreateStudentResponse, status_code=201)
async def create_student(
    body:    CreateStudentRequest,
    teacher: Annotated[dict, Depends(require_teacher)],
):
    sb        = get_service_client()
    school_id = teacher.get("school_id")
    if not school_id:
        raise HTTPException(400, "Teacher must belong to a school")

    temp_password = _gen_temp_password()

    # Create Supabase auth user
    try:
        auth_resp = sb.auth.admin.create_user(
            {
                "email":         body.email,
                "password":      temp_password,
                "email_confirm": True,
                "user_metadata": {"name": body.name, "role": "student"},
            }
        )
    except Exception as exc:
        raise HTTPException(409, f"Could not create student account: {exc}") from exc

    uid = auth_resp.user.id

    # Insert public.users
    sb.table("users").insert(
        {
            "id":        uid,
            "name":      body.name,
            "email":     body.email,
            "role":      "student",
            "school_id": school_id,
        }
    ).execute()

    # Insert student_accessibility
    sb.table("student_accessibility").insert(
        {
            "user_id":             uid,
            "disability_profile":  body.disability_profile,
            "language":            body.language,
            "onboarding_complete": True,   # teacher pre-configured
        }
    ).execute()

    return CreateStudentResponse(
        student=StudentSummary(
            id          = uid,
            name        = body.name,
            profile     = body.disability_profile,
            lessons     = 0,
            progress    = 0,
            last_active = "Just added",
            status      = "active",
        ),
        temp_password=temp_password,
    )


# ── GET /teacher/students/{id} ────────────────────────────────────────────

@router.get("/students/{student_id}", response_model=StudentDetail)
async def student_detail(
    student_id: Annotated[str, Path()],
    teacher:    Annotated[dict, Depends(require_teacher)],
):
    sb        = get_service_client()
    school_id = teacher.get("school_id")

    student = (
        sb.table("users")
        .select("*, student_accessibility(*)")
        .eq("id", student_id)
        .eq("school_id", school_id)
        .single()
        .execute()
    ).data
    if not student:
        raise HTTPException(404, "Student not found in your school")

    acc = student.pop("student_accessibility", None) or {}
    if isinstance(acc, list):
        acc = acc[0] if acc else {}

    # All lessons assigned to student with progress
    assignments = (
        sb.table("lesson_assignments")
        .select("lesson_id, lessons(id,title,subject,page_count,icon_emoji,teacher_id,users!lessons_teacher_id_fkey(name))")
        .eq("student_id", student_id)
        .execute()
    ).data or []

    progress_rows = (
        sb.table("student_progress")
        .select("*")
        .eq("student_id", student_id)
        .execute()
    ).data or []
    prog_map = {r["lesson_id"]: r for r in progress_rows}

    lesson_progress: list[LessonSummary] = []
    for a in assignments:
        lesson = a.get("lessons")
        if not lesson:
            continue
        teacher_user = lesson.get("users") or {}
        teacher_name = teacher_user.get("name", "Teacher") if isinstance(teacher_user, dict) else "Teacher"
        prog = prog_map.get(lesson["id"])
        pct  = min(100, round(
            ((prog or {}).get("current_page", 1) / max(1, lesson.get("page_count") or 1)) * 100
        ))
        lesson_progress.append(LessonSummary(
            id               = lesson["id"],
            title            = lesson["title"],
            subject          = lesson["subject"],
            page_count       = lesson.get("page_count") or 1,
            icon_emoji       = lesson.get("icon_emoji") or "📄",
            teacher_name     = teacher_name,
            progress_percent = pct,
            current_page     = (prog or {}).get("current_page", 1),
            is_completed     = (prog or {}).get("is_completed", False),
        ))

    total   = len(lesson_progress)
    overall = round(sum(l.progress_percent for l in lesson_progress) / total) if total else 0

    return StudentDetail(
        id              = student["id"],
        name            = student["name"],
        profile         = acc.get("disability_profile", "visual"),
        language        = acc.get("language", "english"),
        progress        = overall,
        lessons         = total,
        status          = "active" if student.get("is_active") else "inactive",
        last_active     = _relative_time(acc.get("last_active_at")),
        lesson_progress = lesson_progress,
        font_size       = acc.get("font_size", "large"),
        voice_speed     = acc.get("voice_speed", "normal"),
        high_contrast   = acc.get("high_contrast", True),
    )


# ── PUT /teacher/students/{id}/notes ─────────────────────────────────────

@router.put("/students/{student_id}/notes")
async def save_note(
    student_id: Annotated[str, Path()],
    body:       TeacherNoteRequest,
    teacher:    Annotated[dict, Depends(require_teacher)],
):
    sb  = get_service_client()
    tid = teacher["id"]

    sb.table("teacher_notes").upsert(
        {
            "teacher_id": tid,
            "student_id": student_id,
            "note_text":  body.note_text,
        },
        on_conflict="teacher_id,student_id",
    ).execute()

    return {"ok": True}
