"""
NyayaSetu FastAPI application.
3 endpoints + static frontend serving.
All models loaded at startup — never per request.
Port 7860 for HuggingFace Spaces compatibility.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import time
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Startup: Download models from HuggingFace Hub ────────────────
def download_models():
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        logger.warning("HF_TOKEN not set — skipping model download.")
        return

    try:
        from huggingface_hub import snapshot_download, hf_hub_download
        repo_id = "CaffeinatedCoding/nyayasetu-models"

        # NER model
        if not os.path.exists("models/ner_model"):
            logger.info("Downloading NER model from HuggingFace Hub...")
            snapshot_download(
                repo_id=repo_id,
                repo_type="model",
                allow_patterns="ner_model/*",
                local_dir="models",
                token=hf_token
            )
            logger.info("NER model downloaded successfully")
        else:
            logger.info("NER model already exists, skipping download")

        # FAISS index + chunk metadata
        if not os.path.exists("models/faiss_index/index.faiss"):
            logger.info("Downloading FAISS index from HuggingFace Hub...")
            os.makedirs("models/faiss_index", exist_ok=True)
            hf_hub_download(
                repo_id=repo_id,
                filename="faiss_index/index.faiss",
                repo_type="model",
                local_dir="models",
                token=hf_token
            )
            hf_hub_download(
                repo_id=repo_id,
                filename="faiss_index/chunk_metadata.jsonl",
                repo_type="model",
                local_dir="models",
                token=hf_token
            )
            logger.info("FAISS index downloaded successfully")
        else:
            logger.info("FAISS index already exists, skipping download")

        # Parent judgments
        if not os.path.exists("data/parent_judgments.jsonl"):
            logger.info("Downloading parent judgments from HuggingFace Hub...")
            os.makedirs("data", exist_ok=True)
            hf_hub_download(
                repo_id=repo_id,
                filename="parent_judgments.jsonl",
                repo_type="model",
                local_dir="data",
                token=hf_token
            )
            logger.info("Parent judgments downloaded successfully")
        else:
            logger.info("Parent judgments already exist, skipping download")

    except Exception as e:
        logger.error(f"Model download failed: {e}")
        logger.error("App will start but pipeline may fail if models are missing")

# Run at startup before importing pipeline
download_models()

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

# Serve frontend static files
if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")

# ── Request/Response models ──────────────────────────────────────
class QueryRequest(BaseModel):
    query: str

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


# ── Endpoint 1: Serve frontend ───────────────────────────────────
@app.get("/")
def serve_frontend():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return {
        "name": "NyayaSetu",
        "description": "Indian Legal RAG Agent",
        "data": "Supreme Court of India judgments 1950-2024",
        "disclaimer": "NOT legal advice. Always consult a qualified advocate.",
        "endpoints": {
            "POST /query": "Ask a legal question",
            "GET /health": "Health check",
            "GET /": "This page"
        }
    }


# ── Endpoint 2: Health check ─────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "NyayaSetu",
        "version": "1.0.0"
    }


# ── Endpoint 3: Main query pipeline ──────────────────────────────
@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if len(request.query) < 10:
        raise HTTPException(status_code=400, detail="Query too short — minimum 10 characters")

    if len(request.query) > 1000:
        raise HTTPException(status_code=400, detail="Query too long — maximum 1000 characters")

    start = time.time()
    try:
        result = run_query(request.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")

    result["latency_ms"] = round((time.time() - start) * 1000, 2)
    return result