"""随堂练习与测验域的路由。

本组 5 条，覆盖"出题产物 → 学生作答 → 批改 → 历史"这条链：

    GET  /api/download-exercises/{report_id}   把练习导出成文件下载
    POST /api/quiz-error-analysis              错题分析（调 LLM）
    POST /api/grade-short-answer               简答题评分（调 LLM）
    POST /api/submit-answer                    提交答案
    GET  /api/student-quiz-history/{user_id}   某学生的作答历史

`BASE_DIR` 与 `app/routers/pdf_report.py` 同理：从 `app.core.paths.PROJECT_ROOT`
同源重算（不能 `from server import`，见 `app/routers/__init__.py`），路径指向同一处。
"""

import asyncio
import os
import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.paths import PROJECT_ROOT
from app.models import Exercise, LearningReport, Meeting, StudentAnswer
from app.services.llm_service import llm

router = APIRouter()

BASE_DIR = str(PROJECT_ROOT)  # 与 server.py 的同名常量同源同值

@router.get("/api/download-exercises/{report_id}")
async def download_exercises(report_id: int, db: Session = Depends(get_db)):
    """下载练习题"""
    try:
        # 查询练习题
        exercises = db.query(Exercise).filter(Exercise.report_id == report_id).all()

        if not exercises:
            return {"status": "error", "message": "没有练习题"}

        report = db.query(LearningReport).filter(LearningReport.id == report_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == report.meeting_id).first()

        # 生成JSON格式
        exercise_dir = os.path.join(BASE_DIR, "storage", "exercises")
        os.makedirs(exercise_dir, exist_ok=True)
        filename = f"exercises_{report_id}_{int(time.time())}.txt"
        filepath = os.path.join(exercise_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"练习题集 - {meeting.topic if meeting else '未知课堂'}\n")
            f.write("=" * 50 + "\n\n")

            for i, ex in enumerate(exercises, 1):
                f.write(f"题目 {i}: {ex.question}\n")
                f.write(f"类型: {ex.question_type}\n")
                f.write(f"难度: {ex.difficulty}\n")

                if ex.options:
                    f.write("选项:\n")
                    # 处理不同格式
                    if isinstance(ex.options, dict):
                        for opt_key, opt_val in ex.options.items():
                            opt_text = str(opt_val or '').strip()
                            # 避免出现类似 “A. A. xxx” 的重复前缀
                            opt_text = re.sub(r'^\s*[A-Da-d]\s*[\.、:：]\s*', '', opt_text)
                            f.write(f"  {opt_key}. {opt_text}\n")
                    elif isinstance(ex.options, list):
                        for idx, opt in enumerate(ex.options):
                            opt_key = chr(65 + idx)  # A, B, C, D...
                            opt_text = str(opt or '').strip()
                            # 避免出现类似 “A. A. xxx” 的重复前缀
                            opt_text = re.sub(r'^\s*[A-Da-d]\s*[\.、:：]\s*', '', opt_text)
                            f.write(f"  {opt_key}. {opt_text}\n")
                    else:
                        f.write(f"  {ex.options}\n")

                f.write(f"知识点: {ex.knowledge_tag or '综合'}\n")
                f.write(f"答案: {ex.answer}\n")
                f.write("-" * 40 + "\n\n")
        
        return FileResponse(
            path=filepath,
            filename=f"??_{meeting.topic if meeting else 'exercises'}.txt",
            media_type="text/plain"
        )
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/quiz-error-analysis")
async def quiz_error_analysis(
    wrong_questions: str = Form(...),
    topic: str = Form(default=""),
    db: Session = Depends(get_db)
):
    """AI分析错题，给出学习建议"""
    try:
        import json as _json
        questions = _json.loads(wrong_questions)
        if not questions:
            return {"status": "success", "analysis": "没有错题，表现很棒！"}

        wrong_text = "\n".join([
            f"- 题目：{q.get('question', '未知')}\n  正确答案：{q.get('correctAnswer', '未知')}"
            for q in questions
        ])

        prompt = f"""课程主题：{topic}

以下是学生答错的题目：
{wrong_text}

请用Markdown格式分析这些错题，给出：
1. **易错知识点归纳**：列出学生可能薄弱的知识点
2. **错因分析**：分析常见的错误原因
3. **改进建议**：给出具体可操作的学习建议
4. **推荐复习方向**：指出应该重点复习的内容

请简洁明了，使用列表和加粗等格式突出重点，总字数控制在200-400字。"""

        try:
            response = llm.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位经验丰富的教育分析师，善于从错题中发现学生的薄弱点并给出针对性建议。使用Markdown格式回复。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=800
            )
            analysis = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] AI错题分析失败: {e}")
            analysis = f"**错题数量**：{len(questions)}道\n\n**涉及知识点**：{topic}\n\n建议重点复习相关知识点，多做类似练习题巩固理解。"

        return {"status": "success", "analysis": analysis}
    except Exception as e:
        print(f"[ERROR] quiz-error-analysis: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/grade-short-answer")
async def grade_short_answer(
    question: str = Form(...),
    correct_answer: str = Form(...),
    student_answer: str = Form(...),
    question_type: str = Form("简答题")
):
    """大模型评判简答/讨论题"""
    try:
        prompt = f"""你是一位严格但公正的阅卷老师，请评判学生的回答。

题目：{question}
参考答案：{correct_answer}
学生回答：{student_answer}
题目类型：{question_type}

评判标准：
- 如果是讨论题/开放题：答案不需要完全一致，但必须言之有理、观点明确、有逻辑性。空洞无意义的回答应判错。
- 如果是简答题：核心要点必须涵盖，表述可以不同但含义要正确。
- 只回答一两个字、敷衍了事的回答应判错。

请严格按以下JSON格式回复：
{{"is_correct": true或false, "feedback": "20-50字的评语，指出优点或不足"}}"""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, llm._call_json, prompt)
        is_correct = bool(result.get("is_correct", False))
        feedback = result.get("feedback", "")
        return {"status": "success", "is_correct": is_correct, "feedback": feedback}
    except Exception as e:
        print(f"[ERROR] grade-short-answer: {e}")
        return {"status": "success", "is_correct": True, "feedback": "评分服务暂不可用，默认通过"}


@router.post("/api/submit-answer")
async def submit_answer(
    exercise_id: int = Form(...),
    user_id: int = Form(...),
    answer_content: str = Form(...),
    is_correct: int = Form(...),
    db: Session = Depends(get_db)
):
    """保存学生答题记录"""
    try:
        # 检查是否已有该题的回答记录
        existing = db.query(StudentAnswer).filter(
            StudentAnswer.exercise_id == exercise_id,
            StudentAnswer.user_id == user_id
        ).first()

        if existing:
            existing.answer_content = answer_content
            existing.is_correct = is_correct
            existing.submitted_at = datetime.now()
        else:
            sa = StudentAnswer(
                exercise_id=exercise_id,
                user_id=user_id,
                answer_content=answer_content,
                is_correct=is_correct
            )
            db.add(sa)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] submit-answer: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/student-quiz-history/{user_id}")
async def get_student_quiz_history(user_id: int, db: Session = Depends(get_db)):
    """获取学生的答题历史统计"""
    try:
        answers = db.query(StudentAnswer).filter(StudentAnswer.user_id == user_id).all()
        total = len(answers)
        correct = sum(1 for a in answers if a.is_correct == 1)
        wrong = total - correct

        # 获取错题详情
        wrong_answers = [a for a in answers if a.is_correct == 0]
        wrong_details = []
        for wa in wrong_answers:
            ex = db.query(Exercise).filter(Exercise.id == wa.exercise_id).first()
            if ex:
                wrong_details.append({
                    "exercise_id": ex.id,
                    "question": ex.question,
                    "type": ex.question_type,
                    "correct_answer": ex.answer,
                    "student_answer": wa.answer_content,
                    "knowledge_tag": ex.knowledge_tag,
                    "submitted_at": wa.submitted_at.isoformat() if wa.submitted_at else None
                })

        return {
            "status": "success",
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
            "wrong_details": wrong_details
        }
    except Exception as e:
        print(f"[ERROR] student-quiz-history: {e}")
        return {"status": "error", "message": str(e)}
