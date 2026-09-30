# 数据库配置全面审计报告

## 审计日期: 2026-03-14

## 一、数据库模型定义 (database.py)

### 已定义的15个数据表:

1. **users** - 用户表
   - 字段: id, student_id, username, password, role, face_encoding, created_at
   - 索引: student_id (unique)

2. **meetings** - 会议/课堂表
   - 字段: id, class_code, teacher_id, topic, reference_materials, teaching_design, knowledge_points, template_path, status, created_at, ended_at
   - 索引: class_code (unique)
   - 外键: teacher_id -> users.id

3. **transcripts** - 发言记录表
   - 字段: id, meeting_id, user_id, content, audio_file_path, relevance_score, quality_score, quality_feedback, emotion_tag, body_action, audio_tone, timestamp, created_at
   - 索引: (meeting_id, user_id) 复合索引
   - 外键: meeting_id -> meetings.id, user_id -> users.id

4. **emotion_logs** - 情绪日志表
   - 字段: id, meeting_id, user_id, emotion_type, intensity, snapshot_path, video_url, video_start_time, created_at
   - 索引: (meeting_id, user_id) 复合索引
   - 外键: meeting_id -> meetings.id, user_id -> users.id

5. **ai_insights** - AI洞察表
   - 字段: id, meeting_id, target_user, content, type, created_at
   - 外键: meeting_id -> meetings.id

6. **knowledge_graphs** - 知识图谱表
   - 字段: id, meeting_id, graph_data, created_at, updated_at
   - 索引: meeting_id
   - 外键: meeting_id -> meetings.id

7. **graph_nodes** - 图谱节点表
   - 字段: id, graph_id, concept_label, concept_type, frequency, speakers, meta_info
   - 索引: graph_id
   - 外键: graph_id -> knowledge_graphs.id

8. **graph_edges** - 图谱边表
   - 字段: id, graph_id, source_node_id, target_node_id, relation_type, weight, evidence
   - 索引: graph_id
   - 外键: graph_id -> knowledge_graphs.id, source_node_id/target_node_id -> graph_nodes.id

9. **learning_reports** - 学习报告表
   - 字段: id, meeting_id, user_id, report_data, created_at
   - 索引: meeting_id, user_id
   - 外键: meeting_id -> meetings.id, user_id -> users.id

10. **exercises** - 练习题表
    - 字段: id, report_id, question, question_type, options, answer, knowledge_tag, difficulty, estimated_time
    - 索引: report_id
    - 外键: report_id -> learning_reports.id

11. **student_answers** - 学生答案表
    - 字段: id, exercise_id, user_id, answer_content, is_correct, submitted_at
    - 索引: exercise_id, user_id
    - 外键: exercise_id -> exercises.id, user_id -> users.id

12. **mental_health_assessments** - 心理健康评估表
    - 字段: id, user_id, meeting_id, risk_level, assessment_data, intervention_time, created_at
    - 索引: user_id, meeting_id
    - 外键: user_id -> users.id, meeting_id -> meetings.id

13. **viewpoint_votes** - 观点投票表
    - 字段: id, meeting_id, vote_session_id, viewpoints, votes, status, winner_viewpoint_id, created_at, closed_at
    - 索引: meeting_id, vote_session_id
    - 外键: meeting_id -> meetings.id

14. **member_connections** - 成员连接状态表
    - 字段: id, meeting_id, user_id, username, is_online, video_enabled, audio_enabled, last_heartbeat, joined_at
    - 索引: meeting_id, user_id
    - 外键: meeting_id -> meetings.id, user_id -> users.id

15. **report_templates** - 报告模板表
    - 字段: id, teacher_id, filename, filepath, is_default, created_at
    - 索引: teacher_id
    - 外键: teacher_id -> users.id

---

## 二、API接口与数据库使用情况

### 已实现的29个API接口:

| 接口路径 | 方法 | 使用的数据表 | 状态 |
|---------|------|------------|------|
| /api/register | POST | User | ✅ 正常 |
| /api/login | POST | User | ✅ 正常 |
| /login | POST | User, Meeting | ✅ 正常 |
| /summary | GET | Transcript, EmotionLog, Meeting | ✅ 正常 |
| /api/knowledge-graph/{meeting_id} | GET | KnowledgeGraph | ✅ 正常 |
| /api/generate-report | POST | Meeting, User, Transcript, EmotionLog, LearningReport, Exercise | ✅ 正常 |
| /api/reports/{user_id} | GET | LearningReport | ✅ 正常 |
| /api/meeting-reports/{meeting_id} | GET | LearningReport, User | ✅ 正常 |
| /ws/{username}/{meeting_id} | WebSocket | User, Meeting, Transcript, EmotionLog, AIInsight | ✅ 正常 |
| /api/ai-tutor | POST | 无 (仅LLM调用) | ✅ 正常 |
| /api/cluster-viewpoints | POST | Meeting, Transcript, ViewpointVote | ✅ 正常 |
| /api/cast-vote | POST | ViewpointVote | ✅ 正常 |
| /api/close-vote | POST | ViewpointVote, Meeting | ✅ 正常 |
| /api/select-viewpoint | POST | Meeting | ✅ 正常 |
| /api/class-history/{user_id} | GET | Meeting, Transcript | ✅ 正常 |
| /api/active-groups/{teacher_id} | GET | Meeting, Transcript | ✅ 正常 |
| /api/realtime-stats/{meeting_id} | GET | Transcript, EmotionLog | ✅ 正常 |
| /api/emotion-details/{meeting_id} | GET | EmotionLog, Transcript | ✅ 正常 |
| /api/snapshot/{meeting_id} | GET | User, EmotionLog | ✅ 正常 |
| /api/get-video-context | GET | EmotionLog | ✅ 正常 |
| /api/generate-pdf-report | POST | LearningReport, Meeting, User | ✅ 正常 |
| /api/download-exercises/{report_id} | GET | Exercise, LearningReport, Meeting | ✅ 正常 |
| /api/upload-report-template | POST | ReportTemplate | ✅ 正常 |
| /api/teacher-templates/{teacher_id} | GET | ReportTemplate | ✅ 正常 |
| /api/delete-template/{template_id} | DELETE | ReportTemplate | ✅ 正常 |
| /api/teacher-stats/{teacher_id} | GET | Meeting, Transcript | ✅ 正常 |
| /api/teacher-classes/{teacher_id} | GET | Meeting, Transcript | ✅ 正常 |
| /api/class-groups/{meeting_id} | GET | Meeting, Transcript | ✅ 正常 |
| /api/all-student-reports/{teacher_id} | GET | Meeting, LearningReport, User | ✅ 正常 |

---

## 三、发现的问题

### 🔴 严重问题

#### 1. 未使用的数据表 (5个)
以下数据表已定义但在任何API接口中都未使用:

- **graph_nodes** - 图谱节点表 (未使用)
- **graph_edges** - 图谱边表 (未使用)
- **student_answers** - 学生答案表 (未使用)
- **mental_health_assessments** - 心理健康评估表 (未使用)
- **member_connections** - 成员连接状态表 (未使用)

**影响**: 数据库中存在冗余表结构，占用资源但无实际功能

**建议**:
- 如果这些功能计划实现，需要添加对应的API接口
- 如果不需要，应从database.py中删除这些模型定义

#### 2. 导入不一致问题
在server.py中，ReportTemplate模型在某些函数中是局部导入:

```python
# Line 2127, 2173, 2199
from database import ReportTemplate
```

**问题**: 应该在文件顶部统一导入，而不是在函数内部重复导入

**位置**: server.py:24 (顶部导入区域)

### 🟡 中等问题

#### 3. 字段长度限制不一致
