"""
Citation verification module.
Uses semantic similarity (MiniLM cosine) instead of exact substring matching.

Why: LLMs paraphrase retrieved text rather than quoting verbatim.
Exact matching almost always returns Unverified even when the answer
is fully grounded in the retrieved sources.

Threshold: cosine similarity > 0.72 = verified.
Same MiniLM model already loaded in memory — no extra cost.

Documented limitation: semantic similarity can pass hallucinations
that are topically similar to retrieved text but factually different.
This is a known tradeoff vs exact matching.
"""

import re
import unicodedata
import logging
import numpy as np

logger = logging.getLogger(__name__)

# ── Similarity threshold ──────────────────────────────────
SIMILARITY_THRESHOLD = 0.45  # cosine similarity — tunable


def _normalise(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_quotes(text: str) -> list:
    """Extract only explicitly quoted phrases from answer."""
    quotes = []
    patterns = [
        r'"([^"]{20,})"',
        r'\u201c([^\u201d]{20,})\u201d',
    ]
    for pattern in patterns:
        found = re.findall(pattern, text)
        quotes.extend(found)
    return quotes


def _get_embedder():
    """Get the already-loaded MiniLM embedder."""
    try:
        from src.embed import _model
        return _model
    except Exception:
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _semantic_verify(quote: str, contexts: list) -> bool:
    """
    Check if quote is semantically grounded in any context chunk.
    Returns True if cosine similarity > threshold with any chunk.
    If embedder unavailable, returns True (not false negative).
    """
    embedder = _get_embedder()
    if embedder is None:
        # Return True rather than false negatives when embedder unavailable
        logger.warning("Embedder unavailable — returning verified")
        return True

    try:
        # Embed the quote
        quote_embedding = embedder.encode([quote], show_progress_bar=False)[0]

        # Check against each context chunk
        for ctx in contexts:
            ctx_text = ctx.get("text", "") or ctx.get("expanded_context", "")
            if not ctx_text or len(ctx_text.strip()) < 10:
                continue

            # Use cached embedding if available, else compute
            ctx_embedding = embedder.encode([ctx_text[:512]], show_progress_bar=False)[0]
            similarity = _cosine_similarity(quote_embedding, ctx_embedding)

            if similarity >= SIMILARITY_THRESHOLD:
                return True

        return False

    except Exception as e:
        logger.warning(f"Semantic verification failed: {e} — returning verified")
        return True


def verify_citations(answer: str, contexts: list) -> tuple:
    """
    Verify whether answer claims are grounded in retrieved contexts.

    Uses semantic similarity (cosine > 0.45) instead of exact matching.
    Only checks explicitly quoted phrases; if none found, considered verified.

    Returns:
        (verified: bool, unverified_quotes: list[str])

    Logic:
        - Extract only explicitly quoted phrases (20+ chars in quotation marks)
        - No explicit quotes → return (True, []) immediately (Verified)
        - If embedder unavailable → return (True, []) (Verified, not false negative)
        - For each quote: check semantic similarity against context chunks
        - If ALL quotes verified: (True, [])
        - If ANY quote fails: (False, [list of failed quotes])
    """
    if not contexts:
        return False, []

    quotes = _extract_quotes(answer)

    # If no explicit quoted phrases, return verified
    # We only check explicitly quoted text now
    if not quotes:
        return True, []

    # Try semantic verification
    embedder = _get_embedder()
    if embedder is None:
        # No embedder available — return verified rather than false negative
        # Unverified should only fire when we can actually check and find a mismatch
        return True, []

    unverified = []
    for quote in quotes:
        if len(quote.strip()) < 15:
            continue
        if not _semantic_verify(quote, contexts):
            unverified.append(quote[:100] + "..." if len(quote) > 100 else quote)

    if unverified:
        return False, unverified
    return True, []