from supabase import create_client, Client
from .config import settings

# Service role client — bypasses all RLS, used for all data operations
_service_client: Client | None = None

# Anon client — used ONLY for token verification
_anon_client: Client | None = None


def get_service_client() -> Client:
    global _service_client
    if _service_client is None:
        _service_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _service_client


def get_anon_client() -> Client:
    global _anon_client
    if _anon_client is None:
        _anon_client = create_client(
            settings.supabase_url,
            settings.supabase_anon_key,
        )
    return _anon_client
