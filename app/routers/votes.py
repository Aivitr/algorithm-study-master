"""课堂投票域的路由。

本组共 3 条，按课堂投票的生命周期排列：

    /api/cast-vote      学生投票
    /api/close-vote     教师结束投票，触发统计与 AI 归纳
    /api/confirm-vote   学生确认（vote_confirmations 记在连接管理器上）

`manager` 取自 `app.realtime.registry`——**不能** `from server import manager`，
见 `app/routers/__init__.py`。registry 里的那个实例与 `server.manager` 是同一个
对象，因此 `manager.vote_confirmations` 与 WebSocket 路由看到的是同一份状态。

`datetime` 必须在**模块级**导入：`confirm_vote` 用的是 `datetime.now()`。
`close_vote` 函数体内另有一处局部 `from datetime import datetime`——那只对
它自己可见，**不能**覆盖 `confirm_vote`。少这个模块级导入不是导入失败，而是
运行到 `/api/confirm-vote` 才 NameError，再被该处理器的 try/except 吞成
`{"status":"error"}` 的 200 响应（见 `tests_safe/test_module_free_names.py`）。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Meeting, ViewpointVote
from app.realtime.registry import manager
from app.services.llm_service import llm

router = APIRouter()


def _claim_vote_close(
    db: Session,
    vote_id: int,
    meeting_id: int,
    winner_id: int | None,
) -> bool:
    """原子取得投票关闭权，确保关闭后的副作用只执行一次。"""
    updated_rows = (
        db.query(ViewpointVote)
        .filter(
            ViewpointVote.id == vote_id,
            ViewpointVote.meeting_id == meeting_id,
            ViewpointVote.status == "active",
        )
        .update(
            {
                ViewpointVote.status: "closed",
                ViewpointVote.winner_viewpoint_id: winner_id,
                ViewpointVote.closed_at: datetime.now(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return updated_rows == 1


@router.post("/api/cast-vote")
async def cast_vote(
    vote_id: int = Form(...),
    viewpoint_id: int = Form(...),
    username: str = Form(...),
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """学生投票"""
    try:
        vote_record = db.query(ViewpointVote).filter(ViewpointVote.id == vote_id).first()
        if not vote_record or vote_record.status != "active":
            return {"status": "error", "message": "投票不存在或已关闭"}

        # 获取投票数据
        votes = vote_record.votes or {}
        vp_key = str(viewpoint_id)

        # 移除旧投票
        for k in votes:
            if username in votes[k]:
                votes[k].remove(username)

        # 添加新投票
        if vp_key not in votes:
            votes[vp_key] = []
        votes[vp_key].append(username)

        vote_record.votes = votes
        db.commit()

        # 统计票数
        vote_counts = {k: len(v) for k, v in votes.items()}

        # 广播投票更新
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "vote_update",
            "vote_id": vote_id,
            "votes": votes,
            "vote_counts": vote_counts,
            "voter": username,
            "voted_for": viewpoint_id
        })

        return {"status": "success", "votes": votes, "vote_counts": vote_counts}
    except Exception as e:
        print(f"[ERROR] 投票失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/close-vote")
async def close_vote(
    vote_id: int = Form(...),
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """老师关闭投票"""
    try:
        vote_record = (
            db.query(ViewpointVote)
            .filter(
                ViewpointVote.id == vote_id,
                ViewpointVote.meeting_id == meeting_id,
            )
            .first()
        )
        if not vote_record:
            return {"status": "error", "message": "投票不存在或不属于当前课堂"}

        if vote_record.status != "active":
            return {
                "status": "success",
                "already_closed": True,
                "message": "投票已经关闭，本次未重复执行",
            }
        
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 统计票数
        votes = vote_record.votes or {}
        vote_counts = {k: len(v) for k, v in votes.items()}

        if not vote_counts:
            return {"status": "error", "message": "没有人投票"}
        
        winner_id = max(vote_counts, key=vote_counts.get)
        winner_viewpoint = None
        for vp in vote_record.viewpoints:
            if str(vp["id"]) == winner_id:
                winner_viewpoint = vp
                break
        
        if not winner_viewpoint:
            return {"status": "error", "message": "未找到获胜观点"}

        # 原子取得关闭权，只有一个请求可以继续产生后续副作用
        claimed = _claim_vote_close(
            db=db,
            vote_id=vote_id,
            meeting_id=meeting_id,
            winner_id=int(winner_id),
        )
        if not claimed:
            return {
                "status": "success",
                "already_closed": True,
                "message": "投票已经被其他请求关闭，本次未重复执行",
            }

        # 手动关闭后清理学生确认的内存状态
        manager.vote_confirmations.pop(vote_id, None)

        # 立刻广播：关闭投票弹窗
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "vote_result",
            "vote_id": vote_id,
            "winner_viewpoint": winner_viewpoint,
            "vote_counts": vote_counts,
            "sub_goals": [],
            "guidance": "",
            "updated_goals": None,
            "decomposing": True
        })

        # 同步执行 LLM 分解（像 quick_decompose 一样）
        try:
            print(f"[VOTE] 教师关闭投票，开始生成子目标, meeting_id={meeting_id}")
            sub_result = llm.generate_sub_goals(
                winner_viewpoint,
                meeting.topic,
                meeting.knowledge_points or []
            )
            print(f"[VOTE] LLM返回: {sub_result}")

            new_goals = list(meeting.knowledge_points or [])
            if sub_result.get("sub_goals"):
                for sg in sub_result["sub_goals"]:
                    new_goals.append({
                        "id": len(new_goals) + 1,
                        "desc": f"[深入探讨] {sg['desc']}",
                        "status": "pending",
                        "parent_viewpoint": winner_viewpoint.get("title", "")
                    })

            meeting.knowledge_points = new_goals
            db.commit()

            await manager.broadcast_to_meeting(meeting_id, {
                "type": "goals_updated",
                "updated_goals": new_goals,
                "main_viewpoint": winner_viewpoint.get("title", ""),
                "sub_goals": sub_result.get("sub_goals", []),
                "guidance": sub_result.get("guidance", "")
            })
            print(f"[VOTE] 教师关闭投票分解完成, 生成 {len(sub_result.get('sub_goals', []))} 个子目标")
        except Exception as ex:
            print(f"[ERROR] 教师关闭投票分解失败: {ex}")
            import traceback
            traceback.print_exc()
            await manager.broadcast_to_meeting(meeting_id, {
                "type": "goals_updated",
                "updated_goals": meeting.knowledge_points or [],
                "main_viewpoint": winner_viewpoint.get("title", "分解失败"),
                "sub_goals": [],
                "guidance": "任务分解失败，请稍后重试"
            })

        return {
            "status": "success",
            "winner_viewpoint": winner_viewpoint,
            "decomposing": True
        }
    except Exception as e:
        print(f"[ERROR] 关闭投票失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/confirm-vote")
async def confirm_vote(
    vote_id: int = Form(...),
    username: str = Form(...),
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """成员确认观点选择完毕，当所有在线成员都确认后自动结束投票并重新生成任务分解"""
    try:
        vote_record = (
            db.query(ViewpointVote)
            .filter(
                ViewpointVote.id == vote_id,
                ViewpointVote.meeting_id == meeting_id,
            )
            .first()
        )
        if not vote_record:
            return {"status": "error", "message": "投票不存在或不属于当前课堂"}

        if vote_record.status != "active":
            return {
                "status": "success",
                "already_closed": True,
                "message": "投票已经结束",
            }

        # 记录确认
        if vote_id not in manager.vote_confirmations:
            manager.vote_confirmations[vote_id] = set()
        manager.vote_confirmations[vote_id].add(username)

        confirmed = list(manager.vote_confirmations[vote_id])
        online = manager.get_online_members(meeting_id)

        # 广播确认状态
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "vote_confirm",
            "confirmed_members": confirmed,
            "total_online": len(online),
            "confirmer": username
        })

        # 检查是否所有在线成员都已确认
        all_confirmed = all(m in manager.vote_confirmations[vote_id] for m in online)
        if all_confirmed and len(online) >= 1:
            print(f"[VOTE] 所有成员已确认, 开始处理投票结果")
            # 所有人确认完毕 → 立刻关闭投票弹窗，同步分解任务
            votes = vote_record.votes or {}
            vote_counts = {k: len(v) for k, v in votes.items()}
            print(f"[VOTE] votes={votes}, vote_counts={vote_counts}")

            winner_id = None
            winner_viewpoint = None
            if vote_counts:
                winner_id = max(vote_counts, key=vote_counts.get)
                for vp in (vote_record.viewpoints or []):
                    if str(vp.get("id")) == str(winner_id):
                        winner_viewpoint = vp
                        break
            print(f"[VOTE] winner_id={winner_id}, winner_viewpoint={winner_viewpoint}")

            claimed = _claim_vote_close(
                db=db,
                vote_id=vote_id,
                meeting_id=meeting_id,
                winner_id=int(winner_id) if winner_id is not None else None,
            )
            if not claimed:
                manager.vote_confirmations.pop(vote_id, None)
                return {
                    "status": "success",
                    "already_closed": True,
                    "message": "投票已经被其他请求关闭，本次未重复执行",
                    "confirmed": confirmed,
                    "total_online": len(online),
                }

            manager.vote_confirmations.pop(vote_id, None)

            # 立刻广播：关闭投票弹窗
            await manager.broadcast_to_meeting(meeting_id, {
                "type": "vote_result",
                "winner_viewpoint": winner_viewpoint,
                "vote_counts": vote_counts,
                "decomposing": True
            })
            print(f"[VOTE] vote_result 已广播, 开始同步分解")

            # 同步执行 LLM 分解（像 quick_decompose 一样）
            try:
                meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
                winner_vp = winner_viewpoint or {"title": "无", "desc": ""}

                print(f"[VOTE] 开始生成子目标, meeting_id={meeting_id}")
                sub_result = llm.generate_sub_goals(
                    winner_vp,
                    meeting.topic,
                    meeting.knowledge_points or []
                )
                print(f"[VOTE] LLM返回: {sub_result}")

                new_goals = list(meeting.knowledge_points or [])
                for sg in sub_result.get("sub_goals", []):
                    new_goals.append({
                        "id": len(new_goals) + 1,
                        "desc": f"[深入探讨] {sg['desc']}",
                        "status": "pending",
                        "parent_viewpoint": winner_vp.get("title", "")
                    })

                meeting.knowledge_points = new_goals
                db.commit()

                # 广播分解结果到所有客户端
                await manager.broadcast_to_meeting(meeting_id, {
                    "type": "goals_updated",
                    "updated_goals": new_goals,
                    "main_viewpoint": winner_vp.get("title", ""),
                    "sub_goals": sub_result.get("sub_goals", []),
                    "guidance": sub_result.get("guidance", "")
                })
                print(f"[VOTE] 分解完成, 生成 {len(sub_result.get('sub_goals', []))} 个子目标")
            except Exception as ex:
                print(f"[ERROR] 分解失败: {ex}")
                import traceback
                traceback.print_exc()
                # 通知客户端分解失败，关闭加载状态
                await manager.broadcast_to_meeting(meeting_id, {
                    "type": "goals_updated",
                    "updated_goals": meeting.knowledge_points or [],
                    "main_viewpoint": winner_vp.get("title", "分解失败，请重试") if winner_viewpoint else "分解失败",
                    "sub_goals": [],
                    "guidance": "任务分解失败，请稍后重试"
                })

        return {"status": "success", "confirmed": confirmed, "total_online": len(online)}
    except Exception as e:
        print(f"[ERROR] confirm-vote: {e}")
        return {"status": "error", "message": str(e)}
