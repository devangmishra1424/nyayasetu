"""
Cross-encoder reranker.
Reranks FAISS retrieval results by true query-document relevance.

WHY cross-encoder over bi-encoder (MiniLM)?
MiniLM embeds query and document independently — fast but approximate.
Cross-encoder sees query+document together — slower but much more accurate.
Used post-retrieval on top-15 candidates to select best top-5.

WHY ms-marco-MiniLM-L-6-v2?
Trained on MS-MARCO passage ranking — transfers well to legal QA.
Small enough to load on HF Spaces free tier (~80MB).
Fast enough for reranking 15 candidates in ~200ms on CPU.

Interview answer:
"I added a cross-encoder reranker post-retrieval to boost precision@5
by focusing on true relevance rather than embedding similarity alone.
Legal domain papers show 8-15% precision lift from reranking."
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

_reranker = None
_reranker_loaded = False


def load_reranker():
    """
    Load cross-encoder once at startup.
    Fails gracefully — retrieval works without reranker.
    Call from api/main.py after other models load.
    """
    global _reranker, _reranker_loaded

    try:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder reranker...")
        _reranker = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            max_length=512
        )
        _reranker_loaded = True
        logger.info("Cross-encoder reranker ready")
    except Exception as e:
        logger.warning(f"Reranker load failed: {e}. Retrieval will use FAISS scores only.")
        _reranker_loaded = False


def rerank(query: str, chunks: List[Dict], top_k: int = 5) -> List[Dict]:
    """
    Rerank chunks by cross-encoder relevance score.

    Args:
        query: user query string
        chunks: list of retrieved chunks from FAISS
        top_k: number of top chunks to return after reranking

    Returns:
        top_k chunks sorted by reranker score descending.
        If reranker not loaded, returns original chunks[:top_k].
    """
    if not _reranker_loaded or _reranker is None:
        return chunks[:top_k]

    if not chunks:
        return []

    try:
        # Build query-document pairs
        pairs = []
        for chunk in chunks:
            text = (
                chunk.get("expanded_context") or
                chunk.get("chunk_text") or
                chunk.get("text", "")
            )[:512]
            pairs.append([query, text])

        # Score all pairs
        scores = _reranker.predict(pairs, batch_size=16)

        # Attach scores and sort
        for chunk, score in zip(chunks, scores):
            chunk["reranker_score"] = float(score)

        reranked = sorted(chunks, key=lambda x: x.get("reranker_score", 0), reverse=True)
        
        logger.info(
            f"Reranked {len(chunks)} chunks → top {top_k}. "
            f"Top score: {reranked[0].get('reranker_score', 0):.3f}"
        )
        
        return reranked[:top_k]

    except Exception as e:
        logger.warning(f"Reranking failed: {e}. Using FAISS order.")
        return chunks[:top_k]


def is_loaded() -> bool:
    return _reranker_loaded
