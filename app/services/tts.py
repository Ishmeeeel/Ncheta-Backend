"""
TTS Service — uses edge-tts (Microsoft Edge's free neural TTS, no API key).
Falls back to Azure Speech REST API using the user's AZURE_SPEECH_KEY if needed.

Voice map:
  english → en-NG-EzinneNeural   Nigerian English (female)
  hausa   → ha-NE-AbdullahNeural Hausa (male)
  yoruba  → en-NG-AbeoNeural     Nigerian English variant (best available)
  igbo    → en-NG-EzinneNeural   Nigerian English variant (best available)

Note: Hausa, Yoruba, Igbo native Neural voices are in Microsoft preview.
      We use edge-tts which automatically gets the best available voice.
"""
import asyncio
import os
import tempfile
import httpx
from app.config import settings

VOICE_MAP = {
    "english": "en-NG-EzinneNeural",
    "hausa":   "ha-NE-AbdullahNeural",
    "yoruba":  "yo-NG-BandeNeural",
    "igbo":    "ig-NG-EzinneNeural",
}

# Fallback voices if the above are not available in edge-tts
FALLBACK_VOICE_MAP = {
    "english": "en-GB-SoniaNeural",
    "hausa":   "en-NG-EzinneNeural",
    "yoruba":  "en-NG-EzinneNeural",
    "igbo":    "en-NG-EzinneNeural",
}


async def generate_audio_edge_tts(text: str, language: str) -> bytes:
    """
    Generate audio using edge-tts (free, no API key).
    Returns raw MP3 bytes.
    """
    try:
        import edge_tts

        voice = VOICE_MAP.get(language, "en-NG-EzinneNeural")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            communicate = edge_tts.Communicate(text=text, voice=voice)
            await communicate.save(tmp_path)

            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as primary_error:
        # Try fallback voice
        try:
            import edge_tts

            voice = FALLBACK_VOICE_MAP.get(language, "en-GB-SoniaNeural")

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                communicate = edge_tts.Communicate(text=text, voice=voice)
                await communicate.save(tmp_path)

                with open(tmp_path, "rb") as f:
                    return f.read()
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except Exception:
            # Final fallback: Azure Speech REST API
            return await generate_audio_azure_rest(text, language)


async def generate_audio_azure_rest(text: str, language: str) -> bytes:
    """
    Azure Speech REST API fallback.
    POST to the TTS endpoint with SSML payload.
    """
    voice = VOICE_MAP.get(language, "en-NG-EzinneNeural")
    region = settings.azure_speech_region

    ssml = f"""<speak version='1.0' xml:lang='en-NG'>
    <voice name='{voice}'>
        {text}
    </voice>
</speak>"""

    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        "User-Agent": "Ncheta-TTS/1.0",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, content=ssml.encode("utf-8"), headers=headers)
        response.raise_for_status()
        return response.content


async def generate_audio(text: str, language: str) -> bytes:
    """Public interface — always returns MP3 bytes or raises."""
    return await generate_audio_edge_tts(text, language)
