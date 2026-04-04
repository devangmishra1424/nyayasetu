"""
LLM module. OpenRouter as primary, HuggingFace Inference API as fallback.
"""

import os
import logging
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()
logger = logging.getLogger(__name__)

# ── OpenRouter (primary) ──────────────────────────────────
_openrouter_client = None

# ── HuggingFace Inference API (fallback) ──────────────────
_hf_client = None


def _init_openrouter():
    global _openrouter_client
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — OpenRouter disabled")
        return False
    try:
        from openai import OpenAI
        _openrouter_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        logger.info("OpenRouter ready (primary)")
        return True
    except Exception as e:
        logger.error(f"OpenRouter init failed: {e}")
        return False


def _init_hf():
    global _hf_client
    token = os.getenv("HF_TOKEN")
    if not token:
        logger.warning("HF_TOKEN not set — HF Inference API disabled")
        return False
    try:
        from huggingface_hub import InferenceClient
        _hf_client = InferenceClient(
            model="meta-llama/Llama-3.3-70B-Instruct",
            token=token
        )
        logger.info("HF Inference API ready (fallback)")
        return True
    except Exception as e:
        logger.error(f"HF Inference API init failed: {e}")
        return False


_openrouter_ready = _init_openrouter()
_hf_ready = _init_hf()


def _call_openrouter(messages: list) -> str:
    """Call OpenRouter."""
    response = _openrouter_client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct:free",
        messages=messages,
        max_tokens=1500,
        temperature=0.3,
    )
    return response.choices[0].message.content


def _call_hf(messages: list) -> str:
    """Call HuggingFace Inference API."""
    response = _hf_client.chat_completion(
        messages=messages,
        max_tokens=1500,
        temperature=0.3,
    )
    return response.choices[0].message.content


def _call_with_fallback(messages: list) -> str:
    """Try OpenRouter first, then HF."""
    if _openrouter_ready and _openrouter_client:
        try:
            return _call_openrouter(messages)
        except Exception as e:
            logger.warning(f"OpenRouter failed: {e}, trying HF Inference")

    if _hf_ready and _hf_client:
        try:
            return _call_hf(messages)
        except Exception as e:
            logger.error(f"HF Inference also failed: {e}")

    raise Exception("All LLM providers failed")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
def call_llm_raw(messages: list) -> str:
    """
    Call LLM with pre-built messages list.
    Used by V2 agent for Pass 1 and Pass 3.
    """
    return _call_with_fallback(messages)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
def call_llm(query: str, context: str) -> str:
    """
    Call LLM with query and context.
    Used by V1 agent.
    """
    messages = [
        {
            "role": "system",
            "content": "You are NyayaSetu, an Indian legal research assistant. Answer only from provided excerpts. Cite judgment IDs. End with: NOTE: This is not legal advice."
        },
        {
            "role": "user",
            "content": f"QUESTION: {query}\n\nSOURCES:\n{context}\n\nAnswer based on sources. Cite judgment IDs."
        }
    ]
    return _call_with_fallback(messages)