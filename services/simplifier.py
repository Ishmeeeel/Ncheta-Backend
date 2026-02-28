"""
Text simplification service
----------------------------
Calls HuggingFace Inference API with Mistral-7B-Instruct to produce
a simplified version of lesson content for students with dyslexia.

Strategy:
  - Prompt is instruction-tuned (Mistral chat format)
  - Input truncated to 1 500 chars to stay within model context
  - If the API call fails, returns the original text (never hard-fails)
"""
from __future__ import annotations
import httpx

from core.config import settings

HF_MODEL  = "mistralai/Mistral-7B-Instruct-v0.1"
HF_URL    = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
MAX_INPUT = 1500
MAX_NEW   = 600


def _build_prompt(text: str) -> str:
    safe = text[:MAX_INPUT].strip()
    return (
        "<s>[INST] You are an educational assistant helping students with dyslexia. "
        "Rewrite the following lesson text using:\n"
        "- Short sentences (max 15 words)\n"
        "- Simple, everyday vocabulary\n"
        "- Clear structure with numbered steps when possible\n"
        "- No jargon unless it is explained\n\n"
        f"Original text:\n{safe}\n\n"
        "Simplified text: [/INST]"
    )


async def simplify_text(text: str) -> str:
    """Returns simplified text. Falls back to original on error."""
    if not text or not text.strip():
        return text

    prompt = _build_prompt(text)
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens":  MAX_NEW,
            "temperature":     0.3,
            "do_sample":       True,
            "return_full_text": False,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(HF_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list) and data:
                generated = data[0].get("generated_text", "")
                # Strip any residual prompt echo
                if "[/INST]" in generated:
                    generated = generated.split("[/INST]", 1)[-1]
                result = generated.strip()
                return result if result else text

            return text
    except Exception:
        # Simplification is non-critical — never break the pipeline
        return text


async def generate_image_description(page_text: str) -> str:
    """
    Generates an alt-text-style image/content description
    for the visual impairment mode.
    """
    prompt = (
        "<s>[INST] Write a concise audio description (2-3 sentences) of the following "
        "educational content as if describing it to a blind student. "
        "Focus on the key concepts and any implied visuals.\n\n"
        f"Content:\n{page_text[:800]}\n\n"
        "Audio description: [/INST]"
    )
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 150, "temperature": 0.4, "return_full_text": False},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(HF_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                desc = data[0].get("generated_text", "").strip()
                if "[/INST]" in desc:
                    desc = desc.split("[/INST]", 1)[-1].strip()
                return desc
    except Exception:
        pass

    return f"This page covers: {page_text[:200]}..."
