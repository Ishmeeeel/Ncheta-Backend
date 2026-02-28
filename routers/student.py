"""
Student router
--------------
GET /student/dashboard
GET /student/lessons
GET /student/lessons/{id}
GET /student/lessons/{id}/page/{n}
GET /student/lessons/{id}/audio
PUT /student/lessons/{id}/progress
GET /student/progress
"""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from core.deps import require_student
from core.supabase_client import get_service_client
from models.schemas import (
    DashboardStats, LessonSummary, SubjectBreakdown,
    StudentDashboard, PageContent, AudioResponse,
    ProgressUpdateRequest, StudentProgressPage, ActivityItem,
)

router = APIRouter(prefix="/student", tags=["student"])


# ── Helpers ──────────────────────────────────────────────────────────────

def _progress_percent(current_page: int, page_count: int) -> int:
    if not page_count:
        return 0
    return min(100, round((current_page / page_count) * 100))


def _build_lesson_summary(lesson: dict, progress_row: dict | None, teacher_name: str) -> LessonSummary:
    prog = progress_row or {}
    pct  = _progress_percent(prog.get("current_page", 1), lesson.get("page_count") or 1)
    return LessonSummary(
        id              = lesson["id"],
        title           = lesson["title"],
        subject         = lesson["subject"],
        page_count      = lesson.get("page_count") or 1,
        icon_emoji      = lesson.get("icon_emoji") or "📄",
        teacher_name    = teacher_name,
        progress_percent= pct,
        current_page    = prog.get("current_page", 1),
        is_completed    = prog.get("is_completed", False),
    )


def _relative_time(dt_str: str | None) -> str:
    if not dt_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        diff = datetime.now(dt.tzinfo) - dt
        secs = int(diff.total_seconds())
        if secs < 3600:   return f"{secs // 60}m ago"
        if secs < 86400:  return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return "Recently"


# ── GET /student/dashboard ────────────────────────────────────────────────

@router.get("/dashboard", response_model=StudentDashboard)
async def dashboard(student: Annotated[dict, Depends(require_student)]):
    sb  = get_service_client()
    uid = student["id"]

    # All lessons assigned to this student
    assignments = (
        sb.table("lesson_assignments")
        .select("lesson_id, lessons(id,title,subject,page_count,icon_emoji,teacher_id,users!lessons_teacher_id_fkey(name))")
        .eq("student_id", uid)
        .execute()
    ).data or []

    # All progress rows for this student
    progress_rows = (
        sb.table("student_progress")
        .select("*")
        .eq("student_id", uid)
        .execute()
    ).data or []
    prog_map = {r["lesson_id"]: r for r in progress_rows}

    lessons_with_prog: list[LessonSummary] = []
    for a in assignments:
        lesson = a.get("lessons")
        if not lesson:
            continue
        teacher_user = lesson.get("users") or {}
        teacher_name = teacher_user.get("name", "Teacher") if isinstance(teacher_user, dict) else "Teacher"
        lsum = _build_lesson_summary(lesson, prog_map.get(lesson["id"]), teacher_name)
        lessons_with_prog.append(lsum)

    total    = len(lessons_with_prog)
    completed = sum(1 for l in lessons_with_prog if l.is_completed)
    in_prog  = sum(1 for l in lessons_with_prog if l.progress_percent > 0 and not l.is_completed)
    overall  = round(sum(l.progress_percent for l in lessons_with_prog) / total) if total else 0

    recent    = [l for l in lessons_with_prog if l.progress_percent > 0 and not l.is_completed][:3]
    available = [l for l in lessons_with_prog if l.progress_percent == 0][:3]

    # Subject breakdown
    subject_map: dict[str, dict] = {}
    for l in lessons_with_prog:
        if l.subject not in subject_map:
            subject_map[l.subject] = {"done": 0, "total": 0}
        subject_map[l.subject]["total"] += 1
        if l.is_completed:
            subject_map[l.subject]["done"] += 1
    subjects = [SubjectBreakdown(subject=k, **v) for k, v in subject_map.items()]

    return StudentDashboard(
        stats=DashboardStats(
            total_lessons=total,
            completed=completed,
            in_progress=in_prog,
            overall_progress=overall,
        ),
        recent_lessons=recent,
        available_lessons=available,
        subject_breakdown=subjects,
    )


# ── GET /student/lessons ──────────────────────────────────────────────────

@router.get("/lessons", response_model=list[LessonSummary])
async def lessons(student: Annotated[dict, Depends(require_student)]):
    sb  = get_service_client()
    uid = student["id"]

    assignments = (
        sb.table("lesson_assignments")
        .select("lesson_id, lessons(id,title,subject,page_count,icon_emoji,teacher_id,users!lessons_teacher_id_fkey(name))")
        .eq("student_id", uid)
        .execute()
    ).data or []

    progress_rows = (
        sb.table("student_progress")
        .select("*")
        .eq("student_id", uid)
        .execute()
    ).data or []
    prog_map = {r["lesson_id"]: r for r in progress_rows}

    result = []
    for a in assignments:
        lesson = a.get("lessons")
        if not lesson:
            continue
        teacher_user = lesson.get("users") or {}
        teacher_name = teacher_user.get("name", "Teacher") if isinstance(teacher_user, dict) else "Teacher"
        result.append(_build_lesson_summary(lesson, prog_map.get(lesson["id"]), teacher_name))

    return result


# ── GET /student/lessons/{id} ─────────────────────────────────────────────

@router.get("/lessons/{lesson_id}", response_model=LessonSummary)
async def lesson_detail(
    lesson_id: Annotated[str, Path()],
    student:   Annotated[dict, Depends(require_student)],
):
    sb  = get_service_client()
    uid = student["id"]

    # Verify assignment
    assign = (
        sb.table("lesson_assignments")
        .select("lesson_id")
        .eq("student_id", uid)
        .eq("lesson_id", lesson_id)
        .execute()
    ).data
    if not assign:
        raise HTTPException(403, "You are not assigned to this lesson")

    lesson = (
        sb.table("lessons")
        .select("*, users!lessons_teacher_id_fkey(name)")
        .eq("id", lesson_id)
        .single()
        .execute()
    ).data
    if not lesson:
        raise HTTPException(404, "Lesson not found")

    prog = (
        sb.table("student_progress")
        .select("*")
        .eq("student_id", uid)
        .eq("lesson_id", lesson_id)
        .execute()
    ).data
    prog_row = prog[0] if prog else None

    teacher_user = lesson.pop("users", {}) or {}
    teacher_name = teacher_user.get("name", "Teacher") if isinstance(teacher_user, dict) else "Teacher"

    return _build_lesson_summary(lesson, prog_row, teacher_name)


# ── GET /student/lessons/{id}/page/{n} ───────────────────────────────────

@router.get("/lessons/{lesson_id}/page/{page_num}", response_model=PageContent)
async def lesson_page(
    lesson_id: Annotated[str, Path()],
    page_num:  Annotated[int, Path(ge=1)],
    student:   Annotated[dict, Depends(require_student)],
):
    sb  = get_service_client()
    uid = student["id"]

    # Verify assignment
    assign = (
        sb.table("lesson_assignments")
        .select("lesson_id")
        .eq("student_id", uid)
        .eq("lesson_id", lesson_id)
        .execute()
    ).data
    if not assign:
        raise HTTPException(403, "You are not assigned to this lesson")

    page = (
        sb.table("lesson_pages")
        .select("*")
        .eq("lesson_id", lesson_id)
        .eq("page_number", page_num)
        .execute()
    ).data

    if not page:
        # Return placeholder while processing
        return PageContent(
            page_number=page_num,
            content_original="Content is being processed. Please check back shortly.",
            content_simplified="Content is being processed.",
            image_description=None,
        )

    row = page[0]
    return PageContent(
        page_number=row["page_number"],
        content_original=row.get("content_original"),
        content_simplified=row.get("content_simplified"),
        image_description=row.get("image_description"),
    )


# ── GET /student/lessons/{id}/audio ──────────────────────────────────────

@router.get("/lessons/{lesson_id}/audio", response_model=AudioResponse)
async def lesson_audio(
    lesson_id: Annotated[str, Path()],
    student:   Annotated[dict, Depends(require_student)],
):
    sb       = get_service_client()
    language = student.get("language", "english")

    audio = (
        sb.table("lesson_audio")
        .select("audio_url, language")
        .eq("lesson_id", lesson_id)
        .eq("language", language)
        .execute()
    ).data

    if not audio:
        # Fallback to English
        audio = (
            sb.table("lesson_audio")
            .select("audio_url, language")
            .eq("lesson_id", lesson_id)
            .eq("language", "english")
            .execute()
        ).data

    if not audio:
        return AudioResponse(audio_url=None, language=language)

    row = audio[0]
    return AudioResponse(audio_url=row["audio_url"], language=row["language"])


# ── PUT /student/lessons/{id}/progress ───────────────────────────────────

@router.put("/lessons/{lesson_id}/progress")
async def update_progress(
    lesson_id: Annotated[str, Path()],
    body:      ProgressUpdateRequest,
    student:   Annotated[dict, Depends(require_student)],
):
    sb  = get_service_client()
    uid = student["id"]

    upsert_data: dict = {
        "student_id":       uid,
        "lesson_id":        lesson_id,
        "current_page":     body.current_page,
        "last_accessed_at": datetime.utcnow().isoformat(),
    }
    if body.is_completed:
        upsert_data["is_completed"] = True
        upsert_data["completed_at"] = datetime.utcnow().isoformat()

    sb.table("student_progress").upsert(
        upsert_data, on_conflict="student_id,lesson_id"
    ).execute()

    # Log activity
    action = "completed" if body.is_completed else "read_pages"
    sb.table("activity_log").insert(
        {
            "student_id": uid,
            "lesson_id":  lesson_id,
            "action":     action,
            "pages_read": 1,
        }
    ).execute()

    return {"ok": True}


# ── GET /student/progress ─────────────────────────────────────────────────

@router.get("/progress", response_model=StudentProgressPage)
async def progress_page(student: Annotated[dict, Depends(require_student)]):
    sb  = get_service_client()
    uid = student["id"]

    assignments = (
        sb.table("lesson_assignments")
        .select("lesson_id, lessons(id,title,subject,page_count,icon_emoji,teacher_id,users!lessons_teacher_id_fkey(name))")
        .eq("student_id", uid)
        .execute()
    ).data or []

    progress_rows = (
        sb.table("student_progress")
        .select("*")
        .eq("student_id", uid)
        .execute()
    ).data or []
    prog_map = {r["lesson_id"]: r for r in progress_rows}

    all_lessons: list[LessonSummary] = []
    for a in assignments:
        lesson = a.get("lessons")
        if not lesson:
            continue
        teacher_user = lesson.get("users") or {}
        teacher_name = teacher_user.get("name", "Teacher") if isinstance(teacher_user, dict) else "Teacher"
        all_lessons.append(_build_lesson_summary(lesson, prog_map.get(lesson["id"]), teacher_name))

    completed  = [l for l in all_lessons if l.is_completed]
    in_progress = [l for l in all_lessons if l.progress_percent > 0 and not l.is_completed]

    total   = len(all_lessons)
    overall = round(sum(l.progress_percent for l in all_lessons) / total) if total else 0

    subject_map: dict[str, dict] = {}
    for l in all_lessons:
        if l.subject not in subject_map:
            subject_map[l.subject] = {"done": 0, "total": 0}
        subject_map[l.subject]["total"] += 1
        if l.is_completed:
            subject_map[l.subject]["done"] += 1
    subjects = [SubjectBreakdown(subject=k, **v) for k, v in subject_map.items()]

    # Activity log (last 10)
    activity_raw = (
        sb.table("activity_log")
        .select("action, created_at, lessons(title)")
        .eq("student_id", uid)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []

    activity = [
        ActivityItem(
            action=r["action"],
            lesson_title=(r.get("lessons") or {}).get("title", "Unknown lesson"),
            created_at=_relative_time(r.get("created_at")),
        )
        for r in activity_raw
    ]

    return StudentProgressPage(
        stats=DashboardStats(
            total_lessons=total,
            completed=len(completed),
            in_progress=len(in_progress),
            overall_progress=overall,
        ),
        completed_lessons=completed,
        inprogress_lessons=in_progress,
        subject_breakdown=subjects,
        activity_log=activity,
    )
