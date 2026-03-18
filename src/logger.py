"""
Inference logger.
Writes one JSON line per query to logs/inference.jsonl.
Called as FastAPI BackgroundTask — does not block response.

WHY two-layer logging?
HF Spaces containers are ephemeral — local files are wiped on restart.
Local JSONL is fast for same-session analytics.
In future, add HF Dataset API push here for durable storage.
"""

import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

LOG_PATH = os.getenv("LOG_PATH", "logs/inference.jsonl")


def ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def log_inference(
    query: str,
    session_id: str,
    answer: str,
    num_sources: int,
    verification_status,
    entities: dict,
    latency_ms: float,
    stage: str = "",
    truncated: bool = False,
    out_of_domain: bool = False,
):
    """
    Write one inference record to logs/inference.jsonl.
    Called as BackgroundTask in api/main.py.
    Fails silently — never blocks or crashes the main response.
    """
    try:
        ensure_log_dir()
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "query_length": len(query),
            "query_hash": hash(query) % 100000,
            "num_sources": num_sources,
            "verification_status": str(verification_status),
            "verified": verification_status is True or verification_status == "verified",
            "entities_found": list(entities.keys()) if entities else [],
            "num_entity_types": len(entities) if entities else 0,
            "latency_ms": latency_ms,
            "stage": stage,
            "truncated": truncated,
            "out_of_domain": out_of_domain,
            "answer_length": len(answer),
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.warning(f"Inference logging failed: {e}")
