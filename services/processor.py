"""
Lesson processing pipeline
--------------------------
Runs as a FastAPI BackgroundTask after teacher upload.

Pipeline steps (in order):
  1. extract_text        — parse PDF/DOCX into page strings
  2. audio_english       — Azure TTS, English
  3. audio_hausa         — Azure TTS, Hausa
  4. audio_yoruba        — Azure TTS, Yoruba
  5. audio_igbo          — Azure TTS, Igbo
  6. simplify_dyslexia   — HuggingFace simplified text per page
  7. image_descriptions  — HuggingFace alt-text per page

Each completed step updates processing_jobs.steps in Supabase so the
frontend polling endpoint shows real-time progress.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def _sb():
    """Lazy import to avoid circular deps."""
    from core.supabase_client import get_service_client
    return get_service_client()


def _mark_step(lesson_id: str, step: str, done: bool = True) -> None:
    """Update a single step in processing_jobs.steps JSONB."""
    try:
        sb  = _sb()
        job = (
            sb.table("processing_jobs")
            .select("steps")
            .eq("lesson_id", lesson_id)
            .single()
            .execute()
        ).data

        if not job:
            return

        steps         = job["steps"] or {}
        steps[step]   = done
        sb.table("processing_jobs").update({"steps": steps}).eq("lesson_id", lesson_id).execute()
    except Exception as exc:
        log.error("Failed to mark step %s for lesson %s: %s", step, lesson_id, exc)


def _set_status(lesson_id: str, status: str, error: str | None = None) -> None:
    try:
        sb = _sb()
        update: dict = {
            "status":      status,
            "started_at":  datetime.utcnow().isoformat() if status == "running" else None,
            "completed_at": datetime.utcnow().isoformat() if status in ("done", "failed") else None,
        }
        if error:
            update["error_message"] = error
        # Remove None values — supabase-py doesn't like them
        update = {k: v for k, v in update.items() if v is not None}
        sb.table("processing_jobs").update(update).eq("lesson_id", lesson_id).execute()
        sb.table("lessons").update({"processing_status": status}).eq("id", lesson_id).execute()
    except Exception as exc:
        log.error("Failed to set status %s for lesson %s: %s", status, lesson_id, exc)


async def process_lesson_pipeline(
    lesson_id:  str,
    file_bytes: bytes,
    file_type:  str,
) -> None:
    """
    Entry point called by FastAPI BackgroundTasks.
    Never raises — all errors are caught and written to the job row.
    """
    sb = _sb()
    _set_status(lesson_id, "running")

    try:
        # ── Step 1: Extract text ──────────────────────────────────────────
        sb.table("lessons").update({"processing_status": "extracting"}).eq("id", lesson_id).execute()

        from services.extractor import extract_pages
        pages = extract_pages(file_bytes, file_type)

        # Save pages to lesson_pages table
        page_rows = [
            {"lesson_id": lesson_id, "page_number": i + 1, "content_original": text}
            for i, text in enumerate(pages)
        ]
        if page_rows:
            sb.table("lesson_pages").upsert(page_rows, on_conflict="lesson_id,page_number").execute()

        # Update page_count on lesson
        sb.table("lessons").update({"page_count": len(pages)}).eq("id", lesson_id).execute()
        _mark_step(lesson_id, "extract_text")

        # Combine all pages for whole-lesson audio (first 4000 chars)
        full_text = "\n\n".join(pages)

        # ── Steps 2-5: TTS for all 4 languages ───────────────────────────
        sb.table("lessons").update({"processing_status": "generating_audio"}).eq("id", lesson_id).execute()

        from services.tts import generate_audio
        from services.storage import upload_audio

        for language, step_key in [
            ("english", "audio_english"),
            ("hausa",   "audio_hausa"),
            ("yoruba",  "audio_yoruba"),
            ("igbo",    "audio_igbo"),
        ]:
            try:
                audio_bytes = await generate_audio(full_text[:4000], language)
                audio_url   = upload_audio(audio_bytes, lesson_id, language)

                sb.table("lesson_audio").upsert(
                    {"lesson_id": lesson_id, "language": language, "audio_url": audio_url},
                    on_conflict="lesson_id,language",
                ).execute()

                _mark_step(lesson_id, step_key)
            except Exception as exc:
                log.warning("TTS failed for %s/%s: %s", lesson_id, language, exc)
                # Mark as done=False (already the default) — pipeline continues
                await asyncio.sleep(0.5)

        # ── Step 6: Simplify text (dyslexia mode) ────────────────────────
        sb.table("lessons").update({"processing_status": "simplifying"}).eq("id", lesson_id).execute()

        from services.simplifier import simplify_text, generate_image_description

        simplified_rows: list[dict] = []
        for i, text in enumerate(pages):
            try:
                simplified = await simplify_text(text)
                simplified_rows.append({
                    "lesson_id":          lesson_id,
                    "page_number":        i + 1,
                    "content_simplified": simplified,
                })
                await asyncio.sleep(0.2)   # Rate-limit HF API
            except Exception as exc:
                log.warning("Simplification failed for page %d: %s", i + 1, exc)

        if simplified_rows:
            sb.table("lesson_pages").upsert(
                simplified_rows, on_conflict="lesson_id,page_number"
            ).execute()

        _mark_step(lesson_id, "simplify_dyslexia")

        # ── Step 7: Image descriptions (visual impairment mode) ───────────
        desc_rows: list[dict] = []
        for i, text in enumerate(pages):
            try:
                desc = await generate_image_description(text)
                desc_rows.append({
                    "lesson_id":        lesson_id,
                    "page_number":      i + 1,
                    "image_description": desc,
                })
                await asyncio.sleep(0.2)
            except Exception as exc:
                log.warning("Image description failed for page %d: %s", i + 1, exc)

        if desc_rows:
            sb.table("lesson_pages").upsert(
                desc_rows, on_conflict="lesson_id,page_number"
            ).execute()

        _mark_step(lesson_id, "image_descriptions")

        # ── All done ─────────────────────────────────────────────────────
        _set_status(lesson_id, "done")
        sb.table("lessons").update({"is_published": True}).eq("id", lesson_id).execute()
        log.info("Lesson %s processed successfully (%d pages)", lesson_id, len(pages))

    except Exception as exc:
        log.error("Pipeline FAILED for lesson %s: %s", lesson_id, exc, exc_info=True)
        _set_status(lesson_id, "failed", error=str(exc))
