"""
Pydantic schemas for all court API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class NewSessionRequest(BaseModel):
    case_title: str
    user_side: str  # petitioner | respondent
    user_client: str
    opposing_party: str
    legal_issues: List[str]
    brief_facts: str
    jurisdiction: str = "supreme_court"
    bench_composition: str = "division"  # single | division | constitutional
    difficulty: str = "standard"         # moot | standard | adversarial
    session_length: str = "standard"     # brief | standard | extended
    show_trap_warnings: bool = True


class ImportSessionRequest(BaseModel):
    research_session_id: str
    user_side: str
    bench_composition: str = "division"
    difficulty: str = "standard"
    session_length: str = "standard"
    show_trap_warnings: bool = True


class ArgueRequest(BaseModel):
    session_id: str
    argument: str = Field(..., min_length=20, max_length=2000)


class ObjectionRequest(BaseModel):
    session_id: str
    objection_type: str
    objection_text: str = ""


class DocumentRequest(BaseModel):
    session_id: str
    doc_type: str
    for_side: str = "yours"  # yours | opposing | court_record


class EndSessionRequest(BaseModel):
    session_id: str


class TranscriptEntry(BaseModel):
    speaker: str
    role_label: str
    content: str
    round_number: int
    phase: str
    timestamp: str
    entry_type: str
    metadata: Dict = {}


class RoundResponse(BaseModel):
    opposing_response: str
    judge_question: str
    registrar_note: str
    trap_detected: bool
    trap_warning: str
    new_concessions: List[Dict]
    round_number: int
    phase: str
    cross_exam_complete: bool = False
    ready_for_analysis: bool = False


class SessionSummary(BaseModel):
    session_id: str
    case_title: str
    user_side: str
    phase: str
    current_round: int
    max_rounds: int
    created_at: str
    updated_at: str
    outcome_prediction: Optional[str]
    performance_score: Optional[float]
    concession_count: int
    trap_count: int
