from supabase import create_client, Client
from app.config import settings

# ── Service-role client ────────────────────────────────────────────────────────
# Bypasses RLS. Used ONLY inside FastAPI where we enforce our own authz logic.
# NEVER send this key to the browser.
def get_admin_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


# ── Anon client ────────────────────────────────────────────────────────────────
# Used to call supabase.auth.get_user(token) for token validation.
def get_anon_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_anon_key)


# Module-level singletons (created once at startup)
admin_client: Client = get_admin_client()
anon_client: Client  = get_anon_client()
