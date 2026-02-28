from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import anon_client, admin_client

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> dict:
    """
    Validates the Supabase JWT from the Authorization header.
    Returns the user row from public.users (with school_id, role, etc.)
    Raises 401 if token is invalid or user not found.
    """
    token = credentials.credentials

    # Let Supabase validate the JWT — no manual JWT decoding needed
    try:
        response = anon_client.auth.get_user(token)
        if response is None or response.user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    auth_user_id = response.user.id

    # Fetch the app-level user row from public.users
    result = admin_client.table("users").select("*").eq("id", auth_user_id).maybe_single().execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User profile not found")

    return result.data  # { id, name, email, role, school_id, is_active }


async def require_student(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student access required")
    return user


async def require_teacher(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher access required")
    return user


async def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# Type aliases for cleaner route signatures
CurrentUser  = Annotated[dict, Depends(get_current_user)]
StudentUser  = Annotated[dict, Depends(require_student)]
TeacherUser  = Annotated[dict, Depends(require_teacher)]
AdminUser    = Annotated[dict, Depends(require_admin)]
