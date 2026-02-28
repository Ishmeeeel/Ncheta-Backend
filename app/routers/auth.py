"""
Auth Router
============
POST /auth/register    — Teacher/Admin registration with school code
POST /auth/login       — Email + password login
POST /auth/logout      — Invalidate session
GET  /auth/me          — Return current user profile
PUT  /auth/onboarding  — Save disability profile + language choice
PUT  /auth/settings    — Update accessibility settings
"""
from fastapi import APIRouter, HTTPException, status, BackgroundTasks
from app.database import admin_client, anon_client
from app.deps import CurrentUser
from app.schemas.models import (
    RegisterRequest, LoginRequest, AuthResponse, UserResponse,
    OnboardingRequest, SettingsUpdateRequest, MessageResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_user_response(user_row: dict, accessibility: dict | None = None) -> UserResponse:
    return UserResponse(
        id=user_row["id"],
        name=user_row["name"],
        email=user_row["email"],
        role=user_row["role"],
        school_id=user_row.get("school_id"),
        onboarding_complete=accessibility.get("onboarding_complete", False) if accessibility else False,
        profile=accessibility.get("disability_profile") if accessibility else None,
        language=accessibility.get("language") if accessibility else None,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest):
    """
    Register a teacher or admin.
    Students are created by teachers, not by self-registration.
    """
    # 1. Validate the school access code
    school_result = (
        admin_client.table("schools")
        .select("id, name")
        .eq("access_code", body.school_code.strip().upper())
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )
    if not school_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or inactive school access code. Contact your administrator.",
        )
    school_id = school_result.data["id"]

    # 2. Create the Supabase Auth user
    try:
        auth_response = admin_client.auth.admin.create_user({
            "email":    body.email,
            "password": body.password,
            "email_confirm": True,   # Skip email verification for now
        })
    except Exception as e:
        if "already registered" in str(e).lower() or "already exists" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    auth_user_id = auth_response.user.id

    # 3. Insert into public.users
    admin_client.table("users").insert({
        "id":        auth_user_id,
        "name":      body.name,
        "email":     body.email,
        "role":      body.role,
        "school_id": school_id,
    }).execute()

    # 4. Log in to get a session token
    session = anon_client.auth.sign_in_with_password({
        "email":    body.email,
        "password": body.password,
    })

    user_row = {
        "id": auth_user_id, "name": body.name, "email": body.email,
        "role": body.role, "school_id": school_id,
    }

    return AuthResponse(
        user=_build_user_response(user_row),
        access_token=session.session.access_token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    """Email + password login. Returns JWT and user profile."""
    try:
        session = anon_client.auth.sign_in_with_password({
            "email":    body.email,
            "password": body.password,
        })
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    auth_user_id = session.user.id

    # Fetch public user row
    user_result = admin_client.table("users").select("*").eq("id", auth_user_id).maybe_single().execute()
    if not user_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found.")

    user_row = user_result.data

    # Fetch accessibility settings (students only)
    accessibility = None
    if user_row["role"] == "student":
        acc_result = (
            admin_client.table("student_accessibility")
            .select("*")
            .eq("user_id", auth_user_id)
            .maybe_single()
            .execute()
        )
        accessibility = acc_result.data

    return AuthResponse(
        user=_build_user_response(user_row, accessibility),
        access_token=session.session.access_token,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(current_user: CurrentUser):
    """Invalidate session on Supabase side."""
    try:
        admin_client.auth.admin.sign_out(current_user["id"])
    except Exception:
        pass  # Session may have already expired — still return success
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    """Return the current authenticated user's profile + accessibility settings."""
    accessibility = None
    if current_user["role"] == "student":
        acc = (
            admin_client.table("student_accessibility")
            .select("*")
            .eq("user_id", current_user["id"])
            .maybe_single()
            .execute()
        )
        accessibility = acc.data

    return _build_user_response(current_user, accessibility)


@router.put("/onboarding", response_model=MessageResponse)
async def complete_onboarding(body: OnboardingRequest, current_user: CurrentUser):
    """
    Save the student's disability profile and language.
    Called at the end of the onboarding flow.
    Marks onboarding_complete = true so the app won't redirect back.
    """
    if current_user["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students have onboarding.")

    # Upsert accessibility row
    admin_client.table("student_accessibility").upsert({
        "user_id":              current_user["id"],
        "disability_profile":   body.profile,
        "language":             body.language,
        "setup_guide_type":     body.guide_type,
        "onboarding_complete":  True,
    }).execute()

    return {"message": "Onboarding complete."}


@router.put("/settings", response_model=MessageResponse)
async def update_settings(body: SettingsUpdateRequest, current_user: CurrentUser):
    """
    Update student accessibility settings.
    Partial update — only provided fields are changed.
    """
    if current_user["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students have accessibility settings.")

    updates: dict = {}
    if body.profile       is not None: updates["disability_profile"] = body.profile
    if body.language      is not None: updates["language"]           = body.language
    if body.font_size     is not None: updates["font_size"]          = body.font_size
    if body.voice_speed   is not None: updates["voice_speed"]        = body.voice_speed
    if body.high_contrast is not None: updates["high_contrast"]      = body.high_contrast

    if not updates:
        return {"message": "No changes provided."}

    admin_client.table("student_accessibility").upsert({
        "user_id": current_user["id"],
        **updates,
    }).execute()

    return {"message": "Settings updated."}
