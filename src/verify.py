"""
Citation verification module.
Checks whether quoted phrases in LLM answer appear in retrieved context.

Deterministic — no ML inference.
Documented limitation: paraphrases pass as verified because
exact paraphrase matching requires NLI which is out of scope.
"""

import re
import unicodedata


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_quotes(text: str) -> list[str]:
    """Extract all quoted phrases from text."""
    patterns = [
        r'"([^"]{10,})"',      # standard double quotes
        r'\u201c([^\u201d]{10,})\u201d',  # curly double quotes
        r"'([^']{10,})'",      # single quotes
    ]
    quotes = []
    for pattern in patterns:
        found = re.findall(pattern, text)
        quotes.extend(found)
    return quotes


def verify_citations(answer: str, contexts: list[dict]) -> tuple[bool, list[str]]:
    """
    Check whether quoted phrases in answer appear in context windows.

    Returns:
        (verified: bool, unverified_quotes: list[str])

    Logic:
        - Extract all quoted phrases from answer
        - If no quotes: return (True, []) — no verifiable claims made
        - For each quote: check if normalised quote is substring of any normalised context
        - If ALL quotes found: (True, [])
        - If ANY quote not found: (False, [list of missing quotes])
    """
    quotes = _extract_quotes(answer)

    if not quotes:
        return True, []

    # Build normalised context corpus
    all_context_text = " ".join(
        _normalise(ctx.get("text", "") or ctx.get("excerpt", ""))
        for ctx in contexts
    )

    unverified = []
    for quote in quotes:
        normalised_quote = _normalise(quote)
        # Skip very short normalised quotes — likely artifacts
        if len(normalised_quote) < 8:
            continue
        if normalised_quote not in all_context_text:
            unverified.append(quote)

    if unverified:
        return False, unverified
    return True, []