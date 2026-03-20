"""
Court Session Manager.

Single source of truth for everything that happens in a moot court session.
Every agent reads from and writes to the session object.
Sessions persist to HuggingFace Dataset for durability across container restarts.

Session lifecycle:
  created → briefing → rounds → cross_examination → closing → completed

WHY store to HF Dataset?
HF Spaces containers are ephemeral. Without durable storage, all session
data is lost on restart. HF Dataset API gives us free durable storage
using the same HF_TOKEN already in the Space secrets.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

HF_TOKEN = os.getenv("HF_TOKEN")
SESSIONS_REPO = "CaffeinatedCoding/nyayasetu-court-sessions"

# ── In-memory session store ────────────────────────────────────
# Primary store during runtime. HF Dataset is the durable backup.
_sessions: Dict[str, Dict] = {}


# ── Data structures ────────────────────────────────────────────

@dataclass
class TranscriptEntry:
    """A single entry in the court transcript."""
    speaker: str           # JUDGE | OPPOSING_COUNSEL | REGISTRAR | PETITIONER | RESPONDENT
    role_label: str        # Display label e.g. "HON'BLE COURT", "RESPONDENT'S COUNSEL"
    content: str           # The actual text
    round_number: int      # Which round this belongs to
    phase: str             # briefing | argument | cross_examination | closing
    timestamp: str         # ISO timestamp
    entry_type: str        # argument | question | observation | objection | ruling | document | trap
    metadata: Dict = field(default_factory=dict)  # extra data e.g. trap_type, precedents_cited


@dataclass
class Concession:
    """A concession made by the user during the session."""
    round_number: int
    exact_quote: str       # The exact text where concession was made
    legal_significance: str  # What opposing counsel can do with this
    exploited: bool = False  # Has opposing counsel used this yet


@dataclass
class TrapEvent:
    """A trap set by opposing counsel."""
    round_number: int
    trap_type: str         # admission_trap | precedent_trap | inconsistency_trap
    trap_text: str         # What opposing counsel said to set the trap
    user_fell_in: bool     # Whether user fell into the trap
    user_response: str = ""  # What user said in response


@dataclass
class CourtSession:
    """Complete court session state."""
    
    # Identity
    session_id: str
    created_at: str
    updated_at: str
    
    # Case
    case_title: str
    user_side: str           # petitioner | respondent
    user_client: str
    opposing_party: str
    legal_issues: List[str]
    brief_facts: str
    jurisdiction: str        # supreme_court | high_court | district_court
    
    # Setup
    bench_composition: str   # single | division | constitutional
    difficulty: str          # moot | standard | adversarial
    session_length: str      # brief | standard | extended
    show_trap_warnings: bool
    
    # Derived from research session import
    imported_from_session: Optional[str]  # NyayaSetu research session ID
    case_brief: str          # Generated case brief text
    retrieved_precedents: List[Dict]  # Precedents from research session
    
    # Session progress
    phase: str               # briefing | rounds | cross_examination | closing | completed
    current_round: int
    max_rounds: int          # 3 | 5 | 8
    
    # Transcript
    transcript: List[Dict]   # List of TranscriptEntry as dicts
    
    # Tracking
    concessions: List[Dict]  # List of Concession as dicts
    trap_events: List[Dict]  # List of TrapEvent as dicts
    cited_precedents: List[str]  # Judgment IDs cited during session
    documents_produced: List[Dict]  # Documents generated during session
    
    # Arguments tracking for inconsistency detection
    user_arguments: List[Dict]  # [{round, text, key_claims: []}]
    
    # Analysis (populated at end)
    analysis: Optional[Dict]
    outcome_prediction: Optional[str]
    performance_score: Optional[float]


def create_session(
    case_title: str,
    user_side: str,
    user_client: str,
    opposing_party: str,
    legal_issues: List[str],
    brief_facts: str,
    jurisdiction: str,
    bench_composition: str,
    difficulty: str,
    session_length: str,
    show_trap_warnings: bool,
    imported_from_session: Optional[str] = None,
    case_brief: str = "",
    retrieved_precedents: Optional[List[Dict]] = None,
) -> str:
    """
    Create a new court session. Returns session_id.
    """
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    max_rounds_map = {"brief": 3, "standard": 5, "extended": 8}
    
    session = CourtSession(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        case_title=case_title,
        user_side=user_side,
        user_client=user_client,
        opposing_party=opposing_party,
        legal_issues=legal_issues,
        brief_facts=brief_facts,
        jurisdiction=jurisdiction,
        bench_composition=bench_composition,
        difficulty=difficulty,
        session_length=session_length,
        show_trap_warnings=show_trap_warnings,
        imported_from_session=imported_from_session,
        case_brief=case_brief,
        retrieved_precedents=retrieved_precedents or [],
        phase="briefing",
        current_round=0,
        max_rounds=max_rounds_map.get(session_length, 5),
        transcript=[],
        concessions=[],
        trap_events=[],
        cited_precedents=[],
        documents_produced=[],
        user_arguments=[],
        analysis=None,
        outcome_prediction=None,
        performance_score=None,
    )
    
    _sessions[session_id] = asdict(session)
    logger.info(f"Session created: {session_id} | {case_title}")
    
    return session_id


def get_session(session_id: str) -> Optional[Dict]:
    """Get session from memory. Returns None if not found."""
    return _sessions.get(session_id)


def update_session(session_id: str, updates: Dict) -> bool:
    """Apply updates to session and persist to HF."""
    if session_id not in _sessions:
        logger.warning(f"Session not found: {session_id}")
        return False
    
    _sessions[session_id].update(updates)
    _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Async persist to HF Dataset
    _persist_session(session_id)
    
    return True


def add_transcript_entry(
    session_id: str,
    speaker: str,
    role_label: str,
    content: str,
    entry_type: str = "argument",
    metadata: Optional[Dict] = None,
) -> bool:
    """Add a new entry to the session transcript."""
    session = get_session(session_id)
    if not session:
        return False
    
    entry = asdict(TranscriptEntry(
        speaker=speaker,
        role_label=role_label,
        content=content,
        round_number=session["current_round"],
        phase=session["phase"],
        timestamp=datetime.now(timezone.utc).isoformat(),
        entry_type=entry_type,
        metadata=metadata or {},
    ))
    
    session["transcript"].append(entry)
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    _persist_session(session_id)
    return True


def add_concession(
    session_id: str,
    exact_quote: str,
    legal_significance: str,
) -> bool:
    """Record a concession made by the user."""
    session = get_session(session_id)
    if not session:
        return False
    
    concession = asdict(Concession(
        round_number=session["current_round"],
        exact_quote=exact_quote,
        legal_significance=legal_significance,
    ))
    
    session["concessions"].append(concession)
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info(f"Concession recorded in session {session_id}: {exact_quote[:80]}")
    return True


def add_trap_event(
    session_id: str,
    trap_type: str,
    trap_text: str,
    user_fell_in: bool = False,
    user_response: str = "",
) -> bool:
    """Record a trap event."""
    session = get_session(session_id)
    if not session:
        return False
    
    trap = asdict(TrapEvent(
        round_number=session["current_round"],
        trap_type=trap_type,
        trap_text=trap_text,
        user_fell_in=user_fell_in,
        user_response=user_response,
    ))
    
    session["trap_events"].append(trap)
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    return True


def add_user_argument(
    session_id: str,
    argument_text: str,
    key_claims: List[str],
) -> bool:
    """Track user's argument for inconsistency detection."""
    session = get_session(session_id)
    if not session:
        return False
    
    session["user_arguments"].append({
        "round": session["current_round"],
        "text": argument_text,
        "key_claims": key_claims,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return True


def advance_phase(session_id: str) -> str:
    """
    Move session to next phase.
    Returns new phase name.
    """
    session = get_session(session_id)
    if not session:
        return ""
    
    phase_progression = {
        "briefing": "rounds",
        "rounds": "cross_examination",
        "cross_examination": "closing",
        "closing": "completed",
    }
    
    current = session["phase"]
    next_phase = phase_progression.get(current, "completed")
    
    update_session(session_id, {"phase": next_phase})
    logger.info(f"Session {session_id} advanced: {current} → {next_phase}")
    
    return next_phase


def advance_round(session_id: str) -> int:
    """Increment round counter. Returns new round number."""
    session = get_session(session_id)
    if not session:
        return 0
    
    new_round = session["current_round"] + 1
    
    # Auto-advance phase when max rounds reached
    if new_round > session["max_rounds"] and session["phase"] == "rounds":
        advance_phase(session_id)
    
    update_session(session_id, {"current_round": new_round})
    return new_round


def get_all_sessions() -> List[Dict]:
    """Return all sessions, sorted by updated_at descending."""
    sessions = list(_sessions.values())
    return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)


def get_session_transcript_text(session_id: str) -> str:
    """
    Return full transcript as formatted text for LLM consumption.
    Format matches real court transcript style.
    """
    session = get_session(session_id)
    if not session:
        return ""
    
    lines = [
        f"IN THE {session['jurisdiction'].upper().replace('_', ' ')}",
        f"Case: {session['case_title']}",
        f"Petitioner: {session['user_client'] if session['user_side'] == 'petitioner' else session['opposing_party']}",
        f"Respondent: {session['opposing_party'] if session['user_side'] == 'petitioner' else session['user_client']}",
        "",
        "PROCEEDINGS:",
        "",
    ]
    
    for entry in session["transcript"]:
        lines.append(f"{entry['role_label'].upper()}")
        lines.append(entry["content"])
        lines.append("")
    
    return "\n".join(lines)


def _persist_session(session_id: str):
    """
    Persist session to HuggingFace Dataset.
    Fails silently — in-memory session is still valid.
    """
    if not HF_TOKEN:
        return
    
    try:
        from huggingface_hub import HfApi
        import threading
        
        def _upload():
            api = HfApi(token=HF_TOKEN)
            session_data = json.dumps(_sessions[session_id], ensure_ascii=False)
            
            try:
                api.create_repo(
                    repo_id=SESSIONS_REPO,
                    repo_type="dataset",
                    private=True,
                    exist_ok=True
                )
            except Exception:
                pass
            
            api.upload_file(
                path_or_fileobj=session_data.encode(),
                path_in_repo=f"sessions/{session_id}.json",
                repo_id=SESSIONS_REPO,
                repo_type="dataset",
                token=HF_TOKEN
            )
        
        # Run in background thread — never blocks the response
        thread = threading.Thread(target=_upload, daemon=True)
        thread.start()
        
    except Exception as e:
        logger.warning(f"Session persist failed (non-critical): {e}")


def load_sessions_from_hf():
    """
    Load all sessions from HF Dataset on startup.
    Called once from api/main.py after download_models().
    """
    if not HF_TOKEN:
        logger.warning("No HF_TOKEN — sessions will not persist across restarts")
        return
    
    try:
        from huggingface_hub import HfApi, list_repo_files
        
        api = HfApi(token=HF_TOKEN)
        
        try:
            files = list(api.list_repo_files(
                repo_id=SESSIONS_REPO,
                repo_type="dataset",
                token=HF_TOKEN
            ))
        except Exception:
            logger.info("No existing sessions on HF — starting fresh")
            return
        
        session_files = [f for f in files if f.startswith("sessions/") and f.endswith(".json")]
        
        loaded = 0
        for filepath in session_files:
            try:
                from huggingface_hub import hf_hub_download
                local_path = hf_hub_download(
                    repo_id=SESSIONS_REPO,
                    filename=filepath,
                    repo_type="dataset",
                    token=HF_TOKEN
                )
                with open(local_path) as f:
                    session_data = json.load(f)
                session_id = session_data.get("session_id")
                if session_id:
                    _sessions[session_id] = session_data
                    loaded += 1
            except Exception:
                continue
        
        logger.info(f"Loaded {loaded} sessions from HF Dataset")
        
    except Exception as e:
        logger.warning(f"Session load from HF failed (non-critical): {e}")
