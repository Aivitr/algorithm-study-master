"""PDF 报告导出域的路由。

本组 1 条：

    POST /api/generate-pdf-report    把学习报告渲染成 PDF 存到 storage/reports

路径锚点用 `BASE_DIR = str(PROJECT_ROOT)` 同源重算，不用 server.py 的常量
（不能 `from server import`，见 `app/routers/__init__.py`）。因此
`os.path.join(BASE_DIR, "storage", "reports")` 指向与 server.py 相同的目录。

路径锚点必须从 `app.core.paths.PROJECT_ROOT` 派生——`tests_safe/test_paths_anchor.py`
钉的就是它。
"""

import os
import time

from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.paths import PROJECT_ROOT
from app.models import LearningReport, Meeting, User

router = APIRouter()

BASE_DIR = str(PROJECT_ROOT)  # 与 server.py 的同名常量同源同值

@router.post("/api/generate-pdf-report")
async def generate_pdf_report(
    meeting_id: int = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """生成学习报告PDF文件"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import io

        # 注册中文字体
        chinese_font = 'Helvetica'
        font_paths = [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',      # Ubuntu wqy-zenhei
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',     # Ubuntu wqy-microhei
            '/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc',         # CentOS
            '/usr/share/fonts/chinese/simhei.ttf',                  # 手动安装
            'C:/Windows/Fonts/simhei.ttf',                          # Windows
            'C:/Windows/Fonts/msyh.ttc',                            # Windows 微软雅黑
        ]
        for fp in font_paths:
            try:
                if os.path.exists(fp):
                    if fp.endswith('.ttc'):
                        pdfmetrics.registerFont(TTFont('ChineseFont', fp, subfontIndex=0))
                    else:
                        pdfmetrics.registerFont(TTFont('ChineseFont', fp))
                    chinese_font = 'ChineseFont'
                    print(f"[OK] PDF中文字体已加载: {fp}")
                    break
            except Exception as fe:
                print(f"[WARN] 字体 {fp} 加载失败: {fe}")
                continue

        # 查询最新的报告
        report = db.query(LearningReport).filter(
            LearningReport.meeting_id == meeting_id,
            LearningReport.user_id == user_id
        ).order_by(LearningReport.created_at.desc()).first()

        if not report:
            return {"status": "error", "message": "报告不存在"}

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        user = db.query(User).filter(User.id == user_id).first()

        # 创建PDF文件
        pdf_dir = os.path.join(BASE_DIR, "storage", "reports")
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_filename = f"report_{meeting_id}_{user_id}_{int(time.time())}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)

        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        story = []
        styles = getSampleStyleSheet()

        # 定义样式
        title_style = ParagraphStyle(
            'ChineseTitle',
            parent=styles['Title'],
            fontName=chinese_font,
            fontSize=18
        )
        heading_style = ParagraphStyle(
            'ChineseHeading',
            parent=styles['Heading2'],
            fontName=chinese_font,
            fontSize=14
        )
        body_style = ParagraphStyle(
            'ChineseBody',
            parent=styles['Normal'],
            fontName=chinese_font,
            fontSize=11,
            leading=18
        )

        data = report.report_data

        # 标题
        story.append(Paragraph(f"学习报告 - {data.get('meeting_topic', '')}", title_style))
        story.append(Spacer(1, 20))

        # 基本信息
        story.append(Paragraph("基本信息", heading_style))
        story.append(Paragraph(f"学生姓名：{data.get('student_name', '')}", body_style))
        story.append(Paragraph(f"发言次数：{data.get('speech_count', 0)}", body_style))
        story.append(Paragraph(f"平均相关度：{data.get('avg_relevance', 0)}", body_style))
        story.append(Spacer(1, 15))

        # 优势分析
        story.append(Paragraph("课程总结", heading_style))
        story.append(Paragraph(data.get('course_summary', '暂无总结'), body_style))
        story.append(Spacer(1, 15))

        # 优劣势分析
        story.append(Paragraph("优劣势分析", heading_style))
        strengths = data.get('strengths', [])
        if strengths:
            story.append(Paragraph("优势：" + "；".join(strengths), body_style))
        weaknesses = data.get('weaknesses', [])
        if weaknesses:
            story.append(Paragraph("待改进：" + "；".join(weaknesses), body_style))
        story.append(Spacer(1, 15))

        # 改进建议
        story.append(Paragraph("改进建议", heading_style))
        story.append(Paragraph(data.get('improvement_suggestions', '继续保持'), body_style))

        doc.build(story)

        return {
            "status": "success",
            "pdf_url": f"/storage/reports/{pdf_filename}",
            "filename": pdf_filename
        }
    except ImportError:
        return {"status": "error", "message": "缺少reportlab库: pip install reportlab"}
    except Exception as e:
        print(f"[ERROR] PDF生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
