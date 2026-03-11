"""
FAISS retrieval module.

Loads the FAISS index and chunk metadata once at startup.
Given a query embedding, returns the top-k most similar chunks
plus an expanded context window from the parent judgment.

WHY load at startup and not per request?
Loading a 650MB index takes ~3 seconds. If you loaded it per request,
every user query would take 3+ seconds just for setup. Loading once
at startup means retrieval takes ~5ms per query.
"""

import json
import numpy as np
import faiss
import os
from typing import List, Dict

INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "models/faiss_index/index.faiss")
METADATA_PATH = os.getenv("METADATA_PATH", "models/faiss_index/chunk_metadata.jsonl")
PARENT_PATH = os.getenv("PARENT_PATH", "data/parent_judgments.jsonl")
TOP_K = 5

# Similarity threshold — if best score is below this, query is out of domain
# Score range: 0 to 1 (cosine similarity with normalized vectors)
# 0.3 = very loose match, 0.5 = decent match, 0.7 = strong match
SIMILARITY_THRESHOLD = 0.35

def _load_resources():
    """Load index, metadata and parent store. Called once at module import."""
    
    print("Loading FAISS index...")
    index = faiss.read_index(INDEX_PATH)
    print(f"Index loaded: {index.ntotal} vectors")
    
    print("Loading chunk metadata...")
    metadata = []
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        for line in f:
            metadata.append(json.loads(line))
    print(f"Metadata loaded: {len(metadata)} chunks")
    
    print("Loading parent judgments...")
    parent_store = {}
    with open(PARENT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            parent = json.loads(line)
            parent_store[parent["judgment_id"]] = parent["text"]
    print(f"Parent store loaded: {len(parent_store)} judgments")
    
    return index, metadata, parent_store

_index, _metadata, _parent_store = _load_resources()


def retrieve(query_embedding: np.ndarray, top_k: int = TOP_K) -> List[Dict]:
    """
    Find top-k chunks most similar to the query embedding.
    Returns empty list if best score is below SIMILARITY_THRESHOLD
    (meaning the query is likely out of domain).
    """
    query_vec = query_embedding.reshape(1, -1).astype(np.float32)
    scores, indices = _index.search(query_vec, top_k)
    
    # Check if best match is above threshold
    best_score = float(scores[0][0])
    if best_score < SIMILARITY_THRESHOLD:
        return []  # Out of domain — agent will handle this
    
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        
        chunk = _metadata[idx]
        expanded = _get_expanded_context(
            chunk["judgment_id"],
            chunk["text"]
        )
        
        results.append({
            "chunk_id": chunk["chunk_id"],
            "judgment_id": chunk["judgment_id"],
            "title": chunk.get("title", ""),
            "year": chunk.get("year", ""),
            "chunk_text": chunk["text"],
            "expanded_context": expanded,
            "similarity_score": float(score)
        })
    
    return results


def _get_expanded_context(judgment_id: str, chunk_text: str) -> str:
    """
    Get ~1024 token window from parent judgment centred on the chunk.
    Falls back to chunk text if parent not found.

    WHY expand context?
    The chunk is 512 tokens — enough for retrieval.
    But the LLM needs more surrounding context to give a complete answer.
    We go back to the full judgment and extract a wider window.
    """
    parent_text = _parent_store.get(judgment_id, "")
    if not parent_text:
        return chunk_text
    
    # Find chunk position in parent
    anchor = chunk_text[:80]
    start_pos = parent_text.find(anchor)
    if start_pos == -1:
        return chunk_text
    
    # ~4 chars per token, 1024 tokens = ~4096 chars
    WINDOW = 4096
    expand_start = max(0, start_pos - WINDOW // 4)
    expand_end = min(len(parent_text), start_pos + WINDOW)
    
    return parent_text[expand_start:expand_end]