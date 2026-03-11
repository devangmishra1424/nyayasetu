"""
NyayaSetu RAG Agent — single-pass function.

Every user query goes through exactly these steps in order:
1. NER extraction (if model available, else skip gracefully)
2. Query augmentation (append extracted entities)
3. Embed augmented query with MiniLM
4. FAISS retrieval (top-5 chunks)
5. Out-of-domain check (empty results = no relevant judgments)
6. Context assembly (build prompt context from expanded windows)
7. Single LLM call with retry
8. Citation verification
9. Return structured result

WHY single-pass and no while loop?
A while loop that retries the whole pipeline masks failures.
If retrieval returned bad results, retrying with the same query
returns the same bad results. Better to fail honestly and tell
the user, than to loop silently and return garbage.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.embed import embed_text
from src.retrieval import retrieve
from src.llm import call_llm
from src.verify import verify_citations
from typing import Dict, Any

# NER is optional — if not trained yet, pipeline runs without it
# This is the Cut Line Rule from the blueprint:
# ship without NER rather than blocking the whole project
NER_AVAILABLE = False
try:
    from src.ner import extract_entities
    NER_AVAILABLE = True
    print("NER model loaded — query augmentation active")
except Exception as e:
    print(f"NER not available, running without entity augmentation: {e}")


def run_query(query: str) -> Dict[str, Any]:
    """
    Main pipeline. Input: user query string.
    Output: structured dict with answer, sources, verification.
    """

    # ── Step 1: NER ──────────────────────────────────────────
    entities = {}
    augmented_query = query

    if NER_AVAILABLE:
        try:
            entities = extract_entities(query)
            entity_string = " ".join(
                f"{etype}: {etext}"
                for etype, texts in entities.items()
                for etext in texts
            )
            if entity_string:
                augmented_query = f"{query} {entity_string}"
        except Exception as e:
            print(f"NER failed, using raw query: {e}")
            augmented_query = query

    # ── Step 2: Embed ─────────────────────────────────────────
    query_embedding = embed_text(augmented_query)

    # ── Step 3: Retrieve ──────────────────────────────────────
    retrieved_chunks = retrieve(query_embedding, top_k=5)

    # ── Step 4: Out-of-domain check ───────────────────────────
    if not retrieved_chunks:
        return {
            "query": query,
            "augmented_query": augmented_query,
            "answer": "No relevant Supreme Court judgments found for your query. "
                      "Please rephrase or ask a question about Indian law.",
            "sources": [],
            "verification_status": "No sources retrieved",
            "unverified_quotes": [],
            "entities": entities,
            "num_sources": 0,
            "truncated": False
        }

    # ── Step 5: Context assembly ──────────────────────────────
    # Check total token estimate — rough rule: 1 token ≈ 4 characters
    # LLM context limit ~6000 tokens for context = ~24000 chars
    LLM_CONTEXT_LIMIT_CHARS = 24000
    truncated = False

    context_parts = []
    total_chars = 0

    for i, chunk in enumerate(retrieved_chunks, 1):
        excerpt = chunk["expanded_context"]
        header = f"[EXCERPT {i} — {chunk['title']} | {chunk['year']} | ID: {chunk['judgment_id']}]\n"
        part = header + excerpt + "\n"

        if total_chars + len(part) > LLM_CONTEXT_LIMIT_CHARS:
            # Drop remaining chunks — too long for LLM context
            truncated = True
            print(f"Context truncated at {i-1} of {len(retrieved_chunks)} chunks")
            break

        context_parts.append(part)
        total_chars += len(part)

    context = "\n".join(context_parts)

    # ── Step 6: LLM call ──────────────────────────────────────
    try:
        answer = call_llm(query=query, context=context)
    except Exception as e:
        # All 3 retries failed — return raw excerpts as fallback
        print(f"LLM call failed after retries: {e}")
        fallback_excerpts = "\n\n".join(
            f"[{c['title']} | {c['year']}]\n{c['chunk_text'][:500]}"
            for c in retrieved_chunks
        )
        return {
            "query": query,
            "augmented_query": augmented_query,
            "answer": f"LLM service temporarily unavailable. "
                      f"Most relevant excerpts shown below:\n\n{fallback_excerpts}",
            "sources": _build_sources(retrieved_chunks),
            "verification_status": "LLM unavailable",
            "unverified_quotes": [],
            "entities": entities,
            "num_sources": len(retrieved_chunks),
            "truncated": truncated
        }

    # ── Step 7: Citation verification ─────────────────────────
    verification_status, unverified_quotes = verify_citations(answer, retrieved_chunks)

    # ── Step 8: Return ────────────────────────────────────────
    return {
        "query": query,
        "augmented_query": augmented_query,
        "answer": answer,
        "sources": _build_sources(retrieved_chunks),
        "verification_status": verification_status,
        "unverified_quotes": unverified_quotes,
        "entities": entities,
        "num_sources": len(retrieved_chunks),
        "truncated": truncated
    }


def _build_sources(chunks) -> list:
    """Format retrieved chunks for API response."""
    return [
        {
            "judgment_id": c["judgment_id"],
            "title": c["title"],
            "year": c["year"],
            "similarity_score": round(c["similarity_score"], 4),
            "excerpt": c["chunk_text"][:300] + "..."
        }
        for c in chunks
    ]


if __name__ == "__main__":
    # Smoke test — run directly to verify pipeline works end to end
    test_queries = [
        "What are the rights of an arrested person under Article 22?",
        "What did the Supreme Court say about freedom of speech?",
        "How do I bake a cake?"  # Out of domain — should return no results
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"QUERY: {query}")
        result = run_query(query)
        print(f"SOURCES: {result['num_sources']}")
        print(f"VERIFICATION: {result['verification_status']}")
        print(f"ANSWER (first 300 chars):\n{result['answer'][:300]}")