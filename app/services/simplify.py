"""
Text simplification service using HuggingFace Inference API.
Transforms complex lesson text into plain, step-by-step language
for students with dyslexia or cognitive disabilities.

Uses Mistral-7B-Instruct — fast, free tier, 30k requests/month.
"""
import httpx
from app.config import settings

HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
HF_URL   = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

SYSTEM_PROMPT = """You are an expert at simplifying educational text for students with dyslexia.

Your rules:
1. Use very short sentences (max 12 words each)
2. Break everything into numbered steps where possible
3. Use simple, everyday words — no jargon
4. Add blank lines between paragraphs
5. Start each new idea on a new line
6. Use active voice always
7. Maximum readability: target a 9-year-old reading level
8. Keep all key facts accurate — only simplify the language, not the content
9. Do NOT use bullet points — use numbered steps or short paragraphs
10. Output ONLY the simplified text — no preamble, no explanation"""


async def simplify_text(text: str) -> str:
    """
    Simplify educational text using Mistral-7B via HuggingFace Inference API.
    Returns simplified text string.
    Falls back to a basic rule-based simplifier if API fails.
    """
    prompt = f"<s>[INST] {SYSTEM_PROMPT}\n\nSimplify this text:\n\n{text} [/INST]"

    headers = {
        "Authorization": f"Bearer {settings.huggingface_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 600,
            "temperature": 0.3,
            "return_full_text": False,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(HF_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and data:
                return data[0].get("generated_text", "").strip()

            return _fallback_simplify(text)

    except Exception:
        return _fallback_simplify(text)


def _fallback_simplify(text: str) -> str:
    """
    Basic rule-based fallback when HuggingFace is unavailable.
    Splits long sentences at conjunctions and adds structure.
    """
    sentences = text.replace(". ", ".\n").split("\n")
    simplified = []

    for i, sentence in enumerate(sentences, 1):
        sentence = sentence.strip()
        if not sentence:
            continue
        # Break at conjunctions for shorter sentences
        parts = sentence.replace(", and ", ".\n").replace(", but ", ".\nBut ").split("\n")
        for part in parts:
            part = part.strip()
            if part:
                simplified.append(f"Step {i}: {part}" if i <= 3 else part)

    return "\n\n".join(simplified) if simplified else text


async def generate_image_description(context: str, image_placeholder: str = "") -> str:
    """
    Generate an accessibility description for a lesson image using Mistral.
    Used in Visual Impairment mode to describe diagrams and illustrations.
    """
    prompt = f"""<s>[INST] You are writing alt-text descriptions for educational images for blind students.
    
Given this lesson context: {context[:500]}

Write a clear, detailed description (2-3 sentences) of what an educational diagram for this topic would show.
Start with: "Diagram showing..." 
Be specific about what arrows, labels, and visual elements would appear.
Output ONLY the description. [/INST]"""

    headers = {
        "Authorization": f"Bearer {settings.huggingface_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 150, "temperature": 0.4, "return_full_text": False},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(HF_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and data:
                return data[0].get("generated_text", "").strip()
    except Exception:
        pass

    return f"🔊 Diagram showing the main concepts from this lesson section."
