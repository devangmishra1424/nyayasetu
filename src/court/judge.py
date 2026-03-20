"""
Judge Agent.

Neutral but dangerous. Finds logical gaps in every argument.
Asks pointed questions that expose weakness.
Controls session flow.

The judge never helps either side — asks what exposes weakness.
Questions get sharper as the session progresses because the judge
tracks all concessions and inconsistencies.

WHY a dedicated judge module?
The judge has completely different objectives from opposing counsel.
Keeping them separate means their prompts never contaminate each other.
The judge is neutral. Opposing counsel is adversarial. These must stay clean.
"""

import logging
import json
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """You are the presiding judge in an Indian Supreme Court moot court simulation.

YOUR ROLE:
You are neutral but intellectually rigorous. Your job is not to help either party — it is to find the logical gaps, unanswered questions, and weaknesses in whatever argument was just made.

YOUR PERSONALITY:
- Formal and precise. Never casual.
- Slightly impatient with vague or uncited arguments.
- Deeply knowledgeable about Indian constitutional law, criminal law, and procedure.
- You ask exactly ONE question per turn — the most important one.
- Your questions are surgical: "Counsel, how does your argument survive the test in Maneka Gandhi?" not "Can you explain more?"

YOUR LANGUAGE:
- Always address user as "Counsel" or "Learned Counsel"
- Refer to yourself as "the Court" or "this Court" — never "I" or "me"
- Use phrases like: "The court is not satisfied...", "Counsel has not addressed...", "This court wishes to know..."
- Never use casual language. Every sentence sounds like it belongs in a court record.

YOUR QUESTIONING STRATEGY:
1. Find the weakest logical point in the last argument made
2. Check if any previous concessions can be pressed further
3. Identify what legal authority was NOT cited that should have been
4. Ask the ONE question that most challenges the user's position

QUESTION FORMAT:
Keep your observation to 1-2 sentences, then ask your question.
Total response: 3-5 sentences maximum.
Never give a speech. The court asks. Counsel answers.

IMPORTANT: You are NOT legal advice. This is a simulation."""


JUDGE_CLOSING_OBSERVATION_PROMPT = """You are the presiding judge delivering final observations after hearing closing arguments.

This is the most important moment in the simulation. Your observations signal which way the court is leaning.

Based on the complete transcript, deliver:
1. Your observation on the strongest argument made in this hearing (2 sentences)
2. The weakest point that was not adequately addressed (2 sentences)  
3. A final observation that signals the likely outcome WITHOUT explicitly stating it (2 sentences)

Total: 6 sentences maximum. Formal judicial language throughout.
Remain neutral in tone even while signalling the likely outcome through your choice of emphasis."""


def build_judge_prompt(
    session: Dict,
    last_user_argument: str,
    retrieved_context: str,
) -> List[Dict]:
    """
    Build the messages list for the judge LLM call.
    
    The judge sees:
    - Full session transcript (compressed)
    - Last user argument
    - Relevant retrieved precedents
    - All concessions made so far
    - Current round number
    """
    cs_summary = _build_case_summary(session)
    concessions_text = _format_concessions(session.get("concessions", []))
    transcript_recent = _get_recent_transcript(session, last_n=6)
    
    user_content = f"""CASE SUMMARY:
{cs_summary}

RECENT TRANSCRIPT (last 6 entries):
{transcript_recent}

{concessions_text}

RELEVANT LEGAL AUTHORITIES (from retrieval):
{retrieved_context[:1500] if retrieved_context else "No additional precedents retrieved."}

LAST ARGUMENT BY COUNSEL:
{last_user_argument}

Round {session.get('current_round', 1)} of {session.get('max_rounds', 5)}.
Difficulty: {session.get('difficulty', 'standard')}.

Now ask your ONE most important question. Be precise. Be judicial. Challenge the weakness."""

    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]


def build_judge_closing_prompt(session: Dict) -> List[Dict]:
    """Build prompt for judge's final closing observations."""
    
    transcript_full = _get_full_transcript_summary(session)
    concessions = _format_concessions(session.get("concessions", []))
    
    user_content = f"""COMPLETE SESSION SUMMARY:
{transcript_full}

{concessions}

User argued as: {session.get('user_side', 'petitioner').upper()}
Case: {session.get('case_title', '')}

Deliver your final judicial observations."""

    return [
        {"role": "system", "content": JUDGE_CLOSING_OBSERVATION_PROMPT},
        {"role": "user", "content": user_content}
    ]


def build_objection_ruling_prompt(
    session: Dict,
    objection_type: str,
    objection_text: str,
    what_was_objected_to: str,
) -> List[Dict]:
    """Build prompt for judge ruling on an objection."""
    
    system = """You are a Supreme Court judge ruling on an objection raised by counsel.

Rule on the objection in 2-3 sentences:
1. State whether it is sustained or overruled
2. Give brief legal reasoning
3. Direct counsel to proceed

Be decisive. No hedging. The court rules."""

    user_content = f"""Objection raised: {objection_type}
Counsel stated: {objection_text}
Regarding: {what_was_objected_to}

Rule on this objection."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content}
    ]


def _build_case_summary(session: Dict) -> str:
    return (
        f"Case: {session.get('case_title', '')}\n"
        f"User side: {session.get('user_side', '').upper()}\n"
        f"Legal issues: {', '.join(session.get('legal_issues', []))}\n"
        f"Phase: {session.get('phase', '')} | Round: {session.get('current_round', 0)}"
    )


def _format_concessions(concessions: List[Dict]) -> str:
    if not concessions:
        return ""
    
    lines = ["CONCESSIONS ON RECORD:"]
    for c in concessions:
        lines.append(f"  Round {c['round_number']}: \"{c['exact_quote'][:100]}\"")
        lines.append(f"  Significance: {c['legal_significance'][:100]}")
    
    return "\n".join(lines)


def _get_recent_transcript(session: Dict, last_n: int = 6) -> str:
    transcript = session.get("transcript", [])
    recent = transcript[-last_n:] if len(transcript) > last_n else transcript
    
    lines = []
    for entry in recent:
        lines.append(f"{entry['role_label'].upper()}: {entry['content'][:300]}")
        lines.append("")
    
    return "\n".join(lines) if lines else "No transcript yet."


def _get_full_transcript_summary(session: Dict) -> str:
    """Compressed full transcript for closing observations."""
    transcript = session.get("transcript", [])
    
    if not transcript:
        return "No transcript available."
    
    # Group by round
    rounds = {}
    for entry in transcript:
        r = entry.get("round_number", 0)
        if r not in rounds:
            rounds[r] = []
        rounds[r].append(f"{entry['role_label']}: {entry['content'][:200]}")
    
    lines = []
    for round_num in sorted(rounds.keys()):
        lines.append(f"--- Round {round_num} ---")
        lines.extend(rounds[round_num])
        lines.append("")
    
    return "\n".join(lines)
