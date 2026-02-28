"""
Student Router
===============
GET /student/dashboard              — Stats + recent/available lessons
GET /student/lessons                — All assigned lessons
GET /student/lessons/{id}           — Lesson detail + audio URL for user's language
GET /student/lessons/{id}/page/{n}  — Page content (original, simplified, image desc)
PUT /student/lessons/{id}/progress  — Update current page (called on every page turn)
GET /student/progress               — Full progress page data
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from app.database import admin_client
from app.deps import StudentUser
from app.schemas.models import (
    StudentDashboardResponse, StudentStats, SubjectBreakdown, LessonSummary,
    LessonDetail, PageContent, ProgressUpdateRequest, ProgressUpdateResponse,
    StudentProgressResponse, ActivityEntry,
)

router = APIRouter(prefix="/student", tags=["student"])

SUBJECTS = ["Science", "Math", "History", "English", "Geography", "Biology"]
PROFILE_COLORS = {"visual": "#F59E0B", "hearing": "#6366F1", "dyslexia": "#10B981", "motor": "#EF4444"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _time_ago(dt_str: str | None) -> str:
    """Convert ISO timestamp to human-readable 'X ago' string."""
    if not dt_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return "Recently"


def _calc_progress(current_page: int, page_count: int) -> int:
    if not page_count:
        return 0
    return min(100, round((current_page / page_count) * 100))


def _build_lesson_summary(lesson: dict, progress: dict | None) -> LessonSummary:
    page_count    = lesson.get("page_count") or 1
    current_page  = progress["current_page"] if progress else 0
    is_completed  = progress["is_completed"] if progress else False
    pct           = 100 if is_completed else _calc_progress(current_page, page_count)

    # Get teacher name
    teacher_name = "Unknown Teacher"
    if lesson.get("users"):
        teacher_name = lesson["users"]["name"]

    return LessonSummary(
        id=lesson["id"],
        title=lesson["title"],
        subject=lesson["subject"],
        page_count=page_count,
        icon_emoji=lesson.get("icon_emoji", "📄"),
        teacher_name=teacher_name,
        is_published=lesson.get("is_published", False),
        processing_status=lesson.get("processing_status", "done"),
        progress_percent=pct,
        current_page=current_page,
        is_completed=is_completed,
    )


def _get_student_lessons_with_progress(student_id: str) -> list[dict]:
    """
    Fetch all lessons assigned to a student, joined with their progress.
    Returns list of dicts with lesson + progress merged.
    """
    # All assignments for this student
    assignments = (
        admin_client.table("lesson_assignments")
        .select("lesson_id")
        .eq("student_id", student_id)
        .execute()
    )
    if not assignments.data:
        return []

    lesson_ids = [a["lesson_id"] for a in assignments.data]

    # Fetch lessons
    lessons_result = (
        admin_client.table("lessons")
        .select("*, users(name)")
        .in_("id", lesson_ids)
        .eq("is_published", True)
        .execute()
    )
    lessons = {l["id"]: l for l in (lessons_result.data or [])}

    # Fetch progress
    progress_result = (
        admin_client.table("student_progress")
        .select("*")
        .eq("student_id", student_id)
        .in_("lesson_id", lesson_ids)
        .execute()
    )
    progress = {p["lesson_id"]: p for p in (progress_result.data or [])}

    return [(lessons[lid], progress.get(lid)) for lid in lesson_ids if lid in lessons]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=StudentDashboardResponse)
async def student_dashboard(current_user: StudentUser):
    """Main student dashboard — stats + lesson lists."""
    student_id = current_user["id"]
    lesson_pairs = _get_student_lessons_with_progress(student_id)

    all_summaries = [_build_lesson_summary(l, p) for l, p in lesson_pairs]

    completed    = [s for s in all_summaries if s.is_completed]
    in_progress  = [s for s in all_summaries if s.progress_percent and 0 < s.progress_percent < 100]
    available    = [s for s in all_summaries if not s.is_completed]

    overall = round(sum(s.progress_percent for s in all_summaries) / len(all_summaries)) if all_summaries else 0

    stats = StudentStats(
        total_lessons=len(all_summaries),
        completed=len(completed),
        in_progress=len(in_progress),
        overall_progress=overall,
    )

    subject_breakdown = []
    for subj in SUBJECTS:
        subj_lessons = [s for s in all_summaries if s.subject == subj]
        if subj_lessons:
            subject_breakdown.append(SubjectBreakdown(
                subject=subj,
                done=sum(1 for s in subj_lessons if s.is_completed),
                total=len(subj_lessons),
            ))

    return StudentDashboardResponse(
        stats=stats,
        recent_lessons=in_progress[:2],
        available_lessons=available[:3],
        subject_breakdown=subject_breakdown,
    )


@router.get("/lessons", response_model=list[LessonSummary])
async def student_lessons(current_user: StudentUser):
    """All lessons assigned to the student."""
    lesson_pairs = _get_student_lessons_with_progress(current_user["id"])
    return [_build_lesson_summary(l, p) for l, p in lesson_pairs]


@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
async def get_lesson(lesson_id: str, current_user: StudentUser):
    """
    Lesson detail view. Returns lesson metadata + audio URL for the student's language.
    """
    # Verify assignment
    assignment = (
        admin_client.table("lesson_assignments")
        .select("id")
        .eq("lesson_id", lesson_id)
        .eq("student_id", current_user["id"])
        .maybe_single()
        .execute()
    )
    if not assignment.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found or not assigned.")

    # Fetch lesson
    lesson_result = (
        admin_client.table("lessons")
        .select("*, users(name)")
        .eq("id", lesson_id)
        .eq("is_published", True)
        .maybe_single()
        .execute()
    )
    if not lesson_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

    lesson = lesson_result.data

    # Fetch or create progress row
    progress_result = (
        admin_client.table("student_progress")
        .select("*")
        .eq("student_id", current_user["id"])
        .eq("lesson_id", lesson_id)
        .maybe_single()
        .execute()
    )

    if progress_result.data:
        progress = progress_result.data
    else:
        # First time opening this lesson
        new_progress = {
            "student_id": current_user["id"],
            "lesson_id":  lesson_id,
            "current_page": 1,
        }
        admin_client.table("student_progress").insert(new_progress).execute()

        # Log activity
        admin_client.table("activity_log").insert({
            "student_id": current_user["id"],
            "lesson_id":  lesson_id,
            "action":     "started",
        }).execute()

        progress = {"current_page": 1, "is_completed": False}

    # Fetch audio URL for student's language
    lang = current_user.get("language", "english") or "english"
    audio_result = (
        admin_client.table("lesson_audio")
        .select("audio_url")
        .eq("lesson_id", lesson_id)
        .eq("language", lang)
        .maybe_single()
        .execute()
    )
    audio_url = audio_result.data["audio_url"] if audio_result.data else None

    page_count   = lesson.get("page_count") or 1
    current_page = progress.get("current_page", 1)
    is_completed = progress.get("is_completed", False)
    pct          = 100 if is_completed else _calc_progress(current_page, page_count)

    # Update last_accessed_at
    admin_client.table("student_progress").update({
        "last_accessed_at": "now()",
    }).eq("student_id", current_user["id"]).eq("lesson_id", lesson_id).execute()

    return LessonDetail(
        id=lesson["id"],
        title=lesson["title"],
        subject=lesson["subject"],
        page_count=page_count,
        icon_emoji=lesson.get("icon_emoji", "📄"),
        teacher_name=lesson["users"]["name"] if lesson.get("users") else "Unknown",
        current_page=current_page,
        progress_percent=pct,
        is_completed=is_completed,
        audio_url=audio_url,
    )


@router.get("/lessons/{lesson_id}/page/{page_number}", response_model=PageContent)
async def get_page(lesson_id: str, page_number: int, current_user: StudentUser):
    """Return content for a specific page (original, simplified, image desc)."""
    page_result = (
        admin_client.table("lesson_pages")
        .select("*")
        .eq("lesson_id", lesson_id)
        .eq("page_number", page_number)
        .maybe_single()
        .execute()
    )
    if not page_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")

    p = page_result.data
    return PageContent(
        page_number=p["page_number"],
        content_original=p.get("content_original"),
        content_simplified=p.get("content_simplified"),
        image_description=p.get("image_description"),
    )


@router.put("/lessons/{lesson_id}/progress", response_model=ProgressUpdateResponse)
async def update_progress(lesson_id: str, body: ProgressUpdateRequest, current_user: StudentUser):
    """
    Called on every page turn. Updates current_page.
    Marks lesson complete when student reaches the last page.
    """
    # Get page count
    lesson = admin_client.table("lessons").select("page_count").eq("id", lesson_id).maybe_single().execute()
    if not lesson.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

    page_count   = lesson.data.get("page_count") or 1
    current_page = min(body.current_page, page_count)
    is_completed = current_page >= page_count

    update_data: dict = {
        "current_page":     current_page,
        "last_accessed_at": "now()",
    }
    if is_completed:
        update_data["is_completed"]  = True
        update_data["completed_at"]  = "now()"

    admin_client.table("student_progress").upsert({
        "student_id": current_user["id"],
        "lesson_id":  lesson_id,
        **update_data,
    }).execute()

    # Log activity
    action = "completed" if is_completed else "read_pages"
    admin_client.table("activity_log").insert({
        "student_id": current_user["id"],
        "lesson_id":  lesson_id,
        "action":     action,
        "pages_read": 1,
    }).execute()

    pct = 100 if is_completed else _calc_progress(current_page, page_count)
    return ProgressUpdateResponse(progress_percent=pct, is_completed=is_completed)


@router.get("/progress", response_model=StudentProgressResponse)
async def student_progress(current_user: StudentUser):
    """Full progress page — completed, in-progress, activity log."""
    student_id   = current_user["id"]
    lesson_pairs = _get_student_lessons_with_progress(student_id)
    all_summaries = [_build_lesson_summary(l, p) for l, p in lesson_pairs]

    completed   = [s for s in all_summaries if s.is_completed]
    in_progress = [s for s in all_summaries if s.progress_percent and 0 < s.progress_percent < 100]
    overall     = round(sum(s.progress_percent for s in all_summaries) / len(all_summaries)) if all_summaries else 0

    stats = StudentStats(
        total_lessons=len(all_summaries),
        completed=len(completed),
        in_progress=len(in_progress),
        overall_progress=overall,
    )

    subject_breakdown = []
    for subj in SUBJECTS:
        subj_lessons = [s for s in all_summaries if s.subject == subj]
        if subj_lessons:
            subject_breakdown.append(SubjectBreakdown(
                subject=subj,
                done=sum(1 for s in subj_lessons if s.is_completed),
                total=len(subj_lessons),
            ))

    # Recent activity
    activity_result = (
        admin_client.table("activity_log")
        .select("action, created_at, lessons(title)")
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    activity = []
    for row in (activity_result.data or []):
        lesson_title = row["lessons"]["title"] if row.get("lessons") else "Unknown lesson"
        activity.append(ActivityEntry(
            action=row["action"],
            lesson=lesson_title,
            time=_time_ago(row.get("created_at")),
        ))

    return StudentProgressResponse(
        stats=stats,
        completed=completed,
        in_progress=in_progress,
        subject_breakdown=subject_breakdown,
        activity=activity,
    )
