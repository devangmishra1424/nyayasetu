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
SIMILARITY_THRESHOLD = 0.72  # cosine similarity — tunable


def _normalise(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_quotes(text: str) -> list:
    """Extract quoted phrases and key sentences from answer."""
    quotes = []

    # Extract explicitly quoted phrases
    patterns = [
        r'"([^"]{15,})"',
        r'\u201c([^\u201d]{15,})\u201d',
    ]
    for pattern in patterns:
        found = re.findall(pattern, text)
        quotes.extend(found)

    # If no explicit quotes, extract key sentences for verification
    if not quotes:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        # Take sentences that make specific legal claims
        for s in sentences:
            s = s.strip()
            # Sentences with section numbers, case citations, or specific claims
            if (len(s) > 40 and
                any(indicator in s.lower() for indicator in [
                    "section", "act", "ipc", "crpc", "court held",
                    "judgment", "article", "rule", "according to",
                    "as per", "under", "punishable", "imprisonment"
                ])):
                quotes.append(s)
                if len(quotes) >= 3:  # cap at 3 sentences
                    break

    return quotes


def _get_embedder():
    """Get the already-loaded embedder — no double loading."""
    try:
        from src.retrieval import _embedder as embedder
        return embedder
    except ImportError:
        pass

    try:
        from src.embed import _model as embedder
        return embedder
    except ImportError:
        pass

    try:
        # Last resort — import from retrieval module globals
        import src.retrieval as retrieval_module
        if hasattr(retrieval_module, '_embedder'):
            return retrieval_module._embedder
        if hasattr(retrieval_module, 'embedder'):
            return retrieval_module.embedder
    except Exception:
        pass

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
    """
    embedder = _get_embedder()
    if embedder is None:
        # Fallback to exact matching if embedder unavailable
        all_text = " ".join(_normalise(c.get("text", "")) for c in contexts)
        return _normalise(quote) in all_text

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
        logger.warning(f"Semantic verification failed: {e}, falling back to exact match")
        all_text = " ".join(_normalise(c.get("text", "")) for c in contexts)
        return _normalise(quote) in all_text


def verify_citations(answer: str, contexts: list) -> tuple:
    """
    Verify whether answer claims are grounded in retrieved contexts.

    Uses semantic similarity (cosine > 0.72) instead of exact matching.

    Returns:
        (verified: bool, unverified_quotes: list[str])

    Logic:
        - Extract quoted phrases and key legal claim sentences
        - If no verifiable claims: return (True, [])
        - For each claim: check semantic similarity against all context chunks
        - If ALL claims verified: (True, [])
        - If ANY claim unverified: (False, [list of unverified claims])
    """
    if not contexts:
        return False, []

    quotes = _extract_quotes(answer)

    if not quotes:
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