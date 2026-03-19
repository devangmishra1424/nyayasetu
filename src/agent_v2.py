"""
NyayaSetu V2 Agent — Full Intelligence Layer.

Pass 1 — ANALYSE: Understands message, detects tone/stage,
         builds structured fact web, updates hypotheses,
         forms targeted search queries, compresses summary.

Pass 2 — RETRIEVE: Parallel FAISS search. No LLM call.

Pass 3 — RESPOND: Dynamically assembled prompt + retrieved
         context + full case state. Format-intelligent output.

2 LLM calls per turn. src/agent.py untouched.
"""

import os, sys, json, time, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List

# sys.path must be set before any local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.embed import embed_text
from src.retrieval import retrieve
from src.verify import verify_citations
from src.system_prompt import build_prompt, ANALYSIS_PROMPT
from src.ner import extract_entities, augment_query

logger = logging.getLogger(__name__)

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()
_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Session store ─────────────────────────────────────────
sessions: Dict[str, Dict] = {}


def empty_case_state() -> Dict:
    return {
        "parties": [],
        "events": [],
        "documents": [],
        "amounts": [],
        "locations": [],
        "timeline": [],
        "disputes": [],
        "hypotheses": [],
        "stage": "intake",
        "last_response_type": "none",
        "turn_count": 0,
        "facts_missing": [],
        "context_interpreted": False,
        "last_radar_turn": -3,   # track when radar last fired
    }


def get_or_create_session(session_id: str) -> Dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "summary": "",
            "last_3_messages": [],
            "case_state": empty_case_state()
        }
    return sessions[session_id]


def update_session(session_id: str, analysis: Dict, user_message: str, response: str):
    session = sessions[session_id]
    cs = session["case_state"]

    if analysis.get("updated_summary"):
        session["summary"] = analysis["updated_summary"]

    facts = analysis.get("facts_extracted", {})
    if facts:
        for key in ["parties", "events", "documents", "amounts", "locations", "disputes"]:
            new_items = facts.get(key, [])
            existing = cs.get(key, [])
            for item in new_items:
                if item and item not in existing:
                    existing.append(item)
            cs[key] = existing

        for ev in facts.get("timeline_events", []):
            if ev and ev not in cs["timeline"]:
                cs["timeline"].append(ev)

    for nh in analysis.get("hypotheses", []):
        existing_claims = [h["claim"] for h in cs["hypotheses"]]
        if nh.get("claim") and nh["claim"] not in existing_claims:
            cs["hypotheses"].append(nh)
        else:
            for h in cs["hypotheses"]:
                if h["claim"] == nh.get("claim"):
                    h["confidence"] = nh.get("confidence", h["confidence"])
                    for e in nh.get("evidence", []):
                        if e not in h.get("evidence", []):
                            h.setdefault("evidence", []).append(e)

    cs["stage"] = analysis.get("stage", cs["stage"])
    cs["last_response_type"] = analysis.get("action_needed", "none")
    cs["facts_missing"] = analysis.get("facts_missing", [])
    cs["turn_count"] = cs.get("turn_count", 0) + 1

    if cs["turn_count"] >= 3:
        cs["context_interpreted"] = True

    session["last_3_messages"].append({"role": "user", "content": user_message})
    session["last_3_messages"].append({"role": "assistant", "content": response[:400]})
    if len(session["last_3_messages"]) > 6:
        session["last_3_messages"] = session["last_3_messages"][-6:]


# ── Pass 1: Analyse ───────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4))
def analyse(user_message: str, session: Dict) -> Dict:
    summary = session.get("summary", "")
    last_msgs = session.get("last_3_messages", [])
    cs = session["case_state"]
    last_response_type = cs.get("last_response_type", "none")
    turn_count = cs.get("turn_count", 0)

    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content'][:250]}"
        for m in last_msgs[-4:]
    ) if last_msgs else ""

    fact_web = ""
    if any(cs.get(k) for k in ["parties", "events", "documents", "amounts", "disputes"]):
        hyp_lines = "\n".join(
            f"  - {h['claim']} [{h.get('confidence','?')}]"
            for h in cs.get("hypotheses", [])[:3]
        ) or "  none yet"
        fact_web = f"""
CURRENT FACT WEB:
- Parties: {', '.join(cs.get('parties', [])) or 'none'}
- Events: {', '.join(cs.get('events', [])) or 'none'}
- Documents/Evidence: {', '.join(cs.get('documents', [])) or 'none'}
- Amounts: {', '.join(cs.get('amounts', [])) or 'none'}
- Disputes: {', '.join(cs.get('disputes', [])) or 'none'}
- Active hypotheses:
{hyp_lines}"""

    user_content = f"""CONVERSATION SUMMARY:
{summary if summary else "First message — no prior context."}

RECENT MESSAGES:
{history_text if history_text else "None"}

LAST RESPONSE TYPE: {last_response_type}
TURN COUNT: {turn_count}
{fact_web}

NEW USER MESSAGE:
{user_message}

Rules:
- If last_response_type was "question", action_needed CANNOT be "question"
- action_needed SHOULD differ from last_response_type for variety
- Extract ALL facts from user message even if implied
- Update hypothesis confidence based on new evidence
- search_queries must be specific legal questions for vector search"""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": ANALYSIS_PROMPT},
            {"role": "user", "content": user_content}
        ],
        temperature=0.1,
        max_tokens=900
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        analysis = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Pass 1 JSON parse failed: {raw[:200]}")
        analysis = {
            "tone": "casual", "format_requested": "none",
            "subject": "legal query", "action_needed": "advice",
            "urgency": "medium",
            "hypotheses": [{"claim": user_message[:80], "confidence": "low", "evidence": []}],
            "facts_extracted": {}, "facts_missing": [],
            "legal_issues": [], "clarifying_question": {},
            "stage": "understanding", "last_response_type": last_response_type,
            "updated_summary": f"{summary} | {user_message[:100]}",
            "search_queries": [user_message[:200]],
            "should_interpret_context": False,
            "format_decision": "none"
        }

    return analysis


# ── Pass 2: Retrieve ──────────────────────────────────────
def retrieve_parallel(search_queries: List[str], top_k: int = 5) -> List[Dict]:
    if not search_queries:
        return []

    all_results = []

    def search_one(query):
        try:
            embedding = embed_text(query)
            return retrieve(embedding, top_k=top_k)
        except Exception as e:
            logger.warning(f"FAISS search failed: {e}")
            return []

    with ThreadPoolExecutor(max_workers=min(3, len(search_queries))) as executor:
        futures = {executor.submit(search_one, q): q for q in search_queries}
        for future in as_completed(futures):
            all_results.extend(future.result())

    seen = {}
    for chunk in all_results:
        cid = chunk.get("chunk_id") or chunk.get("judgment_id", "")
        score = chunk.get("similarity_score", 999)
        if cid not in seen or score < seen[cid]["similarity_score"]:
            seen[cid] = chunk

    return sorted(seen.values(), key=lambda x: x.get("similarity_score", 999))[:top_k]


# ── Pass 3: Respond ───────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
def respond(user_message: str, analysis: Dict, chunks: List[Dict], session: Dict) -> str:
    system_prompt = build_prompt(analysis)
    cs = session["case_state"]
    turn_count = cs.get("turn_count", 0)

    context_parts = []
    for chunk in chunks[:5]:
        source_type = chunk.get("source_type", "case_law")
        title = chunk.get("title", "Unknown")
        year = chunk.get("year", "")
        jid = chunk.get("judgment_id", "")
        text = chunk.get("expanded_context") or chunk.get("chunk_text") or chunk.get("text", "")

        type_labels = {
            "statute": f"[STATUTE: {title} | {year}]",
            "procedure": f"[PROCEDURE: {title}]",
            "law_commission": f"[LAW COMMISSION: {title}]",
            "legal_reference": f"[LEGAL REFERENCE: {title}]",
            "statute_qa": f"[LEGAL QA: {title}]",
        }
        header = type_labels.get(source_type, f"[CASE: {title} | {year} | {jid}]")
        context_parts.append(f"{header}\n{text[:800]}")

    context = "\n\n".join(context_parts) if context_parts else "No relevant sources retrieved."

    case_summary = ""
    if cs.get("parties") or cs.get("hypotheses"):
        hyp_text = "\n".join(
            f"  - {h['claim']} [{h.get('confidence','?')} confidence] "
            f"| evidence: {', '.join(h.get('evidence', [])) or 'none yet'}"
            for h in cs.get("hypotheses", [])[:4]
        ) or "  none established"

        case_summary = f"""
CASE STATE (built across {turn_count} turns):
Parties: {', '.join(cs.get('parties', [])) or 'unspecified'}
Events: {', '.join(cs.get('events', [])) or 'unspecified'}
Evidence: {', '.join(cs.get('documents', [])) or 'none mentioned'}
Amounts: {', '.join(cs.get('amounts', [])) or 'none'}
Active hypotheses:
{hyp_text}
Missing facts: {', '.join(cs.get('facts_missing', [])) or 'none critical'}
Stage: {cs.get('stage', 'intake')}"""

    # Context interpretation — only once per conversation at turn 2
    interpret_instruction = ""
    should_interpret = analysis.get("should_interpret_context", False)
    if should_interpret and not cs.get("context_interpreted") and turn_count == 2:
        interpret_instruction = "\nIn one sentence only, reflect back your understanding of the situation before responding."

    # Radar — only fires every 3 turns, not every turn
    last_radar_turn = cs.get("last_radar_turn", -3)
    if (turn_count - last_radar_turn) >= 3:
        cs["last_radar_turn"] = turn_count
        radar_instruction = """
PROACTIVE RADAR — only if a genuinely non-obvious legal angle exists that hasn't been mentioned yet:
Add a single "⚡ You Should Also Know:" line (1-2 sentences max).
Skip entirely if the response already covers all relevant angles or if this is a question/understanding turn."""
    else:
        radar_instruction = "Do NOT add a 'You Should Also Know' section this turn."

    summary = session.get("summary", "")
    last_msgs = session.get("last_3_messages", [])
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content'][:300]}"
        for m in last_msgs[-4:]
    ) if last_msgs else ""

    user_content = f"""CONVERSATION SUMMARY:
{summary if summary else "First message."}

RECENT CONVERSATION:
{history_text if history_text else "None"}
{case_summary}

RETRIEVED LEGAL SOURCES:
{context}

USER MESSAGE: {user_message}

THIS TURN:
- Legal hypotheses: {', '.join(h['claim'] for h in analysis.get('hypotheses', [])[:3]) or 'analysing'}
- Stage: {analysis.get('stage', 'understanding')}
- Urgency: {analysis.get('urgency', 'medium')}
- Response type: {analysis.get('action_needed', 'advice')}
- Format: {analysis.get('format_decision', 'appropriate for content')}
{interpret_instruction}

Instructions:
- Cite specific sources when making legal claims
- Use your legal knowledge for reasoning and context
- Format: {analysis.get('format_decision', 'use the most appropriate format for the content type')}
- Opposition war-gaming: if giving strategy, include what the other side will argue
{radar_instruction}"""

    response = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=0.3,
        max_tokens=1500
    )
    return response.choices[0].message.content


# ── Main entry point ──────────────────────────────────────
def run_query_v2(user_message: str, session_id: str) -> Dict[str, Any]:
    start = time.time()
    session = get_or_create_session(session_id)

    # Pass 1
    try:
        analysis = analyse(user_message, session)
    except Exception as e:
        logger.error(f"Pass 1 failed: {e}")
        analysis = {
            "tone": "casual", "format_requested": "none",
            "subject": "legal query", "action_needed": "advice",
            "urgency": "medium",
            "hypotheses": [{"claim": user_message[:80], "confidence": "low", "evidence": []}],
            "facts_extracted": {}, "facts_missing": [],
            "legal_issues": [], "clarifying_question": {},
            "stage": "understanding", "last_response_type": "none",
            "updated_summary": user_message[:200],
            "search_queries": [user_message[:200]],
            "should_interpret_context": False,
            "format_decision": "none"
        }

    # Extract entities and augment queries for better retrieval
    entities = extract_entities(user_message)
    augmented_message = augment_query(user_message, entities)

    # Pass 2 — build search queries from analysis + legal issues
    search_queries = analysis.get("search_queries", [augmented_message])
    if not search_queries:
        search_queries = [augmented_message]

    # Add queries from issue spotter
    for issue in analysis.get("legal_issues", []):
        statutes = issue.get("relevant_statutes", [])
        specific = issue.get("specific_issue", "")
        if specific:
            issue_query = f"{specific} {' '.join(statutes[:2])}".strip()
            if issue_query not in search_queries:
                search_queries.append(issue_query)

    if augmented_message not in search_queries:
        search_queries.append(augmented_message)

    chunks = []
    try:
        # Retrieve more candidates for reranker to work with
        raw_chunks = retrieve_parallel(search_queries[:3], top_k=10)
        
        # Rerank candidates by true relevance
        from src.reranker import rerank
        chunks = rerank(user_message, raw_chunks, top_k=5)
        
        # Add precedent chain
        from src.citation_graph import get_precedent_chain
        retrieved_ids = [c.get("judgment_id", "") for c in chunks]
        precedents = get_precedent_chain(retrieved_ids, max_precedents=2)
        if precedents:
            chunks.extend(precedents)
    except Exception as e:
        logger.error(f"Pass 2 failed: {e}")

    # Pass 3
    try:
        answer = respond(user_message, analysis, chunks, session)
    except Exception as e:
        logger.error(f"Pass 3 failed: {e}")
        if chunks:
            fallback = "\n\n".join(
                f"[{c.get('title', 'Source')}]\n{c.get('text', '')[:400]}"
                for c in chunks[:3]
            )
            answer = f"LLM service temporarily unavailable. Most relevant excerpts:\n\n{fallback}"
        else:
            answer = "I encountered an issue processing your request. Please try again."

    verification_status, unverified_quotes = verify_citations(answer, chunks)
    update_session(session_id, analysis, user_message, answer)

    sources = []
    for c in chunks:
        title = c.get("title", "")
        jid = c.get("judgment_id", "")
        sources.append({
            "meta": {
                "judgment_id": jid,
                "title": title if title and title != jid else jid,
                "year": c.get("year", ""),
                "chunk_index": c.get("chunk_index", 0),
                "source_type": c.get("source_type", "case_law"),
                "court": c.get("court", "Supreme Court of India")
            },
            "text": (c.get("expanded_context") or c.get("chunk_text") or c.get("text", ""))[:600]
        })

    return {
        "query": user_message,
        "answer": answer,
        "sources": sources,
        "verification_status": verification_status,
        "unverified_quotes": unverified_quotes,
        "entities": entities,
        "num_sources": len(chunks),
        "truncated": False,
        "session_id": session_id,
        "analysis": {
            "tone": analysis.get("tone"),
            "stage": analysis.get("stage"),
            "urgency": analysis.get("urgency"),
            "hypotheses": [h["claim"] for h in analysis.get("hypotheses", [])]
        }
    }