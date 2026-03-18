"""
LLM module. Single Groq API call with tenacity retry.

WHY Groq? Free tier, fastest inference (~500 tokens/sec).
WHY temperature=0.1? Lower = more deterministic, less hallucination.
WHY one call per query? Multi-step chains add latency and failure points.
"""

import os
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def call_llm_raw(messages: list) -> str:
    """
    Call Groq with pre-built messages list.
    Used by V2 agent for Pass 1 and Pass 3.
    """
    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.3,
        max_tokens=1500
    )
    return response.choices[0].message.content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8)
)
def call_llm(query: str, context: str) -> str:
    """
    Call Groq Llama-3. Used by V1 agent.
    Retries 3 times with exponential backoff.
    """
    user_message = f"""QUESTION: {query}

SUPREME COURT JUDGMENT EXCERPTS:
{context}

Answer based only on the excerpts above. Cite judgment IDs.
Use proper markdown formatting."""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are NyayaSetu, an Indian legal research assistant. Answer only from provided excerpts. Cite judgment IDs. End with: NOTE: This is not legal advice."},
            {"role": "user", "content": user_message}
        ],
        temperature=0.1,
        max_tokens=1500
    )

    return response.choices[0].message.content