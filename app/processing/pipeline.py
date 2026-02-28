"""
Ncheta AI Processing Pipeline
==============================
Runs as a FastAPI BackgroundTask after a teacher uploads a lesson.

Steps (in order):
  1. Download file from Supabase Storage
  2. Extract text → lesson_pages rows
  3. Generate audio in 4 languages → lesson_audio rows + Storage upload
  4. Simplify text (dyslexia mode) → update lesson_pages.content_simplified
  5. Generate image descriptions (visual mode) → update lesson_pages.image_description
  6. Mark lesson as published and job as done

Each step updates processing_jobs.steps so the frontend poll can show live progress.
"""
import asyncio
import json
import uuid
from typing import List

from app.database import admin_client
from app.services.extractor import extract_text
from app.services.tts import generate_audio
from app.services.simplify import simplify_text, generate_image_description

LANGUAGES = ["english", "hausa", "yoruba", "igbo"]

AUDIO_STEP_MAP = {
    "english": "audio_english",
    "hausa":   "audio_hausa",
    "yoruba":  "audio_yoruba",
    "igbo":    "audio_igbo",
}


def _update_step(job_id: str, step_name: str) -> None:
    """Mark a single processing step as complete in the DB."""
    job = admin_client.table("processing_jobs").select("steps").eq("id", job_id).single().execute()
    steps = job.data["steps"] if job.data else {}
    steps[step_name] = True
    admin_client.table("processing_jobs").update({"steps": steps}).eq("id", job_id).execute()


def _fail_job(job_id: str, lesson_id: str, error: str) -> None:
    admin_client.table("processing_jobs").update({
        "status": "failed",
        "error_message": error[:500],
    }).eq("id", job_id).execute()
    admin_client.table("lessons").update({"processing_status": "failed"}).eq("id", lesson_id).execute()


async def run_pipeline(
    lesson_id: str,
    job_id: str,
    file_bytes: bytes,
    file_type: str,
    school_id: str,
) -> None:
    """
    Main pipeline coroutine. Called via asyncio.create_task() from the router.
    """
    try:
        # ── Mark running ──────────────────────────────────────────────────────
        admin_client.table("processing_jobs").update({
            "status": "running",
            "started_at": "now()",
        }).eq("id", job_id).execute()

        admin_client.table("lessons").update({
            "processing_status": "extracting",
        }).eq("id", lesson_id).execute()

        # ── Step 1: Extract text ───────────────────────────────────────────────
        pages: List[str] = extract_text(file_bytes, file_type)

        # Update page_count on the lesson
        admin_client.table("lessons").update({"page_count": len(pages)}).eq("id", lesson_id).execute()

        # Insert lesson_pages rows
        page_rows = [
            {
                "lesson_id":        lesson_id,
                "page_number":      i + 1,
                "content_original": text,
            }
            for i, text in enumerate(pages)
        ]
        admin_client.table("lesson_pages").insert(page_rows).execute()
        _update_step(job_id, "extract_text")

        # ── Step 2: Generate TTS audio for all 4 languages ─────────────────────
        admin_client.table("lessons").update({"processing_status": "generating_audio"}).eq("id", lesson_id).execute()

        # Concatenate first 3 pages for audio (keeps file size manageable)
        audio_text = "\n\n".join(pages[:3])

        for language in LANGUAGES:
            try:
                mp3_bytes = await generate_audio(audio_text, language)

                # Upload to Supabase Storage → lesson-audio bucket
                storage_path = f"{school_id}/{lesson_id}/{language}.mp3"
                admin_client.storage.from_("lesson-audio").upload(
                    path=storage_path,
                    file=mp3_bytes,
                    file_options={"content-type": "audio/mpeg", "upsert": "true"},
                )

                # Get the public URL
                url_response = admin_client.storage.from_("lesson-audio").get_public_url(storage_path)
                public_url = url_response if isinstance(url_response, str) else url_response.get("publicUrl", "")

                # Insert lesson_audio row
                admin_client.table("lesson_audio").upsert({
                    "lesson_id": lesson_id,
                    "language":  language,
                    "audio_url": public_url,
                }).execute()

                _update_step(job_id, AUDIO_STEP_MAP[language])

            except Exception as lang_err:
                # Don't fail the whole pipeline for one language
                print(f"[pipeline] Audio failed for {language}: {lang_err}")

        # ── Step 3: Simplify text (dyslexia mode) ─────────────────────────────
        admin_client.table("lessons").update({"processing_status": "simplifying"}).eq("id", lesson_id).execute()

        for i, text in enumerate(pages):
            try:
                simplified = await simplify_text(text)
                admin_client.table("lesson_pages").update({
                    "content_simplified": simplified,
                }).eq("lesson_id", lesson_id).eq("page_number", i + 1).execute()
            except Exception as simp_err:
                print(f"[pipeline] Simplify failed for page {i+1}: {simp_err}")

        _update_step(job_id, "simplify_dyslexia")

        # ── Step 4: Image descriptions (visual mode) ───────────────────────────
        for i, text in enumerate(pages[:5]):  # First 5 pages only
            try:
                description = await generate_image_description(text)
                admin_client.table("lesson_pages").update({
                    "image_description": description,
                }).eq("lesson_id", lesson_id).eq("page_number", i + 1).execute()
            except Exception as img_err:
                print(f"[pipeline] Image desc failed for page {i+1}: {img_err}")

        _update_step(job_id, "image_descriptions")

        # ── Mark done ──────────────────────────────────────────────────────────
        admin_client.table("processing_jobs").update({
            "status":       "done",
            "completed_at": "now()",
        }).eq("id", job_id).execute()

        admin_client.table("lessons").update({
            "processing_status": "done",
            "is_published":      True,
        }).eq("id", lesson_id).execute()

        print(f"[pipeline] Lesson {lesson_id} processed successfully.")

    except Exception as e:
        print(f"[pipeline] FATAL for lesson {lesson_id}: {e}")
        _fail_job(job_id, lesson_id, str(e))
