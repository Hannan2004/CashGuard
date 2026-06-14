import json
import os
import re

from langchain_google_genai import ChatGoogleGenerativeAI

_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

_llm: ChatGoogleGenerativeAI | None = None


def _get_llm() -> ChatGoogleGenerativeAI:
    """Lazily build the Gemini client so importing this module never fails
    just because the API key isn't set yet (useful for tests)."""
    global _llm

    if _llm is None:
        api_key = os.environ.get("GOOGLE_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Add it to your .env file."
            )

        _llm = ChatGoogleGenerativeAI(
            model=_MODEL_NAME,
            google_api_key=api_key,
            temperature=0,
        )

    return _llm


def call_gemini(prompt: str) -> str:
    """Send a plain-text prompt to Gemini and return the text response."""
    llm = _get_llm()
    response = llm.invoke(prompt)
    return response.content


def call_gemini_json(prompt: str) -> dict:
    """Send a prompt that asks Gemini for JSON, and parse the result safely.

    Gemini sometimes wraps JSON in ```json ... ``` fences even when told not
    to, so we strip those before parsing. If parsing still fails, we return
    a dict with an "error" key instead of raising, so a single bad LLM
    response doesn't crash the whole graph run.
    """
    raw = call_gemini(prompt)
    cleaned = raw.strip()

    # Strip markdown code fences like ```json ... ``` or ``` ... ```
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "Failed to parse JSON from Gemini response", "raw": raw}