"""
NyayaSetu FastAPI application — V2.
3 endpoints + static frontend serving.
V2 agent with conversation memory and 3-pass reasoning.
Port 7860 for HuggingFace Spaces compatibility.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Union, Optional
import time
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            snapshot_download(
                repo_id=repo_id, repo_type="model",
                allow_patterns="ner_model/*", local_dir="models", token=hf_token
            )
            logger.info("NER model downloaded")
        else:
            logger.info("NER model already exists")

        if not os.path.exists("models/faiss_index/index.faiss"):
            logger.info("Downloading FAISS index...")
            os.makedirs("models/faiss_index", exist_ok=True)
            hf_hub_download(repo_id=repo_id, filename="faiss_index/index.faiss",
                            repo_type="model", local_dir="models", token=hf_token)
            hf_hub_download(repo_id=repo_id, filename="faiss_index/chunk_metadata.jsonl",
                            repo_type="model", local_dir="models", token=hf_token)
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

from src.ner import load_ner_model
load_ner_model()

from src.citation_graph import load_citation_graph
load_citation_graph()

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


@app.get("/")
def serve_frontend():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return {"name": "NyayaSetu", "version": "2.0.0", "agent": AGENT_VERSION}


@app.get("/health")
def health():
    return {"status": "ok", "service": "NyayaSetu", "version": "2.0.0", "agent": AGENT_VERSION}


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
        if USE_V2:
            session_id = request.session_id or "default"
            result = _run_query(request.query, session_id)
        else:
            result = _run_query_v1(request.query)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
    result["latency_ms"] = round((time.time() - start) * 1000, 2)
    return result