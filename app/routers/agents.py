"""Classroom Group Analysis Agent HTTP 接口。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.service import run_group_analysis
from app.agents.state import TOOL_STATES
from app.agents.tools import CLASSROOM_TOOLS
from app.core.database import get_db


router = APIRouter()


class GroupAnalysisRequest(BaseModel):
    meeting_id: int = Field(gt=0)
    question: str = Field(min_length=1)
    max_turns: int = Field(default=8, ge=1, le=12)


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
