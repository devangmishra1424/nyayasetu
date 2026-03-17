"""
Precedent Chain Builder — Runtime Module.

Loads citation graph built offline by preprocessing/build_citation_graph.py.
At query time, enriches retrieved chunks with cited predecessor judgments.

WHY:
Indian SC judgments build on each other. A 1984 judgment establishing
a key principle was itself built on a 1971 judgment. Showing the user
the reasoning chain across cases makes NyayaSetu feel like a legal
researcher, not a search engine.

The graph is loaded once at startup and kept in memory.
Lookup is O(1) dict access — negligible runtime cost.
"""

import os
import json
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ── Graph store ───────────────────────────────────────────
_graph = {}           # judgment_id -> [citation_strings]
_reverse_graph = {}   # citation_string -> [judgment_ids]
_title_to_id = {}     # normalised_title -> judgment_id
_parent_store = {}    # judgment_id -> text (loaded from parent_judgments.jsonl)
_loaded = False


def load_citation_graph(
    graph_path: str = "data/citation_graph.json",
    reverse_path: str = "data/reverse_citation_graph.json",
    title_path: str = "data/title_to_id.json",
    parent_path: str = "data/parent_judgments.jsonl"
):
    """
    Load all citation graph artifacts once at startup.
    Call from api/main.py after download_models().
    Fails gracefully if files not found.
    """
    global _graph, _reverse_graph, _title_to_id, _parent_store, _loaded

    try:
        if os.path.exists(graph_path):
            with open(graph_path) as f:
                _graph = json.load(f)
            logger.info(f"Citation graph loaded: {len(_graph)} judgments")
        else:
            logger.warning(f"Citation graph not found at {graph_path}")

        if os.path.exists(reverse_path):
            with open(reverse_path) as f:
                _reverse_graph = json.load(f)
            logger.info(f"Reverse citation graph loaded: {len(_reverse_graph)} citations")

        if os.path.exists(title_path):
            with open(title_path) as f:
                _title_to_id = json.load(f)
            logger.info(f"Title index loaded: {len(_title_to_id)} titles")

        # Load parent judgments for text retrieval
        if os.path.exists(parent_path):
            with open(parent_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        j = json.loads(line)
                        jid = j.get("judgment_id", "")
                        if jid:
                            _parent_store[jid] = j.get("text", "")
                    except Exception:
                        continue
            logger.info(f"Parent store loaded: {len(_parent_store)} judgments")

        _loaded = True

    except Exception as e:
        logger.error(f"Citation graph load failed: {e}. Precedent chain disabled.")
        _loaded = False


def _resolve_citation_to_judgment(citation_string: str) -> Optional[str]:
    """
    Try to match a citation string to a judgment_id.
    Uses multiple strategies in order of reliability.
    """
    if not citation_string:
        return None

    # Strategy 1: Check reverse graph directly
    if citation_string in _reverse_graph:
        refs = _reverse_graph[citation_string]
        if refs:
            return refs[0]

    # Strategy 2: Normalise and check title index
    normalised = re.sub(r'[^\w\s]', '', citation_string.lower())[:50]
    if normalised in _title_to_id:
        return _title_to_id[normalised]

    # Strategy 3: Partial match on title index
    for title, jid in _title_to_id.items():
        if len(normalised) > 10 and normalised[:20] in title:
            return jid

    return None


def get_precedent_chain(
    judgment_ids: List[str],
    max_precedents: int = 3
) -> List[Dict]:
    """
    Given a list of retrieved judgment IDs, return their cited predecessors.

    Args:
        judgment_ids: IDs of judgments already retrieved by FAISS
        max_precedents: maximum number of precedent chunks to return

    Returns:
        List of precedent dicts with same structure as regular chunks,
        plus 'is_precedent': True and 'cited_by' field.
    """
    if not _loaded or not _graph:
        return []

    precedents = []
    seen_ids = set(judgment_ids)

    for jid in judgment_ids:
        citations = _graph.get(jid, [])
        if not citations:
            continue

        for citation_ref in citations[:3]:  # max 3 citations per judgment
            resolved_id = _resolve_citation_to_judgment(citation_ref)

            if not resolved_id or resolved_id in seen_ids:
                continue

            # Get text from parent store
            text = _parent_store.get(resolved_id, "")
            if not text:
                continue

            seen_ids.add(resolved_id)

            # Extract a useful excerpt — first 1500 chars after any header
            excerpt = text[:1500].strip()

            precedents.append({
                "judgment_id": resolved_id,
                "chunk_id": f"{resolved_id}_precedent",
                "text": excerpt,
                "title": f"Precedent: {citation_ref[:80]}",
                "year": resolved_id.split("_")[1] if "_" in resolved_id else "",
                "source_type": "case_law",
                "is_precedent": True,
                "cited_by": jid,
                "citation_ref": citation_ref,
                "similarity_score": 0.5  # precedents are added, not ranked
            })

            if len(precedents) >= max_precedents:
                break

        if len(precedents) >= max_precedents:
            break

    if precedents:
        logger.info(f"Precedent chain: added {len(precedents)} predecessor judgments")

    return precedents


def get_citation_count(judgment_id: str) -> int:
    """How many times has this judgment been cited by others."""
    count = 0
    for citations in _graph.values():
        for c in citations:
            resolved = _resolve_citation_to_judgment(c)
            if resolved == judgment_id:
                count += 1
    return count


def is_loaded() -> bool:
    return _loaded