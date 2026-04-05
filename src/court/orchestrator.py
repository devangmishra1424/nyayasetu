"""
Court Orchestrator.

Coordinates all four agents for each user action.
Single entry point for all court operations.

Per round flow:
  1. User submits argument
  2. Opposing counsel responds (retrieval + LLM)
  3. Judge asks question (retrieval + LLM)
  4. Registrar announces (deterministic)
  5. Concession detection runs
  6. Trap detection runs
  7. Session updated
  8. Response assembled

This module owns the 3-LLM-calls-per-round budget.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.court.session import (
    get_session,
    add_transcript_entry,
    add_concession,
    add_trap_event,
    add_user_argument,
    advance_round,
    advance_phase,
    update_session,
)
from src.court.judge import (
    build_judge_prompt,
    build_judge_closing_prompt,
    build_objection_ruling_prompt,
)
from src.court.opposing import (
    build_opposing_prompt,
    build_cross_examination_prompt,
    build_opposing_closing_prompt,
    detect_trap_opportunity,
)
from src.court.registrar import (
    build_round_announcement,
    build_accountability_note,
    get_document_announcement,
)
from src.court.summariser import (
    build_summariser_prompt,
    parse_analysis,
)

logger = logging.getLogger(__name__)


def _call_llm(messages: List[Dict]) -> str:
    """
    Call the LLM. Uses the same llm.py as the main agent.
    """
    from src.llm import call_llm_raw
    return call_llm_raw(messages)


def _build_full_context(session: Dict) -> str:
    """
    Builds complete context string fed to every LLM call.
    Ensures nothing goes wasted — case brief, all arguments, all documents,
    all concessions, all traps are included in every agent's view.
    
    This is the single source of context enrichment for the moot court.
    """
    parts = []
    
    # ── Case foundation ────────────────────────────────────────
    parts.append("=== CASE FOUNDATION ===")
    parts.append(f"Case: {session.get('case_title', '')}")
    parts.append(f"Your side: {session.get('user_side', '').upper()}")
    parts.append(f"Legal issues: {', '.join(session.get('legal_issues', []))}")
    if session.get('brief_facts'):
        parts.append(f"Facts: {session.get('brief_facts', '')[:400]}")
    parts.append("")
    
    # ── Case brief (preserved throughout) ───────────────────────
    case_brief = session.get("case_brief", "")
    if case_brief:
        parts.append("=== CASE BRIEF & RESEARCH ===")
        parts.append(case_brief[:1200])
        parts.append("")
    
    # ── Documents produced (CRITICAL — opposing counsel sees these) ──
    docs = session.get("documents_produced", [])
    if docs:
        parts.append("=== DOCUMENTS ON RECORD ===")
        for doc in docs:
            parts.append(f"[{doc.get('type', 'DOCUMENT')} — filed by {doc.get('for_side', 'COUNSEL')}]")
            parts.append(doc.get("content", "")[:500])
            parts.append("")
    
    # ── All concessions made (CRITICAL — opposing counsel exploits these) ──
    concessions = session.get("concessions", [])
    if concessions:
        parts.append("=== CONCESSIONS ON RECORD (EXPLOIT THESE) ===")
        for c in concessions:
            parts.append(
                f"Round {c.get('round_number', '?')}: \"{c.get('exact_quote', '')[:120]}\" "
                f"({c.get('legal_significance', 'Concession')[:80]})"
            )
        parts.append("")
    
    # ── Trap history (opposing counsel knows what worked before) ──
    traps = session.get("trap_events", [])
    if traps:
        parts.append("=== TRAP HISTORY ===")
        for t in traps:
            fell = "USER FELL IN" if t.get("user_fell_in") else "user avoided"
            parts.append(
                f"Round {t.get('round_number', '?')} [{t.get('trap_type', 'trap').upper()}] {fell}: "
                f"{t.get('trap_text', '')[:120]}"
            )
        parts.append("")
    
    # ── Full user argument history (consistency checking) ────────
    user_args = session.get("user_arguments", [])
    if user_args:
        parts.append("=== USER'S ARGUMENT HISTORY ===")
        for arg in user_args:
            parts.append(f"Round {arg.get('round', '?')}: {arg.get('text', '')[:250]}")
        parts.append("")
    
    # ── Recent transcript (verbatim, untruncated where possible) ─
    transcript = session.get("transcript", [])
    if transcript:
        recent = transcript[-10:]  # More entries than before (was 4, now 10)
        parts.append("=== RECENT PROCEEDINGS ===")
        for entry in recent:
            role = entry.get('role_label', entry.get('speaker', 'SPEAKER')).upper()
            content = entry.get('content', '')[:300]
            parts.append(f"{role}: {content}")
            parts.append("")
    
    return "\n".join(parts)


def _retrieve_for_court(query: str, session: Dict) -> str:
    """
    Retrieve relevant precedents for court use.
    Uses the same FAISS retrieval as main agent.
    Returns formatted context string.
    """
    try:
        from src.embed import embed_text
        from src.retrieval import retrieve
        
        embedding = embed_text(query)
        chunks = retrieve(embedding, top_k=3)
        
        if not chunks:
            return ""
        
        context_parts = []
        for chunk in chunks:
            title = chunk.get("title", "")
            year = chunk.get("year", "")
            text = chunk.get("expanded_context") or chunk.get("chunk_text") or ""
            context_parts.append(f"[{title} | {year}]\n{text[:600]}")
        
        return "\n\n".join(context_parts)
    
    except Exception as e:
        logger.warning(f"Court retrieval failed: {e}")
        return ""


def process_user_argument(
    session_id: str,
    user_argument: str,
) -> Dict:
    """
    Main function called when user submits an argument during rounds.
    
    Returns dict with:
    - opposing_response: str
    - judge_question: str
    - registrar_note: str
    - trap_detected: bool
    - trap_warning: str (empty if no trap)
    - new_concessions: list
    - round_number: int
    - phase: str
    """
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    
    phase = session["phase"]
    
    # Validate user is allowed to submit
    if phase not in ["briefing", "rounds", "cross_examination", "closing"]:
        return {"error": f"Session is in {phase} phase. Cannot accept submissions."}
    
    # Route to appropriate handler
    try:
        if phase == "briefing":
            return _handle_briefing(session_id, user_argument, session)
        elif phase == "rounds":
            return _handle_round(session_id, user_argument, session)
        elif phase == "cross_examination":
            return _handle_cross_exam_answer(session_id, user_argument, session)
        elif phase == "closing":
            return _handle_closing(session_id, user_argument, session)
        else:
            return {"error": f"Cannot process argument in phase: {phase}"}
    except Exception as e:
        logger.error(f"process_user_argument failed in phase {phase}: {e}", exc_info=True)
        return {"error": str(e)}


def _handle_briefing(session_id: str, user_argument: str, session: Dict) -> Dict:
    """
    Handle the first submission — opening argument / briefing phase.
    Transitions to rounds phase after.
    """
    # Add user's opening to transcript
    user_label = (
        "PETITIONER'S COUNSEL"
        if session["user_side"] == "petitioner"
        else "RESPONDENT'S COUNSEL"
    )
    
    add_transcript_entry(
        session_id=session_id,
        speaker=session["user_side"].upper(),
        role_label=user_label,
        content=user_argument,
        entry_type="argument",
    )
    
    add_user_argument(session_id, user_argument, [])
    
    # Build full context with all case info
    full_context = _build_full_context(session)
    
    # Retrieve additional precedents
    query = f"{session.get('case_title', '')} {' '.join(session.get('legal_issues', []))}"
    retrieved_precedents = _retrieve_for_court(query, session)
    combined_context = full_context + "\n\n=== RETRIEVED PRECEDENTS ===\n" + retrieved_precedents if retrieved_precedents else full_context
    
    # Check for trap opportunity
    trap_info = detect_trap_opportunity(user_argument, [], session)
    
    # Opposing counsel responds
    opposing_messages = build_opposing_prompt(
        session=session,
        user_argument=user_argument,
        retrieved_context=combined_context,
        trap_opportunity=trap_info[1] if trap_info else None,
    )
    
    try:
        opposing_response = _call_llm(opposing_messages)
    except Exception as e:
        logger.error(f"Opposing counsel LLM failed: {e}")
        opposing_response = (
            "With respect, My Lords, the submission of my learned friend "
            "lacks the necessary legal foundation. We shall address this in detail."
        )
    
    add_transcript_entry(
        session_id=session_id,
        speaker="OPPOSING_COUNSEL",
        role_label="RESPONDENT'S COUNSEL" if session["user_side"] == "petitioner" else "PETITIONER'S COUNSEL",
        content=opposing_response,
        entry_type="argument",
        metadata={"trap_type": trap_info[0] if trap_info else None},
    )
    
    # Judge asks first question
    judge_messages = build_judge_prompt(
        session=get_session(session_id),  # Fresh session after updates
        last_user_argument=user_argument,
        retrieved_context=combined_context,
    )
    
    try:
        judge_question = _call_llm(judge_messages)
    except Exception as e:
        logger.error(f"Judge LLM failed: {e}")
        judge_question = (
            "Counsel, the court wishes to understand the precise legal foundation "
            "for your submission. What authority do you rely upon?"
        )
    
    add_transcript_entry(
        session_id=session_id,
        speaker="JUDGE",
        role_label="HON'BLE COURT",
        content=judge_question,
        entry_type="question",
    )
    
    # Registrar announces Round 1
    advance_phase(session_id)
    advance_round(session_id)
    registrar_note = build_round_announcement(session, 1, "rounds")
    
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=registrar_note,
        entry_type="announcement",
    )
    
    # Record trap event if applicable
    if trap_info:
        add_trap_event(
            session_id=session_id,
            trap_type=trap_info[0],
            trap_text=opposing_response,
            user_fell_in=False,
        )
    
    # UPDATE: After briefing, user is now in Round 1 and should submit their argument
    update_session(session_id, {"awaiting_action": "user"})
    
    return {
        "opposing_response": opposing_response,
        "judge_question": judge_question,
        "registrar_note": registrar_note,
        "trap_detected": bool(trap_info),
        "trap_warning": f"Trap detected: {trap_info[1]}" if trap_info and session.get("show_trap_warnings") else "",
        "new_concessions": [],
        "round_number": 1,
        "phase": "rounds",
        "session_ended": False,
    }


def _handle_round(session_id: str, user_argument: str, session: Dict) -> Dict:
    """Handle a standard argument round."""
    
    current_round = session["current_round"]
    max_rounds = session["max_rounds"]
    user_side = session["user_side"]
    user_label = "PETITIONER'S COUNSEL" if user_side == "petitioner" else "RESPONDENT'S COUNSEL"
    
    # TURN VALIDATION: Only user should be able to submit arguments in "rounds" phase
    awaiting = session.get("awaiting_action", "user")
    if awaiting != "user":
        return {"error": f"It is currently waiting for {awaiting}'s submission. You cannot speak now."}
    
    # Add user argument to transcript
    add_transcript_entry(
        session_id=session_id,
        speaker=user_side.upper(),
        role_label=user_label,
        content=user_argument,
        entry_type="argument",
    )
    
    add_user_argument(
        session_id=session_id,
        argument_text=user_argument,
        key_claims=_extract_key_claims(user_argument),
    )
    
    # Build full context — EVERYTHING is preserved and fed to agents
    fresh_session = get_session(session_id)
    full_context = _build_full_context(fresh_session)
    
    # Retrieve additional precedents and combine
    legal_issues = " ".join(session.get("legal_issues", []))
    query = f"{user_argument[:200]} {legal_issues}"
    retrieved_precedents = _retrieve_for_court(query, session)
    combined_context = full_context + "\n\n=== RETRIEVED PRECEDENTS ===\n" + retrieved_precedents if retrieved_precedents else full_context
    
    # Detect traps (based on full history)
    trap_info = detect_trap_opportunity(
        user_argument,
        session.get("user_arguments", []),
        session,
    )
    
    # ── LLM Call 1: Opposing counsel ──────────────────────────
    opposing_messages = build_opposing_prompt(
        session=fresh_session,
        user_argument=user_argument,
        retrieved_context=combined_context,
        trap_opportunity=trap_info[1] if trap_info else None,
    )
    
    try:
        opposing_response = _call_llm(opposing_messages)
    except Exception as e:
        logger.error(f"Opposing LLM failed: {e}")
        opposing_response = (
            "My Lords, with respect, my learned friend's submission overlooks "
            "the settled legal position on this point."
        )
    
    add_transcript_entry(
        session_id=session_id,
        speaker="OPPOSING_COUNSEL",
        role_label="RESPONDENT'S COUNSEL" if user_side == "petitioner" else "PETITIONER'S COUNSEL",
        content=opposing_response,
        entry_type="argument",
        metadata={"trap_type": trap_info[0] if trap_info else None},
    )
    
    if trap_info:
        add_trap_event(
            session_id=session_id,
            trap_type=trap_info[0],
            trap_text=opposing_response,
            user_fell_in=_did_user_fall_in_trap(user_argument, trap_info[0]),
            user_response=user_argument,
        )
    
    # ── LLM Call 2: Judge question ────────────────────────────
    fresh_session = get_session(session_id)
    judge_messages = build_judge_prompt(
        session=fresh_session,
        last_user_argument=user_argument,
        retrieved_context=combined_context,
    )
    
    try:
        judge_question = _call_llm(judge_messages)
    except Exception as e:
        logger.error(f"Judge LLM failed: {e}")
        judge_question = (
            "Counsel, the court requires further elaboration on the legal basis of your submission."
        )
    
    add_transcript_entry(
        session_id=session_id,
        speaker="JUDGE",
        role_label="HON'BLE COURT",
        content=judge_question,
        entry_type="question",
    )
    
    # ── Advance round / phase ─────────────────────────────────
    new_round = advance_round(session_id)
    fresh_session = get_session(session_id)
    new_phase = fresh_session["phase"]
    
    # Registrar announcement
    if new_phase == "cross_examination":
        registrar_note = build_round_announcement(session, new_round, "cross_examination")
        # First cross-exam question will be generated, user will answer it
        next_awaiting = "user"  
    elif new_round <= max_rounds:
        registrar_note = build_round_announcement(session, new_round, "rounds")
        next_awaiting = "user"  # User gets to submit next round argument
    else:
        registrar_note = build_round_announcement(session, new_round, "closing")
        next_awaiting = "user"  # User gives closing arguments
    
    # UPDATE: Mark that awaiting_action should be set AFTER round advances
    update_session(session_id, {"awaiting_action": next_awaiting})
    
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=registrar_note,
        entry_type="announcement",
    )
    
    # If transitioning to cross-examination, generate the first cross-exam question now
    if new_phase == "cross_examination":
        fresh_session = get_session(session_id)
        
        # Retrieve precedents for cross-exam context
        combined_context = _build_full_context(fresh_session)
        
        cross_exam_messages = build_cross_examination_prompt(
            session=fresh_session,
            question_number=1,
            retrieved_context=combined_context,
        )
        try:
            first_cross_question = _call_llm(cross_exam_messages)
        except Exception as e:
            logger.error(f"Cross-exam question generation failed: {e}")
            first_cross_question = (
                "Counsel, in your submitted brief, you stated that [key assertion]. "
                "Can you elaborate on the legal precedent supporting this position?"
            )
        
        add_transcript_entry(
            session_id=session_id,
            speaker="OPPOSING_COUNSEL",
            role_label="RESPONDENT'S COUNSEL" if session["user_side"] == "petitioner" else "PETITIONER'S COUNSEL",
            content=first_cross_question,
            entry_type="cross_exam_question",
            metadata={"question_number": 1},
        )
    
    # Detect concessions
    new_concessions = _detect_concessions(user_argument, session_id, current_round)
    
    return {
        "opposing_response": opposing_response,
        "judge_question": judge_question,
        "registrar_note": registrar_note,
        "trap_detected": bool(trap_info),
        "trap_warning": f"Potential trap in opposing counsel's last statement" if trap_info and session.get("show_trap_warnings") else "",
        "new_concessions": new_concessions,
        "round_number": new_round,
        "phase": new_phase,
        "session_ended": new_phase == "completed",
    }


def _handle_cross_exam_answer(
    session_id: str,
    user_answer: str,
    session: Dict,
) -> Dict:
    """Handle user's answer during cross-examination."""
    
    user_side = session["user_side"]
    user_label = "PETITIONER'S COUNSEL" if user_side == "petitioner" else "RESPONDENT'S COUNSEL"
    
    # TURN VALIDATION: Only user should answer during cross-exam
    awaiting = session.get("awaiting_action", "user")
    if awaiting != "user":
        return {"error": f"Cannot submit answer now. Awaiting {awaiting}'s action."}
    
    # Count how many QUESTIONS have been asked by opposing counsel
    all_questions = [
        e for e in session.get("transcript", [])
        if e.get("speaker") == "OPPOSING_COUNSEL" and e.get("entry_type") in ["cross_exam_question", "question", "answer_request"]
    ]
    current_question_number = len(all_questions)  # This is the question the user is answering
    next_question_number = current_question_number + 1  # This will be the next question if there is one
    
    # Add user's answer
    add_transcript_entry(
        session_id=session_id,
        speaker=user_side.upper(),
        role_label=user_label,
        content=user_answer,
        entry_type="answer",
    )
    
    # Detect concessions in answer
    new_concessions = _detect_concessions(user_answer, session_id, session["current_round"])
    
    # If more questions remaining (max 3 total), get next question
    if next_question_number <= 3:
        query = " ".join(session.get("legal_issues", []))
        retrieved_precedents = _retrieve_for_court(query, session)
        
        fresh_session = get_session(session_id)
        full_context = _build_full_context(fresh_session)
        combined_context = full_context + "\n\n=== RETRIEVED PRECEDENTS ===\n" + retrieved_precedents if retrieved_precedents else full_context
        
        cross_messages = build_cross_examination_prompt(
            session=fresh_session,
            question_number=next_question_number,
            retrieved_context=combined_context,
        )
        
        try:
            next_question = _call_llm(cross_messages)
        except Exception as e:
            next_question = f"Question {next_question_number}: Counsel, would you agree that [question]?"
        
        add_transcript_entry(
            session_id=session_id,
            speaker="OPPOSING_COUNSEL",
            role_label="RESPONDENT'S COUNSEL" if user_side == "petitioner" else "PETITIONER'S COUNSEL",
            content=next_question,
            entry_type="cross_exam_question",
        )
        
        # UPDATE awaiting_action: Waiting for answer to next question
        update_session(session_id, {"awaiting_action": "user"})
        
        return {
            "opposing_response": next_question,
            "judge_question": "",
            "registrar_note": f"Question {next_question_number} of 3.",
            "trap_detected": False,
            "trap_warning": "",
            "new_concessions": new_concessions,
            "round_number": session["current_round"],
            "phase": "cross_examination",
            "cross_exam_complete": False,
            "session_ended": False,
        }
    
    else:
        # Cross-examination complete — advance to closing
        advance_phase(session_id)
        registrar_note = build_round_announcement(session, session["current_round"], "closing")
        
        add_transcript_entry(
            session_id=session_id,
            speaker="REGISTRAR",
            role_label="COURT REGISTRAR",
            content=registrar_note,
            entry_type="announcement",
        )
        
        # UPDATE awaiting_action: User gets closing arguments
        update_session(session_id, {"awaiting_action": "user"})
        
        return {
            "opposing_response": "",
            "judge_question": "",
            "registrar_note": registrar_note,
            "trap_detected": False,
            "trap_warning": "",
            "new_concessions": new_concessions,
            "round_number": session["current_round"],
            "phase": "closing",
            "cross_exam_complete": True,
            "session_ended": False,
        }


def _handle_closing(session_id: str, user_closing: str, session: Dict) -> Dict:
    """Handle closing arguments from both sides, then generate analysis.
    
    In proper moot court procedure:
    - Petitioner's counsel gives closing first
    - Respondent's counsel gives rebuttal closing
    - Petitioner does NOT get final rebuttal
    
    This handler manages both sides appropriately based on user_side.
    """
    
    user_side = session["user_side"]
    user_label = "PETITIONER'S COUNSEL" if user_side == "petitioner" else "RESPONDENT'S COUNSEL"
    
    # Check if this is first or second closing
    closing_count = len([e for e in session.get("transcript", []) if e.get("entry_type") == "closing_argument"])
    
    # TURN VALIDATION
    awaiting = session.get("awaiting_action", "user")
    if awaiting != "user":
        return {"error": f"Cannot submit closing now. It is {awaiting}'s turn."}
    
    # Add user's closing
    add_transcript_entry(
        session_id=session_id,
        speaker=user_side.upper(),
        role_label=user_label,
        content=user_closing,
        entry_type="closing_argument",
    )
    
    fresh_session = get_session(session_id)
    
    # If user is petitioner (first closing), get opposing rebuttal
    # If user is respondent, we're done and can finalize
    if user_side == "petitioner":
        # Get respondent's rebuttal closing
        closing_messages = build_opposing_closing_prompt(fresh_session)
        try:
            opposing_closing = _call_llm(closing_messages)
        except Exception as e:
            opposing_closing = (
                "My Lords, with respect, the submissions of the Petitioner's Counsel "
                "are fundamentally flawed. For the reasons we have advanced, the petition should be dismissed."
            )
        
        add_transcript_entry(
            session_id=session_id,
            speaker="OPPOSING_COUNSEL",
            role_label="RESPONDENT'S COUNSEL",
            content=opposing_closing,
            entry_type="closing_argument",
        )
        
        # Mark that session is ending
        update_session(session_id, {"awaiting_action": "judge"})
        
        intermediate_return = {
            "opposing_response": opposing_closing,
            "judge_question": "",
            "registrar_note": "Respondent's counsel has concluded. The matter is now with the Court.",
            "trap_detected": False,
            "trap_warning": "",
            "new_concessions": [],
            "round_number": session["current_round"],
            "phase": "closing",
            "closing_step": "second_closing_done",
            "ready_for_analysis": False,
            "session_ended": False,
        }
    else:
        # User is respondent and just gave rebuttal — session is complete
        update_session(session_id, {"awaiting_action": "judge"})
        intermediate_return = {
            "opposing_response": "",
            "judge_question": "",
            "registrar_note": "Respondent's counsel has concluded. The matter is now with the Court.",
            "trap_detected": False,
            "trap_warning": "",
            "new_concessions": [],
            "round_number": session["current_round"],
            "phase": "closing",
            "closing_step": "respondent_closing_done",
            "ready_for_analysis": True,
            "session_ended": False,
        }
    
    # Get judge's final observations
    fresh_session = get_session(session_id)
    judge_closing_messages = build_judge_closing_prompt(fresh_session)
    try:
        judge_final = _call_llm(judge_closing_messages)
    except Exception as e:
        judge_final = (
            "The court has heard submissions from both sides. The judgment is reserved."
        )
    
    add_transcript_entry(
        session_id=session_id,
        speaker="JUDGE",
        role_label="HON'BLE COURT",
        content=judge_final,
        entry_type="observation",
    )
    
    # Registrar closes session
    registrar_final = build_round_announcement(session, session["current_round"], "completed")
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=registrar_final,
        entry_type="announcement",
    )
    
    advance_phase(session_id)
    
    return {
        "opposing_response": intermediate_return["opposing_response"],
        "judge_question": judge_final,
        "registrar_note": registrar_final,
        "trap_detected": False,
        "trap_warning": "",
        "new_concessions": [],
        "round_number": session["current_round"],
        "phase": "completed",
        "ready_for_analysis": True,
        "session_ended": True,
    }


def generate_session_analysis(session_id: str) -> Dict:
    """
    Call the Summariser agent to generate full session analysis.
    Called after phase == "completed".
    """
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    
    if session["phase"] != "completed":
        return {"error": "Session not yet completed"}
    
    summariser_messages = build_summariser_prompt(session)
    
    try:
        raw_analysis = _call_llm(summariser_messages)
    except Exception as e:
        logger.error(f"Summariser LLM failed: {e}")
        raw_analysis = (
            "## OVERALL ASSESSMENT\n"
            "The moot court session has concluded. Analysis generation encountered an error.\n\n"
            "## PERFORMANCE SCORE\n5.0/10\n\n"
            "## OUTCOME PREDICTION\nUNKNOWN\n\n"
            "## FULL TRANSCRIPT\n" + _get_transcript_text(session)
        )
    
    parsed = parse_analysis(raw_analysis, session)
    
    update_session(session_id, {
        "analysis": parsed,
        "outcome_prediction": parsed.get("outcome_prediction", "unknown"),
        "performance_score": parsed.get("performance_score", 0.0),
    })
    
    return parsed


def process_objection(
    session_id: str,
    objection_type: str,
    objection_text: str,
) -> Dict:
    """Handle a user-raised objection. Pauses round and requests judge ruling."""
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    
    # Objection pauses the round — mark round as "objection_pending"
    phase = session.get("phase", "rounds")
    if phase not in ["rounds", "cross_examination"]:
        return {"error": "Cannot raise objection in current phase"}
    
    # Get what the objection is about from last transcript entry
    transcript = session.get("transcript", [])
    last_entry = transcript[-1] if transcript else {}
    objected_to = last_entry.get("content", "the last submission")[:200]
    
    # Judge rules on objection
    ruling_messages = build_objection_ruling_prompt(
        session=session,
        objection_type=objection_type,
        objection_text=objection_text,
        what_was_objected_to=objected_to,
    )
    
    try:
        ruling = _call_llm(ruling_messages)
    except Exception as e:
        ruling = "Objection overruled. Counsel may proceed."
    
    # Add to transcript
    add_transcript_entry(
        session_id=session_id,
        speaker="JUDGE",
        role_label="HON'BLE COURT",
        content=ruling,
        entry_type="ruling",
        metadata={"objection_type": objection_type},
    )
    
    sustained = "sustained" in ruling.lower()
    
    # After ruling, resume normal flow — mark awaiting_action as "user" to continue
    update_session(session_id, {"awaiting_action": "user"})
    
    return {
        "ruling": ruling,
        "sustained": sustained,
        "objection_resolved": True,
        "can_continue": True,
    }


def process_document_request(
    session_id: str,
    doc_type: str,
    for_side: str,
) -> Dict:
    """Generate a legal document for the session."""
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    
    system = f"""You are a legal document generator specializing in Indian court documents.

Generate a complete, properly formatted {doc_type} for a Supreme Court of India proceeding.

FORMAT REQUIREMENTS:
- Use proper Indian court document format
- Include: IN THE SUPREME COURT OF INDIA header
- Include: Case title, W.P./Crl.A./C.A. number placeholder
- Include: Parties section
- Include: Prayer/relief sought
- Include: Verification clause where applicable
- End with: Signature block with "Counsel for the [Petitioner/Respondent]"

The document must look like a real Indian court document.
Use the case details provided. Be specific — no placeholders except where genuinely needed."""

    case_brief = session.get("case_brief", "")
    user_side = session.get("user_side", "petitioner")
    
    filer = for_side if for_side != "yours" else user_side
    
    user_content = f"""Generate a {doc_type} for the following case:

{case_brief[:800]}

Document is filed by: {filer}
Legal issues: {', '.join(session.get('legal_issues', []))}

Generate the complete document."""

    try:
        document_text = _call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": user_content}
        ])
    except Exception as e:
        logger.error(f"Document generation failed: {e}")
        document_text = f"[Document generation failed: {e}]"
    
    doc_entry = {
        "type": doc_type,
        "for_side": for_side,
        "content": document_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "round": session.get("current_round", 0),
    }
    
    session_obj = get_session(session_id)
    docs = session_obj.get("documents_produced", [])
    docs.append(doc_entry)
    update_session(session_id, {"documents_produced": docs})
    
    # Registrar announcement
    registrar_note = get_document_announcement(doc_type, f"{filer}'s counsel")
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=registrar_note,
        entry_type="document",
        metadata={"doc_type": doc_type},
    )
    
    return {
        "document": document_text,
        "doc_type": doc_type,
        "registrar_note": registrar_note,
    }


def start_cross_examination(session_id: str) -> Dict:
    """
    Initiate cross-examination phase.
    Opposing counsel asks the first question.
    """
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    
    advance_phase(session_id)
    fresh_session = get_session(session_id)
    
    query = " ".join(fresh_session.get("legal_issues", []))
    retrieved_context = _retrieve_for_court(query, fresh_session)
    
    cross_messages = build_cross_examination_prompt(
        session=fresh_session,
        question_number=1,
        retrieved_context=retrieved_context,
    )
    
    try:
        first_question = _call_llm(cross_messages)
    except Exception as e:
        first_question = "Counsel, would you agree that the right you rely upon is subject to reasonable restrictions under the Constitution?"
    
    user_side = session.get("user_side", "petitioner")
    add_transcript_entry(
        session_id=session_id,
        speaker="OPPOSING_COUNSEL",
        role_label="RESPONDENT'S COUNSEL" if user_side == "petitioner" else "PETITIONER'S COUNSEL",
        content=first_question,
        entry_type="question",
    )
    
    registrar_note = build_round_announcement(session, session["current_round"], "cross_examination")
    add_transcript_entry(
        session_id=session_id,
        speaker="REGISTRAR",
        role_label="COURT REGISTRAR",
        content=registrar_note,
        entry_type="announcement",
    )
    
    return {
        "first_question": first_question,
        "registrar_note": registrar_note,
        "phase": "cross_examination",
    }


# ── Helper functions ───────────────────────────────────────────

def _extract_key_claims(argument_text: str) -> List[str]:
    """Extract key legal claims from argument text for inconsistency tracking."""
    import re
    
    claim_patterns = [
        r'(?:the\s+)?(?:right|provision|section|article)\s+(?:to\s+)?[\w\s]{5,40}',
        r'(?:is|was|are|were)\s+(?:not|never|always|clearly)\s+[\w\s]{5,30}',
        r'(?:cannot|shall not|must not)\s+[\w\s]{5,30}',
    ]
    
    claims = []
    text_lower = argument_text.lower()
    
    for pattern in claim_patterns:
        matches = re.findall(pattern, text_lower)
        claims.extend([m.strip()[:80] for m in matches[:2]])
    
    return claims[:5]


def _detect_concessions(
    text: str,
    session_id: str,
    round_number: int,
) -> List[Dict]:
    """
    Simple rule-based concession detector.
    Looks for concession language patterns.
    """
    import re
    
    concession_patterns = [
        (r'(?:i\s+)?(?:accept|concede|admit|acknowledge)\s+that\s+([^.]{20,200})', "Direct concession"),
        (r'(?:you\s+are\s+right|that\s+is\s+correct|i\s+agree)\s+(?:that\s+)?([^.]{20,200})', "Agreement concession"),
        (r'(?:while|although|even\s+though)\s+(?:i\s+)?(?:accept|concede|admit)\s+([^.]{20,200})', "Qualified concession"),
        (r'(?:for\s+the\s+purposes\s+of\s+this\s+argument|without\s+prejudice)\s+([^.]{20,200})', "Argumentative concession"),
    ]
    
    new_concessions = []
    text_lower = text.lower()
    
    for pattern, significance_prefix in concession_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            quote = match.group(0)[:150]
            conceded_point = match.group(1)[:100] if match.lastindex else quote
            
            add_concession(
                session_id=session_id,
                exact_quote=quote,
                legal_significance=f"{significance_prefix}: {conceded_point}",
            )
            
            new_concessions.append({
                "quote": quote,
                "significance": f"{significance_prefix}: {conceded_point}",
                "round": round_number,
            })
    
    return new_concessions


def _did_user_fall_in_trap(user_argument: str, trap_type: str) -> bool:
    """
    Heuristic to determine if user fell into a trap.
    Returns True if user's argument shows they took the bait.
    """
    arg_lower = user_argument.lower()
    
    if trap_type == "admission_trap":
        # User fell in if they agreed with the trap statement
        fall_markers = ["yes", "agree", "correct", "right", "indeed", "certainly", "that is true"]
        return any(marker in arg_lower[:200] for marker in fall_markers)
    
    elif trap_type == "inconsistency_trap":
        # User fell in if they tried to reconcile the inconsistency poorly
        fall_markers = ["both", "however", "but in this case", "that was different"]
        return any(marker in arg_lower[:200] for marker in fall_markers)
    
    return False


def _get_transcript_text(session: Dict) -> str:
    """Simple transcript formatter for fallback."""
    transcript = session.get("transcript", [])
    lines = []
    for entry in transcript:
        lines.append(f"{entry['role_label'].upper()}: {entry['content']}")
        lines.append("")
    return "\n".join(lines)
