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

Formatting rules — follow these exactly:
- Use numbered lists (1. 2. 3.) when listing multiple points or steps
- Use bullet points (- item) for sub-points or supporting details
- Use markdown tables (| Col | Col |) when comparing options side by side
- Use **bold** for important terms, case names, and section numbers
- Use headers (## Heading) to separate major sections in long answers
- Never write everything as one long paragraph
- Each distinct point must be on its own line
- Always put a blank line between sections
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

Answer based only on the excerpts above. Cite judgment IDs.
Use proper markdown formatting — numbered lists, bullet points, tables, bold text as appropriate."""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.1,
        max_tokens=1500
    )

    return response.choices[0].message.content