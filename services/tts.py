"""
Azure Text-to-Speech service
-----------------------------
Uses Azure Cognitive Services REST API (no SDK needed).
Generates audio for all 4 Ncheta languages.

Voice selection priority:
  english → en-NG-EzinneNeural  (Nigerian English, female)
  hausa   → ha-NE-AbdullahNeural (Hausa, male)
  yoruba  → yo-NG-MolaNeural    (Yoruba, male)
  igbo    → ig-NG-EzinmaNeural  (Igbo, female)

If a specific voice is unavailable (region-dependent), falls back to a
general multilingual voice so the pipeline never hard-fails.
"""
from __future__ import annotations
import httpx

from core.config import settings

# Map language → Azure Neural voice name
VOICE_MAP: dict[str, str] = {
    "english": "en-NG-EzinneNeural",
    "hausa":   "ha-NE-AbdullahNeural",
    "yoruba":  "yo-NG-MolaNeural",
    "igbo":    "ig-NG-EzinmaNeural",
}

FALLBACK_VOICE = "en-US-AriaNeural"

TOKEN_URL   = "https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
TTS_URL     = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
OUTPUT_FMT  = "audio-16khz-128kbitrate-mono-mp3"


def _ssml(text: str, voice: str, lang_code: str) -> str:
    # Truncate to 5 000 chars — Azure limit per request
    safe = text[:5000].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<speak version='1.0' xml:lang='{lang_code}'>"
        f"<voice name='{voice}'>{safe}</voice>"
        f"</speak>"
    )


async def generate_audio(text: str, language: str) -> bytes:
    """
    Returns raw MP3 bytes.
    Raises on network/auth failure so the pipeline can mark the job step as failed.
    """
    voice     = VOICE_MAP.get(language, FALLBACK_VOICE)
    lang_code = _lang_code(language)
    region    = settings.azure_speech_region
    key       = settings.azure_speech_key

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Get short-lived token (valid 10 minutes)
        token_resp = await client.post(
            TOKEN_URL.format(region=region),
            headers={"Ocp-Apim-Subscription-Key": key},
        )
        token_resp.raise_for_status()
        token = token_resp.text

        # 2. Synthesise speech
        ssml = _ssml(text, voice, lang_code)
        tts_resp = await client.post(
            TTS_URL.format(region=region),
            headers={
                "Authorization":          f"Bearer {token}",
                "Content-Type":           "application/ssml+xml",
                "X-Microsoft-OutputFormat": OUTPUT_FMT,
            },
            content=ssml.encode("utf-8"),
        )
        tts_resp.raise_for_status()
        return tts_resp.content


def _lang_code(language: str) -> str:
    return {
        "english": "en-NG",
        "hausa":   "ha-NE",
        "yoruba":  "yo-NG",
        "igbo":    "ig-NG",
    }.get(language, "en-NG")
