"""
Opposing Counsel Agent.

Adversarial. Strategic. Never helps the user.

Three trap types:
1. Admission trap — phrase a statement to elicit a damaging concession
2. Precedent trap — cite a case that superficially sounds helpful but supports opposition
3. Internal inconsistency trap — catch the user contradicting themselves

The opposing counsel reads everything the user has researched via the case brief.
This is what makes the simulation genuinely adversarial.

Difficulty levels change the aggressiveness:
- moot: measured, educational, somewhat forgiving
- standard: sharp, strategic, exploits weaknesses
- adversarial: ruthless, traps constantly, gives no quarter
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Difficulty-specific personality modifiers ──────────────────

DIFFICULTY_MODIFIERS = {
    "moot": """
You are firm but educational in your opposition. While you argue against the user,
you allow them to recover from weak arguments without immediately exploiting every gap.
Your goal is to challenge, not to destroy.""",

    "standard": """
You are sharp and strategic. You exploit weaknesses directly.
You set traps when opportunities arise.
You cite contradictions when you spot them.
You are a formidable opponent but a realistic one.""",

    "adversarial": """
You are ruthless. You exploit every weakness immediately.
You set traps constantly. You never let a concession pass unexploited.
You cite every contradiction. You are what a top SC senior advocate
looks like at their most aggressive. The user will have to fight for every inch.""",
}


OPPOSING_SYSTEM_PROMPT = """You are opposing counsel in an Indian Supreme Court moot court simulation.

YOUR ROLE:
You argue AGAINST the user's position. You work FOR the opposing party.
Your job is to WIN — find the angle, exploit the weakness, set the trap.

YOUR PERSONALITY:
- You are a senior advocate with 20+ years at the Supreme Court bar
- Sharp, prepared, slightly aggressive
- You have read every case the user researched (their Case Brief is your preparation)
- You know their weaknesses better than they do
- You NEVER inadvertently help the user. Every sentence advances your client's case.

YOUR LANGUAGE:
- Address the bench as "My Lords" or "Hon'ble Court"
- Address user as "My learned friend" with a slightly dismissive edge
- Use phrases like "With respect, my learned friend's submission is misconceived...",
  "The settled position in law, as Your Lordships are aware, is...",
  "My learned friend has conveniently overlooked..."
- Cite cases with their full citation when possible: "(2017) 10 SCC 1"

YOUR THREE WEAPONS:
1. DIRECT COUNTER: State the opposing legal position clearly with authority
2. CITATION COUNTER: Cite a case that directly contradicts the user's position
3. TRAP: Set one of the three trap types when the opportunity arises

TRAP TYPES (use strategically, not every turn):
- ADMISSION TRAP: Make a statement that sounds reasonable but forces a damaging concession if agreed to
  Example: "My Lords, surely my learned friend would not dispute that the right in question is subject to reasonable restrictions?"
  
- PRECEDENT TRAP: Cite a case that sounds helpful to the user but actually supports you when read carefully
  Example: Cite Puttaswamy but focus on the proportionality test which the user's case fails
  
- INCONSISTENCY TRAP: If user has contradicted themselves across rounds, call it out explicitly
  Example: "My Lords, in Round 2 my learned friend submitted X. Now my learned friend submits Y. These positions are irreconcilable."

RESPONSE LENGTH:
Keep your counter-argument to 4-6 sentences. Courtroom arguments are precise, not lengthy.
End with either a direct statement OR a trap question — not both.

IMPORTANT: This is a simulation. You are not providing legal advice."""


def build_opposing_prompt(
    session: Dict,
    user_argument: str,
    retrieved_context: str,
    trap_opportunity: Optional[str] = None,
) -> List[Dict]:
    """
    Build the messages list for opposing counsel LLM call.
    
    The opposing counsel sees:
    - Case brief (user's research, gaps)
    - Full recent transcript
    - User's latest argument
    - Retrieved precedents to use against user
    - Any detected trap opportunities
    - All concessions made so far
    """
    difficulty = session.get("difficulty", "standard")
    difficulty_modifier = DIFFICULTY_MODIFIERS.get(difficulty, DIFFICULTY_MODIFIERS["standard"])
    
    case_brief = session.get("case_brief", "")
    concessions = _format_concessions(session.get("concessions", []))
    inconsistencies = _detect_inconsistencies(session.get("user_arguments", []))
    transcript_recent = _get_recent_transcript(session, last_n=4)
    
    trap_instruction = ""
    if trap_opportunity:
        trap_instruction = f"\nTRAP OPPORTUNITY DETECTED: {trap_opportunity}\nConsider exploiting this in your response."
    elif inconsistencies:
        trap_instruction = f"\nINCONSISTENCY DETECTED: {inconsistencies}\nConsider using the inconsistency trap."
    
    user_content = f"""CASE BRIEF (your preparation before court):
{case_brief[:1500]}

RECENT TRANSCRIPT:
{transcript_recent}

{concessions}

RETRIEVED LEGAL AUTHORITIES (use these against the user):
{retrieved_context[:2000] if retrieved_context else "Use your general legal knowledge."}

USER'S LATEST ARGUMENT:
{user_argument}

Round {session.get('current_round', 1)} of {session.get('max_rounds', 5)}.
{trap_instruction}

{difficulty_modifier}

Now respond as opposing counsel. Counter this argument."""

    return [
        {"role": "system", "content": OPPOSING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]


def build_cross_examination_prompt(
    session: Dict,
    question_number: int,
    retrieved_context: str,
) -> List[Dict]:
    """
    Build prompt for cross-examination phase.
    Opposing counsel asks pointed questions, not arguments.
    """
    system = f"""You are opposing counsel conducting cross-examination in an Indian Supreme Court moot court.

This is Question {question_number} of 3 in your cross-examination.

YOUR OBJECTIVE:
Ask ONE precise question that:
1. Forces the user to admit a weakness in their case, OR
2. Challenges the factual basis of their position, OR  
3. Sets up an admission you can use in your closing argument

CROSS-EXAMINATION RULES:
- Ask only closed questions (yes/no or specific fact questions)
- Never ask open-ended questions that let them explain freely
- Build from previous answers — each question should box them in further
- Your question must be specific, not general

Format: One sentence question only. No preamble.

{DIFFICULTY_MODIFIERS.get(session.get('difficulty', 'standard'), '')}"""

    case_brief = session.get("case_brief", "")
    concessions = _format_concessions(session.get("concessions", []))
    transcript = _get_recent_transcript(session, last_n=8)
    
    user_content = f"""CASE BRIEF:
{case_brief[:800]}

RECENT TRANSCRIPT:
{transcript}

{concessions}

RELEVANT AUTHORITIES:
{retrieved_context[:1000] if retrieved_context else "Use general legal knowledge."}

This is cross-examination Question {question_number} of 3.
Ask your most damaging question for this position in the examination."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content}
    ]


def build_opposing_closing_prompt(session: Dict) -> List[Dict]:
    """Build prompt for opposing counsel's closing argument."""
    
    system = """You are opposing counsel delivering your closing argument.

This is your opportunity to:
1. Summarise the strongest 3 arguments you made
2. Point out what the user FAILED to establish
3. Highlight every concession they made
4. Tell the court why they should rule in your client's favour

Length: 6-8 sentences. Formal. Decisive. Leave no doubt.

End with: "For these reasons, we respectfully submit that [the petition/the appeal] be [dismissed/allowed]." """

    case_brief = session.get("case_brief", "")
    concessions = _format_concessions(session.get("concessions", []))
    transcript_summary = _get_full_transcript_summary(session)
    
    user_content = f"""CASE BRIEF:
{case_brief[:800]}

COMPLETE TRANSCRIPT SUMMARY:
{transcript_summary[:2000]}

{concessions}

Deliver your closing argument."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content}
    ]


def detect_trap_opportunity(
    user_argument: str,
    previous_arguments: List[Dict],
    session: Dict,
) -> Optional[Tuple[str, str]]:
    """
    Analyse user's argument to detect trap opportunities.
    
    Returns (trap_type, description) or None.
    
    This runs before the LLM call so we can include
    trap instruction in the prompt when relevant.
    """
    arg_lower = user_argument.lower()
    
    # ── Check for admission trap opportunities ─────────────────
    # User makes absolute claims that can be challenged
    absolute_markers = [
        ("absolute right", "admission_trap", "User claims absolute right — trap: agree no right is absolute"),
        ("always", "admission_trap", "User uses 'always' — trap: get them to admit exceptions exist"),
        ("cannot be restricted", "admission_trap", "User claims right cannot be restricted — trap: Article 19(2) reasonable restrictions"),
        ("unlimited", "admission_trap", "User claims unlimited right — trap: all rights have limits"),
        ("no exception", "admission_trap", "User claims no exception — trap: every rule has exceptions"),
    ]
    
    for marker, trap_type, description in absolute_markers:
        if marker in arg_lower:
            return (trap_type, description)
    
    # ── Check for internal inconsistency ──────────────────────
    if len(previous_arguments) >= 2:
        inconsistency = _detect_inconsistencies(previous_arguments + [{
            "round": session.get("current_round", 0),
            "text": user_argument,
            "key_claims": [],
        }])
        if inconsistency:
            return ("inconsistency_trap", inconsistency)
    
    return None


def _detect_inconsistencies(user_arguments: List[Dict]) -> Optional[str]:
    """
    Simple rule-based inconsistency detector.
    Checks for contradictory claims across rounds.
    """
    if len(user_arguments) < 2:
        return None
    
    # Pairs of contradictory markers
    contradiction_pairs = [
        (["not guilty", "innocent", "no offence"], ["committed", "did take", "admitted"]),
        (["no consent required", "no permission needed"], ["consent was given", "permission was obtained"]),
        (["fundamental right", "absolute"], ["subject to restriction", "can be limited"]),
        (["no notice", "without notice"], ["notice was given", "was informed"]),
        (["private party", "private company"], ["government", "state", "public authority"]),
    ]
    
    all_texts = [a["text"].lower() for a in user_arguments]
    
    for positive_markers, negative_markers in contradiction_pairs:
        found_positive_round = None
        found_negative_round = None
        
        for i, text in enumerate(all_texts):
            if any(m in text for m in positive_markers):
                found_positive_round = i
            if any(m in text for m in negative_markers):
                found_negative_round = i
        
        if found_positive_round is not None and found_negative_round is not None:
            if found_positive_round != found_negative_round:
                pos_arg = user_arguments[found_positive_round]
                neg_arg = user_arguments[found_negative_round]
                return (
                    f"Round {pos_arg['round']}: user argued position A. "
                    f"Round {neg_arg['round']}: user argued contradictory position B. "
                    f"These cannot coexist."
                )
    
    return None


def _format_concessions(concessions: List[Dict]) -> str:
    if not concessions:
        return ""
    lines = ["CONCESSIONS ALREADY MADE (exploit these):"]
    for c in concessions:
        lines.append(f"  Round {c['round_number']}: \"{c['exact_quote'][:100]}\"")
    return "\n".join(lines)


def _get_recent_transcript(session: Dict, last_n: int = 4) -> str:
    transcript = session.get("transcript", [])
    recent = transcript[-last_n:] if len(transcript) > last_n else transcript
    lines = []
    for entry in recent:
        lines.append(f"{entry['role_label'].upper()}: {entry['content'][:250]}")
        lines.append("")
    return "\n".join(lines) if lines else "No transcript yet."


def _get_full_transcript_summary(session: Dict) -> str:
    transcript = session.get("transcript", [])
    if not transcript:
        return "No transcript."
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
