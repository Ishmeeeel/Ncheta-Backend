from typing import Annotated
from fastapi import Depends, HTTPException, Header
from .supabase_client import get_service_client


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[7:]


async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    """
    1. Extract JWT from Authorization: Bearer <token>
    2. Verify via Supabase (auth.get_user — no local secret needed)
    3. Fetch the full user row from public.users joined with student_accessibility
    4. Return as dict — routers can then check role, profile, etc.
    """
    token = _extract_token(authorization)
    sb = get_service_client()

    try:
        auth_resp = sb.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token verification failed") from exc

    if not auth_resp or not auth_resp.user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    uid = auth_resp.user.id

    # Fetch user + accessibility settings in one query
    resp = (
        sb.table("users")
        .select("*, student_accessibility(*)")
        .eq("id", uid)
        .single()
        .execute()
    )

    if not resp.data:
        raise HTTPException(status_code=404, detail="User profile not found in database")

    user = resp.data
    # Flatten accessibility into top level for convenience
    acc = user.pop("student_accessibility", None) or {}
    if isinstance(acc, list):          # supabase returns [] when no row
        acc = acc[0] if acc else {}

    user["disability_profile"]   = acc.get("disability_profile")
    user["language"]              = acc.get("language")
    user["font_size"]             = acc.get("font_size", "large")
    user["voice_speed"]           = acc.get("voice_speed", "normal")
    user["high_contrast"]         = acc.get("high_contrast", True)
    user["onboarding_complete"]   = acc.get("onboarding_complete", False)

    return user


async def require_student(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Students only")
    return current_user


async def require_teacher(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if current_user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return current_user


async def require_admin(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if current_user["role"] not in ("admin", "teacher"):
        raise HTTPException(status_code=403, detail="Admins only")
    return current_user
