"""
Admin router
------------
GET  /admin/dashboard
GET  /admin/schools
POST /admin/schools
POST /admin/schools/{id}/access-code  (regenerate)
"""
import secrets
import string
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from core.deps import require_admin
from core.supabase_client import get_service_client
from models.schemas import AdminDashboard, SchoolSummary

router = APIRouter(prefix="/admin", tags=["admin"])


def _gen_code(prefix: str = "NCH") -> str:
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
    return f"{prefix}-{suffix}"


# ── GET /admin/dashboard ─────────────────────────────────────────────────

@router.get("/dashboard", response_model=AdminDashboard)
async def admin_dashboard(admin: Annotated[dict, Depends(require_admin)]):
    sb = get_service_client()

    schools = (sb.table("schools").select("*").execute()).data or []

    # Count users per school
    users_resp = (
        sb.table("users").select("role, school_id, student_accessibility(disability_profile)").execute()
    ).data or []

    school_stats: dict[str, dict] = {
        s["id"]: {"students": 0, "teachers": 0} for s in schools
    }
    profile_counts: dict[str, int] = {}

    for u in users_resp:
        sid = u.get("school_id")
        if sid and sid in school_stats:
            if u["role"] == "student":
                school_stats[sid]["students"] += 1
                # Profile breakdown
                acc = u.get("student_accessibility") or {}
                if isinstance(acc, list):
                    acc = acc[0] if acc else {}
                profile = acc.get("disability_profile", "visual") if acc else "visual"
                profile_counts[profile] = profile_counts.get(profile, 0) + 1
            elif u["role"] == "teacher":
                school_stats[sid]["teachers"] += 1

    total_lessons = (
        sb.table("lessons").select("id", count="exact").execute()
    ).count or 0

    school_list = [
        SchoolSummary(
            id          = s["id"],
            name        = s["name"],
            location    = s["location"],
            access_code = s["access_code"],
            students    = school_stats.get(s["id"], {}).get("students", 0),
            teachers    = school_stats.get(s["id"], {}).get("teachers", 0),
            is_active   = s["is_active"],
        )
        for s in schools
    ]

    return AdminDashboard(
        stats={
            "total_schools":   len(schools),
            "total_students":  sum(v["students"] for v in school_stats.values()),
            "total_teachers":  sum(v["teachers"] for v in school_stats.values()),
            "total_lessons":   total_lessons,
        },
        schools=school_list,
        profile_breakdown=[{"profile": k, "count": v} for k, v in profile_counts.items()],
    )


# ── GET /admin/schools ────────────────────────────────────────────────────

@router.get("/schools", response_model=list[SchoolSummary])
async def list_schools(admin: Annotated[dict, Depends(require_admin)]):
    sb      = get_service_client()
    schools = (sb.table("schools").select("*").order("created_at", desc=True).execute()).data or []

    result = []
    for s in schools:
        students = (
            sb.table("users").select("id", count="exact").eq("school_id", s["id"]).eq("role", "student").execute()
        ).count or 0
        teachers = (
            sb.table("users").select("id", count="exact").eq("school_id", s["id"]).eq("role", "teacher").execute()
        ).count or 0
        result.append(SchoolSummary(
            id          = s["id"],
            name        = s["name"],
            location    = s["location"],
            access_code = s["access_code"],
            students    = students,
            teachers    = teachers,
            is_active   = s["is_active"],
        ))
    return result


# ── POST /admin/schools ───────────────────────────────────────────────────

@router.post("/schools", response_model=SchoolSummary, status_code=201)
async def create_school(
    name:     str,
    location: str,
    admin:    Annotated[dict, Depends(require_admin)],
):
    sb   = get_service_client()
    code = _gen_code()

    row = (
        sb.table("schools").insert(
            {"name": name, "location": location, "access_code": code}
        ).execute()
    ).data[0]

    return SchoolSummary(
        id=row["id"], name=row["name"], location=row["location"],
        access_code=row["access_code"], students=0, teachers=0, is_active=True,
    )


# ── POST /admin/schools/{id}/access-code ─────────────────────────────────

@router.post("/schools/{school_id}/access-code")
async def regenerate_code(
    school_id: Annotated[str, Path()],
    admin:     Annotated[dict, Depends(require_admin)],
):
    sb   = get_service_client()
    code = _gen_code()
    sb.table("schools").update({"access_code": code}).eq("id", school_id).execute()
    return {"access_code": code}
