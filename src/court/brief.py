"""
Case Brief Generator.

When a user imports a NyayaSetu research session into Moot Court,
this module reads the session state and generates a structured Case Brief.

The Case Brief is what opposing counsel reads before the hearing starts.
It tells them:
- What facts have been established
- What legal issues the user identified
- What precedents they retrieved
- Where the gaps are in their case

This is what makes the simulation genuinely adversarial —
opposing counsel knows your research.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def generate_case_brief(
    research_session: Dict,
    user_side: str,
) -> str:
    """
    Generate a structured Case Brief from a NyayaSetu research session.
    
    Args:
        research_session: The session dict from NyayaSetu's sessions store
        user_side: "petitioner" or "respondent"
    
    Returns:
        Formatted case brief string ready for LLM consumption
    """
    cs = research_session.get("case_state", {})
    summary = research_session.get("summary", "")
    
    # Extract structured data
    parties = cs.get("parties", [])
    events = cs.get("events", [])
    documents = cs.get("documents", [])
    disputes = cs.get("disputes", [])
    hypotheses = cs.get("hypotheses", [])
    facts_missing = cs.get("facts_missing", [])
    
    # Extract precedents from last messages
    last_messages = research_session.get("last_3_messages", [])
    
    sections = [
        "CASE BRIEF",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Generated from NyayaSetu Research Session",
        f"User Position: {user_side.upper()}",
        "",
    ]
    
    if summary:
        sections += [
            "SITUATION SUMMARY:",
            summary,
            "",
        ]
    
    if parties:
        sections += [
            "PARTIES IDENTIFIED:",
            *[f"  • {p}" for p in parties],
            "",
        ]
    
    if events:
        sections += [
            "KEY EVENTS:",
            *[f"  • {e}" for e in events],
            "",
        ]
    
    if documents:
        sections += [
            "EVIDENCE/DOCUMENTS MENTIONED:",
            *[f"  • {d}" for d in documents],
            "",
        ]
    
    if disputes:
        sections += [
            "CORE DISPUTES:",
            *[f"  • {d}" for d in disputes],
            "",
        ]
    
    if hypotheses:
        sections += ["LEGAL HYPOTHESES FORMED:"]
        for h in hypotheses[:5]:
            claim = h.get("claim", "")
            confidence = h.get("confidence", "unknown")
            evidence = h.get("evidence", [])
            sections.append(f"  • [{confidence.upper()}] {claim}")
            if evidence:
                sections.append(f"    Evidence: {', '.join(evidence[:3])}")
        sections.append("")
    
    if facts_missing:
        sections += [
            "KNOWN GAPS IN THE CASE (Critical for opposing counsel):",
            *[f"  ⚠ {f}" for f in facts_missing],
            "",
        ]
    
    sections += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "NOTE: This brief was generated from the user's research session.",
        "Opposing counsel has access to all information above.",
    ]
    
    return "\n".join(sections)


def generate_fresh_brief(
    case_title: str,
    user_side: str,
    user_client: str,
    opposing_party: str,
    legal_issues: list,
    brief_facts: str,
    jurisdiction: str,
) -> str:
    """
    Generate a case brief from scratch when user enters details manually.
    """
    user_role = "Petitioner" if user_side == "petitioner" else "Respondent"
    opposing_role = "Respondent" if user_side == "petitioner" else "Petitioner"
    
    sections = [
        "CASE BRIEF",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Case Title: {case_title}",
        f"Jurisdiction: {jurisdiction.replace('_', ' ').title()}",
        "",
        f"{user_role} ({user_client}) vs {opposing_role} ({opposing_party})",
        "",
        "BRIEF FACTS:",
        brief_facts,
        "",
        "LEGAL ISSUES:",
        *[f"  {i+1}. {issue}" for i, issue in enumerate(legal_issues)],
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    
    return "\n".join(sections)
