"""
NyayaSetu FastAPI application — V2.
3 endpoints + static frontend serving.
V2 agent with conversation memory and 3-pass reasoning.
Port 7860 for HuggingFace Spaces compatibility.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Union, Optional
import time
import os
import sys
import logging
import json
from collections import Counter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from src.logger import log_inference

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def download_models():
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        logger.warning("HF_TOKEN not set — skipping model download.")
        return
    try:
        from huggingface_hub import snapshot_download, hf_hub_download
        repo_id = "CaffeinatedCoding/nyayasetu-models"

        if not os.path.exists("models/ner_model"):
            logger.info("Downloading NER model...")
            os.makedirs("models/ner_model", exist_ok=True)
            # NER model files — explicit downloads to avoid snapshot_download pattern bugs
            ner_files = [
                "config.json", "model.safetensors", "tokenizer.json", 
                "tokenizer_config.json", "training_args.bin", "training_results.json"
            ]
            for fname in ner_files:
                try:
                    hf_hub_download(
                        repo_id=repo_id, filename=f"ner_model/{fname}",
                        repo_type="model", local_dir="models", token=hf_token
                    )
                except Exception as e:
                    logger.warning(f"Could not download ner_model/{fname}: {e}")
            logger.info("NER model downloaded")
        else:
            logger.info("NER model already exists")

        if not os.path.exists("models/faiss_index/index.faiss"):
            logger.info("Downloading FAISS index...")
            os.makedirs("models/faiss_index", exist_ok=True)
            # Download FAISS files explicitly to avoid snapshot_download pattern issues
            faiss_files = ["index.faiss", "chunk_metadata.jsonl"]
            for fname in faiss_files:
                try:
                    hf_hub_download(repo_id=repo_id, filename=f"faiss_index/{fname}",
                                    repo_type="model", local_dir="models", token=hf_token)
                except Exception as fe:
                    logger.warning(f"Could not download faiss_index/{fname}: {fe}")
            logger.info("FAISS index downloaded")
        else:
            logger.info("FAISS index already exists")

        if not os.path.exists("data/parent_judgments.jsonl"):
            logger.info("Downloading parent judgments...")
            os.makedirs("data", exist_ok=True)
            hf_hub_download(repo_id=repo_id, filename="parent_judgments.jsonl",
                            repo_type="model", local_dir="data", token=hf_token)
            logger.info("Parent judgments downloaded")
        else:
            logger.info("Parent judgments already exist")

        # Download citation graph artifacts — only if Kaggle run has completed
        os.makedirs("data", exist_ok=True)
        for fname in ["citation_graph.json", "reverse_citation_graph.json", "title_to_id.json"]:
            if not os.path.exists(f"data/{fname}"):
                logger.info(f"Downloading {fname}...")
                try:
                    hf_hub_download(repo_id=repo_id, filename=fname,
                                    repo_type="model", local_dir="data", token=hf_token)
                    logger.info(f"{fname} downloaded")
                except Exception as fe:
                    logger.warning(f"{fname} not on Hub yet — skipping: {fe}")

    except Exception as e:
        logger.error(f"Model download failed: {e}")


download_models()

# NER is optional enhancement — skip on HF Spaces to save memory
# The app works fine without NER; it just doesn't extract entities
SPACE_ID = os.getenv("SPACE_ID", "")  # HF Spaces sets this
if SPACE_ID:
    logger.info("Running on HF Spaces — skipping NER to save memory")
else:
    from src.ner import load_ner_model
    load_ner_model()

from src.reranker import load_reranker
load_reranker()

from src.citation_graph import load_citation_graph
load_citation_graph()

# Load court sessions from HuggingFace dataset on startup
from src.court.session import load_sessions_from_hf
load_sessions_from_hf()

AGENT_VERSION = os.getenv("AGENT_VERSION", "v2")

if AGENT_VERSION == "v2":
    logger.info("Loading V2 agent (3-pass reasoning loop)")
    from src.agent_v2 import run_query_v2 as _run_query
    USE_V2 = True
else:
    logger.info("Loading V1 agent (single-pass)")
    from src.agent import run_query as _run_query_v1
    USE_V2 = False

app = FastAPI(title="NyayaSetu", description="Indian Legal RAG Agent", version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    query: str
    answer: str
    sources: list
    verification_status: Union[str, bool]
    unverified_quotes: list
    entities: dict
    num_sources: int
    truncated: bool
    latency_ms: float
    session_id: Optional[str] = None


@app.get("/")
def serve_frontend():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return {"name": "NyayaSetu", "version": "2.0.0", "agent": AGENT_VERSION}


@app.get("/health")
def health():
    from src.agent_v2 import _circuit_breaker
    return {
        "status": "ok",
        "service": "NyayaSetu",
        "version": "2.0.0",
        "agent": AGENT_VERSION,
        "groq_circuit_breaker": _circuit_breaker.get_status()
    }


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, background_tasks: BackgroundTasks):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if len(request.query) < 10:
        raise HTTPException(status_code=400, detail="Query too short — minimum 10 characters")
    if len(request.query) > 1000:
        raise HTTPException(status_code=400, detail="Query too long — maximum 1000 characters")
    
    start = time.time()
    try:
        if USE_V2:
            session_id = request.session_id or "default"
            result = _run_query(request.query, session_id)
        else:
            result = _run_query_v1(request.query)
            session_id = "v1"
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
    
    latency_ms = round((time.time() - start) * 1000, 2)
    result["latency_ms"] = latency_ms
    result["session_id"] = session_id

    # Log inference as background task — non-blocking
    background_tasks.add_task(
        log_inference,
        query=request.query,
        session_id=session_id,
        answer=result.get("answer", ""),
        num_sources=result.get("num_sources", 0),
        verification_status=result.get("verification_status", False),
        entities=result.get("entities", {}),
        latency_ms=latency_ms,
        stage=result.get("analysis", {}).get("stage", ""),
        truncated=result.get("truncated", False),
        out_of_domain=result.get("num_sources", 0) == 0,
    )

    return result


@app.get("/analytics")
def analytics():
    """Return aggregated analytics from inference logs."""
    log_path = os.getenv("LOG_PATH", "logs/inference.jsonl")
    
    if not os.path.exists(log_path):
        return {
            "total_queries": 0,
            "verified_ratio": 0,
            "avg_latency_ms": 0,
            "out_of_domain_rate": 0,
            "avg_sources": 0,
            "stage_distribution": {},
            "entity_type_frequency": {},
            "recent_latencies": [],
        }
    
    records = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        return {"error": "Could not read logs"}
    
    if not records:
        return {"total_queries": 0}
    
    total = len(records)
    verified = sum(1 for r in records if r.get("verified", False))
    out_of_domain = sum(1 for r in records if r.get("out_of_domain", False))
    latencies = [r.get("latency_ms", 0) for r in records if r.get("latency_ms")]
    sources = [r.get("num_sources", 0) for r in records]
    stages = Counter(r.get("stage", "unknown") for r in records)
    
    all_entity_types = []
    for r in records:
        all_entity_types.extend(r.get("entities_found", []))
    entity_freq = dict(Counter(all_entity_types).most_common(10))
    
    return {
        "total_queries": total,
        "verified_ratio": round(verified / total * 100, 1) if total else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 0) if latencies else 0,
        "out_of_domain_rate": round(out_of_domain / total * 100, 1) if total else 0,
        "avg_sources": round(sum(sources) / len(sources), 1) if sources else 0,
        "stage_distribution": dict(stages),
        "entity_type_frequency": entity_freq,
        "recent_latencies": latencies[-20:],
    }


# ── COURT ENDPOINTS ────────────────────────────────────────────

from api.court_schemas import (
    NewSessionRequest, ImportSessionRequest, ArgueRequest,
    ObjectionRequest, DocumentRequest, EndSessionRequest,
    RoundResponse, SessionSummary
)


@app.post("/court/new")
def court_new_session(request: NewSessionRequest):
    """Start a fresh moot court session."""
    from src.court.session import create_session
    from src.court.brief import generate_fresh_brief
    from src.court.registrar import build_round_announcement
    
    case_brief = generate_fresh_brief(
        case_title=request.case_title,
        user_side=request.user_side,
        user_client=request.user_client,
        opposing_party=request.opposing_party,
        legal_issues=request.legal_issues,
        brief_facts=request.brief_facts,
        jurisdiction=request.jurisdiction,
    )
    
    session_id = create_session(
        case_title=request.case_title,
        user_side=request.user_side,
        user_client=request.user_client,
        opposing_party=request.opposing_party,
        legal_issues=request.legal_issues,
        brief_facts=request.brief_facts,
        jurisdiction=request.jurisdiction,
        bench_composition=request.bench_composition,
        difficulty=request.difficulty,
        session_length=request.session_length,
        show_trap_warnings=request.show_trap_warnings,
        case_brief=case_brief,
    )
    
    # Registrar opens the session
    from src.court.session import get_session, add_transcript_entry
    session = get_session(session_id)
    opening = build_round_announcement(session, 0, "briefing")
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=opening,
        entry_type="announcement",
    )
    
    return {
        "session_id": session_id,
        "case_brief": case_brief,
        "opening_announcement": opening,
        "phase": "briefing",
    }


@app.post("/court/import")
def court_import_session(request: ImportSessionRequest):
    """Import a NyayaSetu research session into Moot Court."""
    from src.court.session import create_session, add_transcript_entry
    from src.court.brief import generate_case_brief
    from src.court.registrar import build_round_announcement
    from src.agent_v2 import sessions as research_sessions
    
    research_session = research_sessions.get(request.research_session_id)
    if not research_session:
        raise HTTPException(status_code=404, detail="Research session not found")
    
    case_state = research_session.get("case_state", {})
    
    case_brief = generate_case_brief(research_session, request.user_side)
    
    # Extract case details from research session
    parties = case_state.get("parties", [])
    case_title = f"{parties[0]} vs {parties[1]}" if len(parties) >= 2 else "Present Matter"
    legal_issues_raw = research_session.get("case_state", {}).get("disputes", [])
    
    session_id = create_session(
        case_title=case_title,
        user_side=request.user_side,
        user_client=parties[0] if parties else "Petitioner",
        opposing_party=parties[1] if len(parties) > 1 else "Respondent",
        legal_issues=legal_issues_raw[:5],
        brief_facts=research_session.get("summary", ""),
        jurisdiction="supreme_court",
        bench_composition=request.bench_composition,
        difficulty=request.difficulty,
        session_length=request.session_length,
        show_trap_warnings=request.show_trap_warnings,
        imported_from_session=request.research_session_id,
        case_brief=case_brief,
    )
    
    from src.court.session import get_session
    session = get_session(session_id)
    opening = build_round_announcement(session, 0, "briefing")
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=opening,
        entry_type="announcement",
    )
    
    return {
        "session_id": session_id,
        "case_brief": case_brief,
        "opening_announcement": opening,
        "phase": "briefing",
        "imported_from": request.research_session_id,
    }


@app.post("/court/argue")
def court_argue(request: ArgueRequest):
    """Submit an argument or answer during the session."""
    from src.court.orchestrator import process_user_argument
    
    if not request.session_id or not request.argument.strip():
        raise HTTPException(status_code=400, detail="Session ID and argument required")
    
    result = process_user_argument(request.session_id, request.argument)
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@app.post("/court/object")
def court_object(request: ObjectionRequest):
    """Raise an objection."""
    from src.court.orchestrator import process_objection
    
    result = process_objection(
        request.session_id,
        request.objection_type,
        request.objection_text,
    )
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@app.post("/court/document")
def court_document(request: DocumentRequest):
    """Generate and produce a legal document."""
    from src.court.orchestrator import process_document_request
    
    result = process_document_request(
        request.session_id,
        request.doc_type,
        request.for_side,
    )
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@app.post("/court/end")
def court_end_session(request: EndSessionRequest):
    """End the session and generate full analysis."""
    from src.court.orchestrator import generate_session_analysis
    from src.court.session import get_session
    
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session["phase"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Session is in phase '{session['phase']}' — complete closing arguments first"
        )
    
    analysis = generate_session_analysis(request.session_id)
    
    if "error" in analysis:
        raise HTTPException(status_code=500, detail=analysis["error"])
    
    return analysis


@app.get("/court/session/{session_id}")
def court_get_session(session_id: str):
    """Get full session data including transcript."""
    from src.court.session import get_session
    
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return session


@app.get("/court/sessions")
def court_list_sessions():
    """List all sessions."""
    from src.court.session import get_all_sessions
    
    sessions = get_all_sessions()
    
    # Return summary only
    summaries = []
    for s in sessions:
        summaries.append({
            "session_id": s["session_id"],
            "case_title": s["case_title"],
            "user_side": s["user_side"],
            "phase": s["phase"],
            "current_round": s["current_round"],
            "max_rounds": s["max_rounds"],
            "created_at": s["created_at"],
            "updated_at": s["updated_at"],
            "outcome_prediction": s.get("outcome_prediction"),
            "performance_score": s.get("performance_score"),
            "concession_count": len(s.get("concessions", [])),
            "trap_count": len(s.get("trap_events", [])),
        })
    
    return {"sessions": summaries, "total": len(summaries)}


@app.post("/court/cross_exam/start")
def court_start_cross_exam(session_id: str):
    """Manually trigger cross-examination phase."""
    from src.court.orchestrator import start_cross_examination
    
    result = start_cross_examination(session_id)
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result