from typing import List, Dict, Any
from pydantic import BaseModel


class FeatureTicket(BaseModel):
    title: str
    summary: str


class PatchPlan(BaseModel):
    summary: str
    files_to_touch: List[str]
    risk_notes: List[str]


class GeneratedFile(BaseModel):
    path: str
    content: str


class PatchDraft(BaseModel):
    summary: str
    files: List[GeneratedFile]
    release_note: str


class ToolResult(BaseModel):
    name: str
    ok: bool
    payload: Dict[str, Any]


class PipelineReport(BaseModel):
    request_title: str
    outcome: str
    reasons: List[str]
    patch_plan: PatchPlan
    tool_results: List[ToolResult]
    release_note: str