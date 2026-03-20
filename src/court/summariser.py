"""
Summariser Agent.

Only appears at the end of the session. Never speaks during the hearing.
Reads the entire transcript and produces the structured analysis document.

This is the most valuable output of the entire moot court system —
the thing that makes users want to come back and practice again.

The analysis must be:
- Brutally honest about what the user did wrong
- Specific about what they could have done differently
- Encouraging enough that they want to try again
- Precise enough to be actually useful for preparation
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

SUMMARISER_SYSTEM_PROMPT = """You are a senior legal trainer analysing a moot court simulation.

YOUR ROLE:
You have watched the complete hearing. Now you produce a comprehensive, honest analysis
that will help the user improve their advocacy skills.

YOUR PERSONALITY:
- Clinical and precise. Not harsh, not gentle — just honest.
- Deeply knowledgeable about Indian law and courtroom procedure.
- You care about the user's development. Honest feedback serves them better than false praise.
- You name specific moments, not generalities.

YOUR ANALYSIS STRUCTURE:
Produce the analysis in this EXACT format using these EXACT section headers:

## OVERALL ASSESSMENT
[2 sentences: overall performance and predicted outcome]

## PERFORMANCE SCORE
[Single number X.X/10 with one sentence justification]

## OUTCOME PREDICTION
[ALLOWED / DISMISSED / PARTLY ALLOWED / REMANDED with one sentence reasoning]

## STRONGEST ARGUMENTS
[Number each argument. For each: what was argued, why it was effective, which precedent supported it]

## WEAKEST ARGUMENTS
[Number each. For each: what was argued, exactly why it failed, what should have been argued instead]

## CONCESSIONS ANALYSIS
[For each concession: exact quote, what it conceded legally, how opposing counsel could exploit it, how to avoid making this concession]

## TRAP ANALYSIS
[For each trap event: what the trap was, whether you fell in, what the correct response was]

## WHAT THE JUDGE WAS SIGNALLING
[Translate each judicial question into plain language: what weakness it was probing]

## MISSED OPPORTUNITIES
[Arguments you should have made but didn't, with specific precedents you should have cited]

## PREPARATION RECOMMENDATIONS
[3-5 specific, actionable recommendations for what to research and prepare before a real hearing]

## FULL TRANSCRIPT
[The complete verbatim transcript formatted as a court record]

Be specific. Name rounds, cite exact quotes, reference specific cases. 
Generic feedback is useless. Specific feedback is gold."""


def build_summariser_prompt(session: Dict) -> List[Dict]:
    """
    Build the messages list for the summariser LLM call.
    
    The summariser gets everything:
    - Complete transcript
    - All concessions
    - All trap events
    - Case brief
    - Retrieved precedents used
    """
    transcript = _format_full_transcript(session)
    concessions = _format_concessions_detailed(session.get("concessions", []))
    trap_events = _format_trap_events(session.get("trap_events", []))
    user_arguments = _format_user_arguments(session.get("user_arguments", []))
    
    user_content = f"""COMPLETE SESSION DATA FOR ANALYSIS:

Case: {session.get('case_title', '')}
User argued as: {session.get('user_side', '').upper()}
Difficulty: {session.get('difficulty', 'standard')}
Rounds completed: {session.get('current_round', 0)} of {session.get('max_rounds', 5)}

CASE BRIEF:
{session.get('case_brief', 'No brief available.')[:800]}

LEGAL ISSUES:
{', '.join(session.get('legal_issues', []))}

COMPLETE TRANSCRIPT:
{transcript}

USER'S ARGUMENTS (extracted):
{user_arguments}

{concessions}

{trap_events}

Now produce the complete session analysis following the exact format specified."""

    return [
        {"role": "system", "content": SUMMARISER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]


def parse_analysis(raw_analysis: str, session: Dict) -> Dict:
    """
    Parse the summariser's raw output into a structured dict.
    Used by the frontend to display individual sections.
    """
    import re
    
    sections = {
        "overall_assessment": "",
        "performance_score": 0.0,
        "outcome_prediction": "unknown",
        "strongest_arguments": [],
        "weakest_arguments": [],
        "concessions_analysis": [],
        "trap_analysis": [],
        "judge_signals": "",
        "missed_opportunities": [],
        "preparation_recommendations": [],
        "full_transcript": "",
        "raw_analysis": raw_analysis,
    }
    
    # Extract performance score
    score_match = re.search(r'(\d+\.?\d*)\s*/\s*10', raw_analysis)
    if score_match:
        try:
            sections["performance_score"] = float(score_match.group(1))
        except Exception:
            pass
    
    # Extract outcome prediction
    for outcome in ["ALLOWED", "DISMISSED", "PARTLY ALLOWED", "REMANDED"]:
        if outcome in raw_analysis.upper():
            sections["outcome_prediction"] = outcome.lower().replace(" ", "_")
            break
    
    # Extract sections by header
    header_map = {
        "OVERALL ASSESSMENT": "overall_assessment",
        "WHAT THE JUDGE WAS SIGNALLING": "judge_signals",
        "FULL TRANSCRIPT": "full_transcript",
    }
    
    for header, key in header_map.items():
        pattern = rf'##\s+{header}\s*\n(.*?)(?=##|\Z)'
        match = re.search(pattern, raw_analysis, re.DOTALL | re.IGNORECASE)
        if match:
            sections[key] = match.group(1).strip()
    
    # Extract list sections
    list_sections = {
        "STRONGEST ARGUMENTS": "strongest_arguments",
        "WEAKEST ARGUMENTS": "weakest_arguments",
        "MISSED OPPORTUNITIES": "missed_opportunities",
        "PREPARATION RECOMMENDATIONS": "preparation_recommendations",
    }
    
    for header, key in list_sections.items():
        pattern = rf'##\s+{header}\s*\n(.*?)(?=##|\Z)'
        match = re.search(pattern, raw_analysis, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1).strip()
            # Split into numbered items
            items = re.split(r'\n\d+\.', content)
            sections[key] = [item.strip() for item in items if item.strip()]
    
    return sections


def _format_full_transcript(session: Dict) -> str:
    """Format complete transcript for analysis."""
    transcript = session.get("transcript", [])
    if not transcript:
        return "No transcript available."
    
    lines = []
    current_round = None
    
    for entry in transcript:
        round_num = entry.get("round_number", 0)
        if round_num != current_round:
            current_round = round_num
            lines.append(f"\n--- ROUND {round_num} | {entry.get('phase', '').upper()} ---\n")
        
        lines.append(f"{entry['role_label'].upper()}")
        lines.append(entry["content"])
        lines.append("")
    
    return "\n".join(lines)


def _format_concessions_detailed(concessions: List[Dict]) -> str:
    if not concessions:
        return "CONCESSIONS: None recorded."
    
    lines = ["CONCESSIONS MADE BY USER:"]
    for i, c in enumerate(concessions, 1):
        lines.append(f"{i}. Round {c['round_number']}")
        lines.append(f"   Quote: \"{c['exact_quote']}\"")
        lines.append(f"   Legal significance: {c['legal_significance']}")
        lines.append("")
    
    return "\n".join(lines)


def _format_trap_events(trap_events: List[Dict]) -> str:
    if not trap_events:
        return "TRAPS: None set."
    
    lines = ["TRAP EVENTS:"]
    for i, t in enumerate(trap_events, 1):
        fell = "USER FELL INTO TRAP" if t.get("user_fell_in") else "User avoided trap"
        lines.append(f"{i}. Round {t['round_number']} | {t['trap_type']} | {fell}")
        lines.append(f"   Trap: {t['trap_text'][:200]}")
        if t.get("user_response"):
            lines.append(f"   Response: {t['user_response'][:200]}")
        lines.append("")
    
    return "\n".join(lines)


def _format_user_arguments(user_arguments: List[Dict]) -> str:
    if not user_arguments:
        return "No user arguments recorded."
    
    lines = []
    for arg in user_arguments:
        lines.append(f"Round {arg['round']}: {arg['text'][:300]}")
        if arg.get("key_claims"):
            lines.append(f"  Claims: {', '.join(arg['key_claims'][:3])}")
        lines.append("")
    
    return "\n".join(lines)
