"""
Court Registrar Agent.

Procedural voice. Manages session flow. Keeps both sides accountable.
Only speaks twice per round:
1. Opening announcement for the round
2. Closing note if anything was left unaddressed

Uses only the transcript — no retrieval needed.
Runs on a fast, simple prompt — not the full LLM.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

REGISTRAR_SYSTEM_PROMPT = """You are the Court Registrar in an Indian Supreme Court moot court simulation.

YOUR ROLE:
You manage procedure. You are formal, neutral, bureaucratic.
You speak in short, precise announcements.

YOU SPEAK IN TWO SITUATIONS ONLY:
1. At the start of each round/phase — announce what is happening
2. When counsel has left something unaddressed — flag it

YOUR LANGUAGE:
- "The court is now in session."
- "Counsel for the petitioner may proceed with Round [N]."
- "The court notes that counsel has not addressed [specific observation from previous round]."
- "Cross-examination will now commence. Respondent's counsel will proceed."
- "The court stands adjourned pending deliberation."

NEVER give legal analysis. Never express an opinion. Never take sides.
Your job is procedure and record-keeping only.

Keep all announcements to 1-3 sentences."""


def build_round_announcement(
    session: Dict,
    round_number: int,
    phase: str,
) -> str:
    """
    Generate registrar's round opening announcement.
    This is deterministic — no LLM call needed for standard announcements.
    """
    user_side = session.get("user_side", "petitioner")
    user_label = "Petitioner's Counsel" if user_side == "petitioner" else "Respondent's Counsel"
    max_rounds = session.get("max_rounds", 5)
    
    announcements = {
        "briefing": (
            f"The court is now in session. "
            f"Case: {session.get('case_title', 'Present Matter')}. "
            f"The bench has perused the case brief. "
            f"{user_label} may proceed with opening submissions."
        ),
        "rounds": (
            f"Round {round_number} of {max_rounds}. "
            f"{user_label} may proceed."
        ),
        "cross_examination": (
            f"The court now moves to cross-examination. "
            f"Opposing counsel will put three questions to {user_label}. "
            f"Counsel is directed to answer specifically."
        ),
        "closing": (
            f"The court will now hear closing arguments. "
            f"{user_label} may begin."
        ),
        "completed": (
            f"The court stands adjourned. "
            f"A formal analysis of the proceedings will now be prepared."
        ),
    }
    
    return announcements.get(phase, f"The court will now proceed with {phase}.")


def build_accountability_note(
    session: Dict,
    unaddressed_items: List[str],
) -> str:
    """
    Generate a registrar note when counsel left something unaddressed.
    Only called when there ARE unaddressed items.
    """
    if not unaddressed_items:
        return ""
    
    if len(unaddressed_items) == 1:
        return (
            f"The court notes that counsel has not addressed "
            f"the following observation from the previous round: "
            f"{unaddressed_items[0]}"
        )
    else:
        items_text = "; ".join(unaddressed_items[:2])
        return (
            f"The court notes that counsel has not addressed "
            f"the following observations from the previous round: {items_text}."
        )


def get_objection_announcement(ruling: str, objection_type: str) -> str:
    """Format registrar's recording of an objection ruling."""
    return f"Objection noted. The court has ruled: {ruling}"


def get_document_announcement(doc_type: str, filed_by: str) -> str:
    """Announce when a document is produced."""
    return (
        f"The court notes that {filed_by} has produced "
        f"{doc_type} which has been taken on record."
    )
