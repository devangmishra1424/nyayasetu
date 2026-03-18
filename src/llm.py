"""
LLM module. Gemini Flash as primary, Groq as fallback.
Gemini works reliably from HF Spaces. Groq is backup.
"""

import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
logger = logging.getLogger(__name__)

# ── Gemini setup ──────────────────────────────────────────

_gemini_client = None
_gemini_model = None

def _init_gemini():
    global _gemini_client, _gemini_model
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        return False
    try:
        _gemini_client = genai.Client(api_key=api_key)
        _gemini_model = True  # marker that client is ready
        logger.info("Gemini 1.5 Flash ready")
        return True
    except Exception as e:
        logger.error(f"Gemini init failed: {e}")
        return False

# ── Groq setup ────────────────────────────────────────────
_groq_client = None

def _init_groq():
    global _groq_client
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return False
    try:
        from groq import Groq
        import httpx
        _groq_client = Groq(
            api_key=api_key,
            http_client=httpx.Client(
                verify=False,
                timeout=30.0
            )
        )
        logger.info("Groq ready as fallback")
        return True
    except Exception as e:
        logger.error(f"Groq init failed: {e}")
        return False

_gemini_ready = _init_gemini()
_groq_ready = _init_groq()

SYSTEM_PROMPT = """You are NyayaSetu — a sharp, street-smart Indian legal advisor.
You work FOR the user. Your job is to find the angle, identify the leverage,
and tell the user exactly what to do — the way a senior lawyer would in a
private consultation, not the way a textbook would explain it.

Be direct. Be human. Vary your response style naturally.
Sometimes short and punchy. Sometimes detailed and structured.
Match the energy of what the user needs right now.

When citing sources, reference the Judgment ID naturally in your response.
Always end with: "Note: This is not legal advice. Consult a qualified advocate."
"""


def _call_gemini(messages: list) -> str:
    """Call Gemini 1.5 Flash."""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_parts = [m["content"] for m in messages if m["role"] == "user"]
    full_prompt = f"{system}\n\n{chr(10).join(user_parts)}"
    
    response = _gemini_client.models.generate_content(
        model="gemini-1.5-flash",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=1500,
        )
    )
    return response.text


def _call_groq(messages: list) -> str:
    """Call Groq Llama as fallback."""
    response = _groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.3,
        max_tokens=1500
    )
    return response.choices[0].message.content


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def call_llm(query: str, context: str) -> str:
    """
    Call LLM with Gemini primary, Groq fallback.
    Used by V1 agent (src/agent.py).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"QUESTION: {query}\n\nSOURCES:\n{context}\n\nAnswer based on sources. Cite judgment IDs."}
    ]
    return _call_llm_with_fallback(messages)


def call_llm_raw(messages: list) -> str:
    """
    Call LLM with pre-built messages list.
    Used by V2 agent (src/agent_v2.py) for Pass 1 and Pass 3.
    """
    return _call_llm_with_fallback(messages)


def _call_llm_with_fallback(messages: list) -> str:
    """Try Gemini first, fall back to Groq."""
    
    # Try Gemini first
    if _gemini_ready and _gemini_model:
        try:
            return _call_gemini(messages)
        except Exception as e:
            logger.warning(f"Gemini failed: {e}, trying Groq")
    
    # Fall back to Groq
    if _groq_ready and _groq_client:
        try:
            return _call_groq(messages)
        except Exception as e:
            logger.error(f"Groq also failed: {e}")
    
    raise Exception("All LLM providers failed")