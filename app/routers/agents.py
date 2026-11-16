"""Classroom Group Analysis Agent HTTP 接口。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.service import run_group_analysis
from app.agents.state import TOOL_STATES
from app.agents.tools import CLASSROOM_TOOLS
from app.core.database import get_db
from app.services.classroom_agent_service import classroom_agent_service


router = APIRouter()


class GroupAnalysisRequest(BaseModel):
    meeting_id: int = Field(gt=0)
    question: str = Field(min_length=1)
    max_turns: int = Field(default=8, ge=1, le=12)


class ActionConfirmationRequest(BaseModel):
    meeting_id: int = Field(gt=0)
    target: str = ""
    action: str = Field(min_length=1)
    script: str = ""
    expected: str = ""
    risk: str = ""
    evidence: list[str] = Field(default_factory=list)


@router.post("/api/agents/group-analysis")
async def analyze_classroom_group(
    payload: GroupAnalysisRequest,
    db: Session = Depends(get_db),
):
    try:
        result = await run_group_analysis(
            db, payload.meeting_id, payload.question, payload.max_turns
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "analysis": result.model_dump()}


@router.get("/api/agents/group-analysis/tools")
def list_classroom_group_tools():
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_json_schema,
                "allowed_states": sorted(
                    state.value for state in TOOL_STATES.get(tool.name, frozenset())
                ),
            }
            for tool in CLASSROOM_TOOLS
        ]
    }


@router.get("/api/agents/group-analysis/metrics/{meeting_id}")
def get_group_analysis_metrics(
    meeting_id: int,
    db: Session = Depends(get_db),
):
    return classroom_agent_service.get_metrics(db, meeting_id)


@router.post("/api/agents/group-analysis/actions/confirm")
def confirm_group_analysis_action(
    payload: ActionConfirmationRequest,
    db: Session = Depends(get_db),
):
    result = classroom_agent_service.confirm_action(
        db,
        payload.meeting_id,
        target=payload.target,
        action=payload.action,
        script=payload.script,
        expected=payload.expected,
        risk=payload.risk,
        evidence=payload.evidence,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "动作确认失败"))
    return result
