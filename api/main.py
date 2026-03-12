"""
NyayaSetu FastAPI application.
3 endpoints only.

All models loaded at startup — never per request.
Port 7860 for HuggingFace Spaces compatibility.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.agent import run_query

app = FastAPI(
    title="NyayaSetu",
    description="Indian Legal RAG Agent — Supreme Court Judgments 1950–2024",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── Request/Response models ───────────────────────────
class QueryRequest(BaseModel):
    query: str

class SourceItem(BaseModel):
    judgment_id: str
    title: str
    year: str
    similarity_score: float
    excerpt: str

class QueryResponse(BaseModel):
    query: str
    answer: str
    sources: list
    verification_status: str
    unverified_quotes: list
    entities: dict
    num_sources: int
    truncated: bool
    latency_ms: float


# ── Endpoint 1: Health check ──────────────────────────
@app.get("/health")
def health():
    """
    Used by GitHub Actions smoke test after every deploy.
    If this returns anything other than 200, deploy is failed.
    """
    return {
        "status": "ok",
        "service": "NyayaSetu",
        "version": "1.0.0"
    }


# ── Endpoint 2: App info ──────────────────────────────
@app.get("/")
def root():
    return {
        "name": "NyayaSetu",
        "description": "Indian Legal RAG Agent",
        "data": "Supreme Court of India judgments 1950-2024",
        "disclaimer": "NOT legal advice. Always consult a qualified advocate.",
        "endpoints": {
            "POST /query": "Ask a legal question",
            "GET /health": "Health check",
            "GET /": "This info page"
        }
    }


# ── Endpoint 3: Main query pipeline ──────────────────
@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """
    Main pipeline endpoint.
    Takes a legal question, returns cited answer.
    """
    # Validation
    if not request.query.strip():
        raise HTTPException(
            status_code=400,
            detail="Query cannot be empty"
        )

    if len(request.query) < 10:
        raise HTTPException(
            status_code=400,
            detail="Query too short — minimum 10 characters"
        )

    if len(request.query) > 1000:
        raise HTTPException(
            status_code=400,
            detail="Query too long — maximum 1000 characters"
        )

    # Run pipeline
    start = time.time()
    try:
        result = run_query(request.query)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline error: {str(e)}"
        )

    result["latency_ms"] = round((time.time() - start) * 1000, 2)
    return result