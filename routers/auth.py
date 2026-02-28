"""
Auth router
-----------
POST /auth/register        → create Supabase auth user + public.users row
GET  /auth/me              → return full user profile (called after login)
PUT  /auth/onboarding      → save disability profile + language, mark complete
PUT  /auth/settings        → update accessibility preferences
"""
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from core.deps import get_current_user
from core.supabase_client import get_service_client
from models.schemas import (
    RegisterRequest, RegisterResponse,
    OnboardingRequest, SettingsRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Helpers ──────────────────────────────────────────────────────────────

def _row_to_user_response(row: dict) -> UserResponse:
    return UserResponse(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        role=row["role"],
        school_id=row.get("school_id"),
        disability_profile=row.get("disability_profile"),
        language=row.get("language"),
        font_size=row.get("font_size", "large"),
        voice_speed=row.get("voice_speed", "normal"),
        high_contrast=row.get("high_contrast", True),
        onboarding_complete=row.get("onboarding_complete", False),
    )


# ── POST /auth/register ───────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: RegisterRequest):
    sb = get_service_client()

    # 1. Validate school access code
    school_resp = (
        sb.table("schools")
        .select("id, is_active")
        .eq("access_code", body.school_code.upper())
        .single()
        .execute()
    )
    if not school_resp.data:
        raise HTTPException(400, "Invalid school access code")
    if not school_resp.data["is_active"]:
        raise HTTPException(400, "This school is not currently active")
    school_id = school_resp.data["id"]

    # 2. Create Supabase auth user (email_confirm=True skips email confirmation)
    try:
        auth_resp = sb.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
                "user_metadata": {"name": body.name, "role": body.role},
            }
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "already registered" in msg or "already exists" in msg:
            raise HTTPException(409, "An account with this email already exists")
        raise HTTPException(500, f"Could not create account: {exc}") from exc

    if not auth_resp.user:
        raise HTTPException(500, "Account creation returned no user")

    uid = auth_resp.user.id

    # 3. Insert into public.users
    try:
        sb.table("users").insert(
            {
                "id": uid,
                "name": body.name,
                "email": body.email,
                "role": body.role,
                "school_id": school_id,
            }
        ).execute()
    except Exception as exc:
        # Roll back auth user on failure
        sb.auth.admin.delete_user(uid)
        raise HTTPException(500, f"Could not save user profile: {exc}") from exc

    return RegisterResponse(
        user=UserResponse(
            id=uid,
            name=body.name,
            email=body.email,
            role=body.role,
            school_id=school_id,
        )
    )


# ── GET /auth/me ──────────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[dict, Depends(get_current_user)]):
    return _row_to_user_response(current_user)


# ── PUT /auth/onboarding ──────────────────────────────────────────────────

@router.put("/onboarding", response_model=UserResponse)
async def onboarding(
    body: OnboardingRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    if current_user["role"] != "student":
        raise HTTPException(403, "Only students complete onboarding")

    sb = get_service_client()
    uid = current_user["id"]

    # Upsert student_accessibility row
    sb.table("student_accessibility").upsert(
        {
            "user_id": uid,
            "disability_profile": body.disability_profile,
            "language": body.language,
            "setup_guide_type": body.guide_type,
            "onboarding_complete": True,
        },
        on_conflict="user_id",
    ).execute()

    # Return updated user
    current_user["disability_profile"] = body.disability_profile
    current_user["language"] = body.language
    current_user["onboarding_complete"] = True
    return _row_to_user_response(current_user)


# ── PUT /auth/settings ────────────────────────────────────────────────────

@router.put("/settings", response_model=UserResponse)
async def update_settings(
    body: SettingsRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    if current_user["role"] != "student":
        raise HTTPException(403, "Only students have accessibility settings")

    sb = get_service_client()
    uid = current_user["id"]

    update_data: dict = {}
    if body.profile      is not None: update_data["disability_profile"] = body.profile
    if body.language     is not None: update_data["language"]            = body.language
    if body.font_size    is not None: update_data["font_size"]           = body.font_size
    if body.voice_speed  is not None: update_data["voice_speed"]         = body.voice_speed
    if body.high_contrast is not None: update_data["high_contrast"]      = body.high_contrast

    if update_data:
        sb.table("student_accessibility").upsert(
            {"user_id": uid, **update_data},
            on_conflict="user_id",
        ).execute()
        current_user.update(update_data)
        # rename profile key to match response schema
        if "disability_profile" in update_data:
            current_user["disability_profile"] = update_data["disability_profile"]

    return _row_to_user_response(current_user)
