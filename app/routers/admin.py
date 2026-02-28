"""
Admin Router
=============
GET  /admin/dashboard          — Platform-wide stats + schools list
GET  /admin/schools            — All schools
POST /admin/schools            — Create new school (generates access code)
POST /admin/schools/{id}/deactivate  — Deactivate a school
"""
import secrets
import string
from fastapi import APIRouter, HTTPException, status
from app.database import admin_client
from app.deps import AdminUser
from app.schemas.models import (
    AdminDashboardResponse, PlatformStats, SchoolSummary, ProfileBreakdown,
    CreateSchoolRequest, CreateSchoolResponse, MessageResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])

PROFILE_META = {
    "visual":   {"emoji": "👁️", "color": "#F59E0B"},
    "hearing":  {"emoji": "👂", "color": "#6366F1"},
    "dyslexia": {"emoji": "🧠", "color": "#10B981"},
    "motor":    {"emoji": "🖐️", "color": "#EF4444"},
}


def _generate_access_code(length: int = 8) -> str:
    """Generate a human-readable school access code like NCH-A3K9."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(length))
    return f"NCH-{suffix[:4]}"


async def _get_school_summary(school: dict) -> SchoolSummary:
    school_id = school["id"]

    students_result = (
        admin_client.table("users")
        .select("id", count="exact")
        .eq("school_id", school_id)
        .eq("role", "student")
        .execute()
    )
    teachers_result = (
        admin_client.table("users")
        .select("id", count="exact")
        .eq("school_id", school_id)
        .eq("role", "teacher")
        .execute()
    )

    return SchoolSummary(
        id=school_id,
        name=school["name"],
        location=school["location"],
        access_code=school["access_code"],
        students=students_result.count or 0,
        teachers=teachers_result.count or 0,
        is_active=school.get("is_active", True),
    )


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def admin_dashboard(current_user: AdminUser):
    """Platform-wide overview for admin dashboard."""

    # Platform stats
    schools_r  = admin_client.table("schools").select("id", count="exact").execute()
    students_r = admin_client.table("users").select("id", count="exact").eq("role", "student").execute()
    teachers_r = admin_client.table("users").select("id", count="exact").eq("role", "teacher").execute()
    lessons_r  = admin_client.table("lessons").select("id", count="exact").eq("is_published", True).execute()

    stats = PlatformStats(
        total_schools=schools_r.count or 0,
        total_students=students_r.count or 0,
        total_teachers=teachers_r.count or 0,
        total_lessons=lessons_r.count or 0,
    )

    # Schools list
    schools_data = admin_client.table("schools").select("*").order("created_at", desc=True).execute()
    school_summaries = []
    for s in (schools_data.data or []):
        school_summaries.append(await _get_school_summary(s))

    # Profile breakdown (disability profile distribution)
    acc_result = (
        admin_client.table("student_accessibility")
        .select("disability_profile")
        .execute()
    )
    profile_counts: dict[str, int] = {"visual": 0, "hearing": 0, "dyslexia": 0, "motor": 0}
    for row in (acc_result.data or []):
        p = row.get("disability_profile", "visual")
        if p in profile_counts:
            profile_counts[p] += 1

    profile_breakdown = [
        ProfileBreakdown(
            profile=pid,
            emoji=PROFILE_META[pid]["emoji"],
            color=PROFILE_META[pid]["color"],
            count=profile_counts.get(pid, 0),
        )
        for pid in PROFILE_META
    ]

    return AdminDashboardResponse(
        stats=stats,
        schools=school_summaries,
        profile_breakdown=profile_breakdown,
    )


@router.get("/schools", response_model=list[SchoolSummary])
async def list_schools(current_user: AdminUser):
    schools = admin_client.table("schools").select("*").order("name").execute()
    return [await _get_school_summary(s) for s in (schools.data or [])]


@router.post("/schools", response_model=CreateSchoolResponse, status_code=status.HTTP_201_CREATED)
async def create_school(body: CreateSchoolRequest, current_user: AdminUser):
    """Create a new school. Generates a unique access code automatically."""
    # Ensure unique access code
    for _ in range(10):
        code = _generate_access_code()
        existing = (
            admin_client.table("schools")
            .select("id")
            .eq("access_code", code)
            .maybe_single()
            .execute()
        )
        if not existing.data:
            break

    result = admin_client.table("schools").insert({
        "name":        body.name,
        "location":    body.location,
        "access_code": code,
        "is_active":   True,
    }).execute()

    new_school = result.data[0]
    summary = SchoolSummary(
        id=new_school["id"],
        name=new_school["name"],
        location=new_school["location"],
        access_code=new_school["access_code"],
        students=0,
        teachers=0,
        is_active=True,
    )
    return CreateSchoolResponse(school=summary, access_code=code)


@router.post("/schools/{school_id}/deactivate", response_model=MessageResponse)
async def deactivate_school(school_id: str, current_user: AdminUser):
    """Deactivate a school — prevents new logins from that school."""
    admin_client.table("schools").update({"is_active": False}).eq("id", school_id).execute()
    return {"message": "School deactivated."}
