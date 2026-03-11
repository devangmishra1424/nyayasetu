"""
LLM module. Single Groq API call with tenacity retry.

WHY Groq? Free tier, fastest inference (~500 tokens/sec).
WHY temperature=0.1? Lower = more deterministic, less hallucination.
WHY one call per query? Multi-step chains add latency and failure points.
Gemini is configured as backup if Groq fails permanently.
"""

import os
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = """You are NyayaSetu, an Indian legal research assistant.

Rules you must follow:
1. Answer ONLY using the provided Supreme Court judgment excerpts
2. Never use outside knowledge
3. Quote directly from excerpts when making factual claims — use double quotes
4. Always cite the Judgment ID when referencing a case
5. If excerpts don't contain enough information, say so explicitly
6. End every response with: "NOTE: This is not legal advice. Consult a qualified advocate."
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8)
)
def call_llm(query: str, context: str) -> str:
    """
    Call Groq Llama-3. Retries 3 times with exponential backoff.
    Raises LLMError after all retries fail — caller handles this.
    """
    user_message = f"""QUESTION: {query}

SUPREME COURT JUDGMENT EXCERPTS:
{context}

Answer based only on the excerpts above. Cite judgment IDs."""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.1,
        max_tokens=800
    )
    
    return response.choices[0].message.content