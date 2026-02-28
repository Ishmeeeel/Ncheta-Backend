"""
Supabase Storage service
-------------------------
Handles uploads to the 4 buckets defined in the project.

Buckets:
  lesson-originals  (private)  — raw teacher uploads
  lesson-audio      (public)   — generated MP3s
  lesson-images     (public)   — extracted images
  user-avatars      (public)   — profile pictures (future)
"""
from __future__ import annotations
import uuid

from core.config import settings
from core.supabase_client import get_service_client


# ── Originals (private) ──────────────────────────────────────────────────

def upload_original_file(file_bytes: bytes, filename: str, teacher_id: str) -> str:
    """
    Uploads raw lesson file to lesson-originals bucket.
    Returns the storage path (NOT a public URL — fetch server-side).
    """
    sb    = get_service_client()
    ext   = filename.rsplit(".", 1)[-1].lower()
    path  = f"{teacher_id}/{uuid.uuid4()}.{ext}"

    sb.storage.from_("lesson-originals").upload(
        path,
        file_bytes,
        file_options={"content-type": _content_type(ext), "upsert": "true"},
    )
    return path


# ── Audio (public) ────────────────────────────────────────────────────────

def upload_audio(audio_bytes: bytes, lesson_id: str, language: str) -> str:
    """
    Uploads MP3 to lesson-audio bucket.
    Returns the full public URL.
    """
    sb   = get_service_client()
    path = f"{lesson_id}/{language}.mp3"

    sb.storage.from_("lesson-audio").upload(
        path,
        audio_bytes,
        file_options={"content-type": "audio/mpeg", "upsert": "true"},
    )

    # Construct public URL
    return f"{settings.supabase_url}/storage/v1/object/public/lesson-audio/{path}"


# ── Helper ───────────────────────────────────────────────────────────────

def _content_type(ext: str) -> str:
    return {
        "pdf":  "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }.get(ext, "application/octet-stream")
