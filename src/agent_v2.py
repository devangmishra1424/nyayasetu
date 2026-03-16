"""
NyayaSetu V2 Agent — 3-pass reasoning loop.

Pass 1 — ANALYSE: LLM call to understand the message,
         detect tone/format/stage, form search queries,
         update conversation summary.

Pass 2 — RETRIEVE: Parallel FAISS search using queries
         from Pass 1. No LLM call. Pure vector search.

Pass 3 — RESPOND: LLM call with dynamically assembled
         prompt + retrieved context + conversation state.

2 LLM calls per turn maximum.
src/agent.py is untouched — this is additive.
"""

import os
import sys
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.embed import embed_text
from src.retrieval import retrieve
from src.verify import verify_citations
from src.system_prompt import build_prompt, ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

# ── Groq client (same as llm.py) ──────────────────────────
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()
_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── In-memory session store ───────────────────────────────
# Resets on container restart — acceptable for free tier
sessions: Dict[str, Dict] = {}


def get_or_create_session(session_id: str) -> Dict:
    """Get existing session or create a fresh one."""
    if session_id not in sessions:
        sessions[session_id] = {
            "summary": "",
            "last_3_messages": [],
            "case_state": {
                "facts_established": [],
                "facts_missing": [],
                "hypotheses": [],
                "retrieved_cases": [],
                "stage": "intake",
                "last_response_type": "none"
            }
        }
    return sessions[session_id]


def update_session(session_id: str, analysis: Dict, user_message: str, response: str):
    """Update session state after each turn."""
    session = sessions[session_id]

    # Update summary from Pass 1 output
    if analysis.get("updated_summary"):
        session["summary"] = analysis["updated_summary"]

    # Keep only last 3 messages
    session["last_3_messages"].append({"role": "user", "content": user_message})
    session["last_3_messages"].append({"role": "assistant", "content": response})
    if len(session["last_3_messages"]) > 6:  # 3 pairs = 6 messages
        session["last_3_messages"] = session["last_3_messages"][-6:]

    # Update case state
    cs = session["case_state"]
    cs["stage"] = analysis.get("stage", cs["stage"])
    cs["last_response_type"] = analysis.get("action_needed", "none")

    if analysis.get("facts_missing"):
        cs["facts_missing"] = analysis["facts_missing"]

    if analysis.get("legal_hypotheses"):
        for h in analysis["legal_hypotheses"]:
            if h not in cs["hypotheses"]:
                cs["hypotheses"].append(h)


# ── Pass 1: Analyse ───────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4))
def analyse(user_message: str, session: Dict) -> Dict:
    """
    LLM call 1: Understand the message, detect intent,
    form search queries, update summary.
    Returns structured analysis dict.
    """
    summary = session.get("summary", "")
    last_msgs = session.get("last_3_messages", [])
    last_response_type = session["case_state"].get("last_response_type", "none")

    # Build context for analysis
    history_text = ""
    if last_msgs:
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in last_msgs[-4:]  # last 2 turns
        )

    user_content = f"""CONVERSATION SUMMARY:
{summary if summary else "No previous context — this is the first message."}

RECENT MESSAGES:
{history_text if history_text else "None"}

LAST RESPONSE TYPE: {last_response_type}

NEW USER MESSAGE:
{user_message}

Remember: If last_response_type was "question", action_needed CANNOT be "question"."""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": ANALYSIS_PROMPT},
            {"role": "user", "content": user_content}
        ],
        temperature=0.1,
        max_tokens=600
    )

    raw = response.choices[0].message.content.strip()

    # Parse JSON — strip any accidental markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        analysis = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Pass 1 JSON parse failed: {raw[:200]}")
        # Fallback analysis
        analysis = {
            "tone": "casual",
            "format_requested": "none",
            "subject": "legal query",
            "action_needed": "advice",
            "urgency": "medium",
            "legal_hypotheses": [user_message[:100]],
            "facts_missing": [],
            "stage": "understanding",
            "last_response_type": last_response_type,
            "updated_summary": f"{summary} User asked: {user_message[:100]}",
            "search_queries": [user_message[:200]]
        }

    return analysis


# ── Pass 2: Retrieve ──────────────────────────────────────
def retrieve_parallel(search_queries: List[str], top_k: int = 5) -> List[Dict]:
    """
    Run multiple FAISS queries in parallel.
    Merge results, deduplicate by chunk_id, re-rank by score.
    Returns top_k unique chunks.
    """
    if not search_queries:
        return []

    all_results = []

    def search_one(query):
        try:
            embedding = embed_text(query)
            results = retrieve(embedding, top_k=top_k)
            return results
        except Exception as e:
            logger.warning(f"FAISS search failed for query '{query[:50]}': {e}")
            return []

    # Run queries in parallel
    with ThreadPoolExecutor(max_workers=min(3, len(search_queries))) as executor:
        futures = {executor.submit(search_one, q): q for q in search_queries}
        for future in as_completed(futures):
            results = future.result()
            all_results.extend(results)

    # Deduplicate by chunk_id, keep best score
    seen = {}
    for chunk in all_results:
        cid = chunk.get("chunk_id") or chunk.get("judgment_id", "")
        score = chunk.get("similarity_score", 0)
        if cid not in seen or score < seen[cid]["similarity_score"]:
            seen[cid] = chunk

    # Sort by score (lower L2 = more similar) and return top_k
    unique_chunks = sorted(seen.values(), key=lambda x: x.get("similarity_score", 999))
    return unique_chunks[:top_k]


# ── Pass 3: Respond ───────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
def respond(
    user_message: str,
    analysis: Dict,
    chunks: List[Dict],
    session: Dict
) -> str:
    """
    LLM call 2: Generate the final response.
    Uses dynamically assembled prompt based on analysis.
    """
    # Build dynamic system prompt
    system_prompt = build_prompt(analysis)

    # Build context from retrieved chunks
    context_parts = []
    for i, chunk in enumerate(chunks[:5], 1):
        source_type = chunk.get("source_type", "case_law")
        title = chunk.get("title", "Unknown")
        year = chunk.get("year", "")
        jid = chunk.get("judgment_id", "")
        text = chunk.get("expanded_context") or chunk.get("chunk_text") or chunk.get("text", "")

        if source_type == "statute":
            header = f"[STATUTE: {title} | {year}]"
        elif source_type == "procedure":
            header = f"[PROCEDURE: {title}]"
        elif source_type == "law_commission":
            header = f"[LAW COMMISSION: {title}]"
        elif source_type == "legal_reference":
            header = f"[LEGAL REFERENCE: {title}]"
        else:
            header = f"[CASE: {title} | {year} | ID: {jid}]"

        context_parts.append(f"{header}\n{text[:800]}")

    context = "\n\n".join(context_parts) if context_parts else "No relevant sources retrieved."

    # Build conversation context
    summary = session.get("summary", "")
    last_msgs = session.get("last_3_messages", [])

    history_text = ""
    if last_msgs:
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}"
            for m in last_msgs[-4:]
        )

    user_content = f"""CONVERSATION CONTEXT:
{summary if summary else "First message in this conversation."}

RECENT CONVERSATION:
{history_text if history_text else "No previous messages."}

RETRIEVED LEGAL SOURCES:
{context}

USER MESSAGE: {user_message}

ANALYSIS:
- Legal issues identified: {', '.join(analysis.get('legal_hypotheses', [])[:3])}
- Stage: {analysis.get('stage', 'understanding')}
- Urgency: {analysis.get('urgency', 'medium')}
- Response type needed: {analysis.get('action_needed', 'advice')}

Respond now. Use only the retrieved sources for specific legal citations.
Your own legal knowledge can be used for general reasoning and context."""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=0.3,
        max_tokens=1200
    )

    return response.choices[0].message.content


# ── Main entry point ──────────────────────────────────────
def run_query_v2(user_message: str, session_id: str) -> Dict[str, Any]:
    """
    Main V2 pipeline. 3 passes per query.
    Returns structured response dict compatible with existing API schema.
    """
    start = time.time()

    # Get or create session
    session = get_or_create_session(session_id)

    # ── Pass 1: Analyse ────────────────────────────────────
    try:
        analysis = analyse(user_message, session)
    except Exception as e:
        logger.error(f"Pass 1 failed: {e}")
        analysis = {
            "tone": "casual",
            "format_requested": "none",
            "subject": "legal query",
            "action_needed": "advice",
            "urgency": "medium",
            "legal_hypotheses": [user_message[:100]],
            "facts_missing": [],
            "stage": "understanding",
            "last_response_type": "none",
            "updated_summary": user_message[:200],
            "search_queries": [user_message[:200]]
        }

    # ── Pass 2: Retrieve ───────────────────────────────────
    search_queries = analysis.get("search_queries", [user_message])
    if not search_queries:
        search_queries = [user_message]

    # Add original message as fallback query
    if user_message not in search_queries:
        search_queries.append(user_message)

    chunks = []
    try:
        chunks = retrieve_parallel(search_queries[:3], top_k=5)
    except Exception as e:
        logger.error(f"Pass 2 retrieval failed: {e}")

    # ── Pass 3: Respond ────────────────────────────────────
    try:
        answer = respond(user_message, analysis, chunks, session)
    except Exception as e:
        logger.error(f"Pass 3 failed: {e}")
        if chunks:
            fallback = "\n\n".join(
                f"[{c.get('title', 'Source')}]\n{(c.get('expanded_context') or c.get('chunk_text') or c.get('text', ''))[:400]}"
                for c in chunks[:3]
            )
            answer = f"I encountered an issue generating a response. Here are the most relevant sources I found:\n\n{fallback}"
        else:
            answer = "I encountered an issue processing your request. Please try again."

    # ── Verification ───────────────────────────────────────
    verification_status, unverified_quotes = verify_citations(answer, chunks)

    # ── Update session ─────────────────────────────────────
    update_session(session_id, analysis, user_message, answer)

    # ── Build response ─────────────────────────────────────
    sources = []
    for c in chunks:
        sources.append({
            "meta": {
                "judgment_id": c.get("judgment_id", ""),
                "year": c.get("year", ""),
                "chunk_index": c.get("chunk_index", 0),
                "source_type": c.get("source_type", "case_law"),
                "title": c.get("title", "")
            },
            "text": (c.get("expanded_context") or c.get("chunk_text") or c.get("text", ""))[:600]
        })

    return {
        "query": user_message,
        "answer": answer,
        "sources": sources,
        "verification_status": verification_status,
        "unverified_quotes": unverified_quotes,
        "entities": {},
        "num_sources": len(chunks),
        "truncated": len(chunks) < len(search_queries),
        "session_id": session_id,
        "analysis": {
            "tone": analysis.get("tone"),
            "stage": analysis.get("stage"),
            "urgency": analysis.get("urgency"),
            "hypotheses": analysis.get("legal_hypotheses", [])
        }
    }