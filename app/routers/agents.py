"""Classroom Group Analysis Agent HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.agents.service import run_group_analysis
from app.agents.state import TOOL_STATES
from app.agents.tools import CLASSROOM_TOOLS
from app.core.database import get_db
from app.core.meeting_state import CREATED
from app.models import Meeting
from app.services.classroom_agent_service import classroom_agent_service
from app.services.session_service import SessionContext, require_session

router = APIRouter()


class GroupAnalysisRequest(BaseModel):
    meeting_id: int = Field(gt=0)
    question: str = Field(min_length=1)
    max_turns: int = Field(default=8, ge=1, le=12)


class ActionConfirmationRequest(BaseModel):
    meeting_id: int = Field(gt=0)
    target: Annotated[str, StringConstraints(max_length=50)] = ""
    action: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    script: Annotated[str, StringConstraints(max_length=2000)] = ""
    expected: Annotated[str, StringConstraints(max_length=2000)] = ""
    risk: Annotated[str, StringConstraints(max_length=2000)] = ""
    evidence: list[Annotated[str, StringConstraints(max_length=100)]] = Field(
        default_factory=list, max_length=50
    )


@router.post("/api/agents/group-analysis")
async def analyze_classroom_group(
    payload: GroupAnalysisRequest,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    if ctx.user.role != "teacher":
        raise HTTPException(status_code=403, detail="只有教师可以运行课堂分析")
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


@router.post("/api/agents/group-analysis/actions/confirm")
def confirm_group_analysis_action(
    payload: ActionConfirmationRequest,
    db: Session = Depends(get_db),
    ctx: SessionContext = Depends(require_session),
):
    meeting = db.query(Meeting).filter(Meeting.id == payload.meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="课堂不存在")
    if ctx.user.role != "teacher" or int(meeting.teacher_id) != int(ctx.user.id):
        raise HTTPException(status_code=403, detail="只有本课堂教师可以确认干预动作")
    if meeting.status == CREATED:
        raise HTTPException(status_code=409, detail="课堂尚未开始")

    result = classroom_agent_service.confirm_action(
        db,
        payload.meeting_id,
        target=payload.target,
        action=payload.action,
        script=payload.script,
        expected=payload.expected,
        risk=payload.risk,
        evidence=payload.evidence,
        confirmed_by=int(ctx.user.id),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "动作确认失败"))
    return result
