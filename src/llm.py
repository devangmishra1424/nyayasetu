"""
LLM module. Single DeepSeek API call with tenacity retry.

WHY DeepSeek? Free tier, cost-effective inference.
WHY temperature=0.1? Lower = more deterministic, less hallucination.
WHY one call per query? Multi-step chains add latency and failure points.
"""

import os
import logging
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

api_key = os.getenv("DEEPSEEK_API_KEY")
logger.info(f"DEEPSEEK_API_KEY loaded: {bool(api_key)} (length: {len(api_key) if api_key else 0})")

_client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com/v1"
)
logger.info("DeepSeek client initialized successfully")


def call_llm_raw(messages: list) -> str:
    """
    Call DeepSeek with pre-built messages list.
    Used by V2 agent for Pass 1 and Pass 3.
    """
    try:
        response = _client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error in call_llm_raw: {type(e).__name__}: {str(e)}", exc_info=True)
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8)
)
def call_llm(query: str, context: str) -> str:
    """
    Call DeepSeek. Used by V1 agent.
    Retries 3 times with exponential backoff.
    """
    try:
        user_message = f"""QUESTION: {query}

SUPREME COURT JUDGMENT EXCERPTS:
{context}

Answer based only on the excerpts above. Cite judgment IDs.
Use proper markdown formatting."""

        response = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are NyayaSetu, an Indian legal research assistant. Answer only from provided excerpts. Cite judgment IDs. End with: NOTE: This is not legal advice."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            max_tokens=1500
        )

        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error in call_llm: {type(e).__name__}: {str(e)}", exc_info=True)
        raise