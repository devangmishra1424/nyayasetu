"""
Citation verification. Deterministic string matching — no ML.

LOGIC:
- Extract all quoted phrases (in double quotes) from LLM answer
- Check each phrase verbatim against all retrieved chunk texts
- ALL found → Verified
- ANY missing → Unverified  
- No quotes in answer → Verified (no verifiable claim made)

DOCUMENTED LIMITATION:
Paraphrased claims that are not quoted pass as Verified.
Full NLI-based verification is out of scope — documented in README.
"""

import re
from typing import List, Dict, Tuple

def extract_quotes(text: str) -> List[str]:
    """Extract double-quoted phrases of at least 8 characters."""
    return re.findall(r'"([^"]{8,})"', text)

def verify_citations(
    llm_answer: str,
    retrieved_chunks: List[Dict]
) -> Tuple[str, List[str]]:
    """
    Returns (status, unverified_quotes).
    status: "Verified" | "Unverified" | "No verifiable claims"
    """
    quotes = extract_quotes(llm_answer)
    
    if not quotes:
        return "No verifiable claims", []
    
    all_context = " ".join(
        c.get("expanded_context", c.get("chunk_text", ""))
        for c in retrieved_chunks
    ).lower()
    
    unverified = [q for q in quotes if q.lower() not in all_context]
    
    if unverified:
        return "Unverified", unverified
    return "Verified", []