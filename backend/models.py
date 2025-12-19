from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class Change(BaseModel):
    category: str
    type: Literal["added", "modified", "removed"]
    risk_score: float = Field(..., description="Heuristic risk score used for ranking")
    similarity: Optional[float] = None
    old_index: Optional[int] = None
    new_index: Optional[int] = None
    old: Optional[str] = None
    new: Optional[str] = None
    explanation: str
    suggested_action: str


class AnalysisEngineInfo(BaseModel):
    mode: Literal["basic", "semantic"]
    model_name: Optional[str] = None
    num_changes: int


class PolicyVersionInfo(BaseModel):
    id: str
    fetched_at: str


class AnalyzeResponse(BaseModel):
    service_id: Optional[str] = None
    doc_type: Optional[str] = None
    source: Optional[str] = None
    old_version: Optional[PolicyVersionInfo] = None
    new_version: Optional[PolicyVersionInfo] = None
    engine: AnalysisEngineInfo
    changes: List[Change]


class CompareRequest(BaseModel):
    old_text: str
    new_text: str
    mode: Literal["basic", "semantic"] = "semantic"
    max_changes: Optional[int] = None
