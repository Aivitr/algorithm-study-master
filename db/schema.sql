-- ============================================================================
-- 建库脚本（生产开发通用）—— 由 tools/export_prod_schema.py 自动生成，请勿手改。
--
-- 来源：cscl_db（**只读**导出）；源主机名不入库（见 .env.prod）。
-- 排序规则：Chinese_PRC_CI_AS
-- 用途：对新库执行即建库；对已有库执行是无操作（每条语句都幂等）。
--
--   docker compose up          开发侧：db-init 服务自动执行本文件
--   sqlcmd -S <host> -d cscl_db -i db/schema.sql    生产侧：手动执行
--
-- ⚠️ 这是生产结构的**冻结快照**。模型改了它不会自己跟，重新生成：
--       python tools/export_prod_schema.py --yes
--    然后人工过目 diff 再提交。
-- ============================================================================

SET NOCOUNT ON;
GO

-- 开发侧空库需要它；生产侧已存在，是 no-op（未走到的分支也不会被做权限检查）。
-- COLLATE 必须带上：本机容器的服务器默认排序规则是 SQL_Latin1_General_CP1_CI_AS，
-- 而本库是 Chinese_PRC_CI_AS，两者对中文字符串的比较/排序语义不同。
IF DB_ID(N'cscl_db') IS NULL
    CREATE DATABASE [cscl_db] COLLATE Chinese_PRC_CI_AS;
GO

-- 显式切库：这样从 master 连进去直接 -i 本文件也能跑通，
-- 不必要求调用方先自己 CREATE DATABASE 再用 -d 指过来。
USE [cscl_db];
GO

IF OBJECT_ID(N'dbo.[ai_insights]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[ai_insights] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [target_user] varchar(50) NULL,
    [content] varchar(max) NULL,
    [type] varchar(20) NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__ai_insig__3213E83F7BA144F2] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[collaboration_intervention_logs]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[collaboration_intervention_logs] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [target_user] varchar(50) NULL,
    [intervention_type] varchar(80) NOT NULL,
    [target] varchar(30) NULL,
    [trigger_level] varchar(50) NULL,
    [trigger_score] float NULL,
    [trigger_metrics] nvarchar(max) NULL,
    [suggestion] nvarchar(2000) NULL,
    [teacher_suggestion] nvarchar(2000) NULL,
    [evidence] nvarchar(max) NULL,
    [handled_status] varchar(30) NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__collabor__3213E83F0E6506C7] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[emotion_logs]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[emotion_logs] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [user_id] int NULL,
    [emotion_type] varchar(100) NULL,
    [intensity] float NULL,
    [snapshot_path] varchar(500) NULL,
    [video_url] varchar(500) NULL,
    [video_start_time] float NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__emotion___3213E83F02938CFB] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[evaluation_logs]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[evaluation_logs] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [transcript_id] int NULL,
    [user_id] int NULL,
    [overall_score] int NULL,
    [dimensions] nvarchar(max) NULL,
    [evidence] nvarchar(max) NULL,
    [confidence] float NULL,
    [evaluation_version] varchar(50) NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__evaluati__3213E83FB9713AE3] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[exercises]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[exercises] (
    [id] int IDENTITY(1,1) NOT NULL,
    [report_id] int NULL,
    [question] nvarchar(4000) NOT NULL,
    [question_type] nvarchar(50) NULL,
    [options] nvarchar(max) NULL,
    [answer] nvarchar(2000) NULL,
    [knowledge_tag] nvarchar(200) NULL,
    [difficulty] float NULL,
    [estimated_time] int NULL,
    CONSTRAINT [PK__exercise__3213E83F8F916F58] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[graph_edges]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[graph_edges] (
    [id] int IDENTITY(1,1) NOT NULL,
    [graph_id] int NULL,
    [source_node_id] int NULL,
    [target_node_id] int NULL,
    [relation_type] varchar(50) NULL,
    [weight] float NULL,
    [evidence] varchar(max) NULL,
    CONSTRAINT [PK__graph_ed__3213E83F4836499D] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[graph_nodes]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[graph_nodes] (
    [id] int IDENTITY(1,1) NOT NULL,
    [graph_id] int NULL,
    [concept_label] varchar(200) NOT NULL,
    [concept_type] varchar(50) NULL,
    [frequency] int NULL,
    [speakers] nvarchar(max) NULL,
    [meta_info] nvarchar(max) NULL,
    CONSTRAINT [PK__graph_no__3213E83F50192658] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[knowledge_graphs]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[knowledge_graphs] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [graph_data] nvarchar(max) NOT NULL,
    [created_at] datetime NULL,
    [updated_at] datetime NULL,
    CONSTRAINT [PK__knowledg__3213E83F5DA842F1] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[learning_reports]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[learning_reports] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [user_id] int NULL,
    [report_data] nvarchar(max) NOT NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__learning__3213E83FFEDF7D56] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[meetings]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[meetings] (
    [id] int IDENTITY(1,1) NOT NULL,
    [class_code] varchar(50) NULL,
    [teacher_id] int NULL,
    [topic] nvarchar(255) NULL,
    [reference_materials] nvarchar(max) NULL,
    [teaching_design] nvarchar(max) NULL,
    [knowledge_points] nvarchar(max) NULL,
    [template_path] varchar(500) NULL,
    [status] varchar(20) NULL,
    [created_at] datetime NULL,
    [ended_at] datetime NULL,
    CONSTRAINT [PK__meetings__3213E83FC1A105C7] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[member_connections]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[member_connections] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [user_id] int NULL,
    [username] varchar(50) NULL,
    [is_online] int NULL,
    [video_enabled] int NULL,
    [audio_enabled] int NULL,
    [last_heartbeat] datetime NULL,
    [joined_at] datetime NULL,
    CONSTRAINT [PK__member_c__3213E83FA7027660] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[mental_health_assessments]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[mental_health_assessments] (
    [id] int IDENTITY(1,1) NOT NULL,
    [user_id] int NULL,
    [meeting_id] int NULL,
    [risk_level] varchar(20) NULL,
    [assessment_data] nvarchar(max) NULL,
    [intervention_time] datetime NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__mental_h__3213E83FE94A399F] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[rag_chunks]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[rag_chunks] (
    [id] int IDENTITY(1,1) NOT NULL,
    [source_type] varchar(80) NULL,
    [source_name] varchar(300) NULL,
    [chunk_text] nvarchar(4000) NOT NULL,
    [embedding] nvarchar(max) NULL,
    [meta_info] nvarchar(max) NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__rag_chun__3213E83FB684C24D] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[report_templates]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[report_templates] (
    [id] int IDENTITY(1,1) NOT NULL,
    [teacher_id] int NULL,
    [filename] varchar(200) NOT NULL,
    [filepath] varchar(500) NOT NULL,
    [is_default] int NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__report_t__3213E83F0500891F] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[student_answers]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[student_answers] (
    [id] int IDENTITY(1,1) NOT NULL,
    [exercise_id] int NULL,
    [user_id] int NULL,
    [answer_content] varchar(max) NULL,
    [is_correct] int NULL,
    [submitted_at] datetime NULL,
    CONSTRAINT [PK__student___3213E83FE5A08F6C] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[transcripts]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[transcripts] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [user_id] int NULL,
    [content] nvarchar(4000) NULL,
    [audio_file_path] varchar(500) NULL,
    [relevance_score] int NULL,
    [quality_score] int NULL,
    [quality_feedback] nvarchar(1000) NULL,
    [emotion_tag] nvarchar(100) NULL,
    [body_action] nvarchar(100) NULL,
    [audio_tone] nvarchar(100) NULL,
    [timestamp] datetime NULL,
    [created_at] datetime NULL,
    [ptt_mode] int NULL,
    [corrected_by] int NULL,
    [correction_time] datetime NULL,
    [binding_source] nvarchar(100) NULL,
    [binding_confidence] float NULL,
    [identity_review_status] nvarchar(50) NULL,
    [identity_review_note] nvarchar(1000) NULL,
    [cross_modal_consistency] float NULL,
    [quality_dimensions] nvarchar(max) NULL,
    [evaluation_evidence] nvarchar(max) NULL,
    [evaluation_version] nvarchar(50) NULL,
    CONSTRAINT [PK__transcri__3213E83FE53AD82D] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[users]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[users] (
    [id] int IDENTITY(1,1) NOT NULL,
    [student_id] nvarchar(50) NOT NULL,
    [username] nvarchar(50) NOT NULL,
    [password] nvarchar(256) NOT NULL,
    [role] nvarchar(20) NOT NULL,
    [face_encoding] nvarchar(max) NULL,
    [created_at] datetime NULL,
    CONSTRAINT [PK__users__3213E83FD937422B] PRIMARY KEY ([id])
);
END;
GO
IF OBJECT_ID(N'dbo.[viewpoint_votes]', N'U') IS NULL
BEGIN
CREATE TABLE [dbo].[viewpoint_votes] (
    [id] int IDENTITY(1,1) NOT NULL,
    [meeting_id] int NULL,
    [vote_session_id] varchar(50) NULL,
    [viewpoints] nvarchar(max) NOT NULL,
    [votes] nvarchar(max) NULL,
    [status] varchar(20) NULL,
    [winner_viewpoint_id] int NULL,
    [created_at] datetime NULL,
    [closed_at] datetime NULL,
    CONSTRAINT [PK__viewpoin__3213E83F475F2691] PRIMARY KEY ([id])
);
END;
GO
-- ---------------------------------------------------------------- 索引
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_meeting_insights' AND object_id = OBJECT_ID(N'dbo.[ai_insights]'))
CREATE NONCLUSTERED INDEX [idx_meeting_insights] ON [dbo].[ai_insights] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_ai_insights_id' AND object_id = OBJECT_ID(N'dbo.[ai_insights]'))
CREATE NONCLUSTERED INDEX [ix_ai_insights_id] ON [dbo].[ai_insights] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_intervention_meeting_type' AND object_id = OBJECT_ID(N'dbo.[collaboration_intervention_logs]'))
CREATE NONCLUSTERED INDEX [idx_intervention_meeting_type] ON [dbo].[collaboration_intervention_logs] ([meeting_id], [intervention_type]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_collaboration_intervention_logs_id' AND object_id = OBJECT_ID(N'dbo.[collaboration_intervention_logs]'))
CREATE NONCLUSTERED INDEX [ix_collaboration_intervention_logs_id] ON [dbo].[collaboration_intervention_logs] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_collaboration_intervention_logs_meeting_id' AND object_id = OBJECT_ID(N'dbo.[collaboration_intervention_logs]'))
CREATE NONCLUSTERED INDEX [ix_collaboration_intervention_logs_meeting_id] ON [dbo].[collaboration_intervention_logs] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_emotion_meeting_user' AND object_id = OBJECT_ID(N'dbo.[emotion_logs]'))
CREATE NONCLUSTERED INDEX [idx_emotion_meeting_user] ON [dbo].[emotion_logs] ([meeting_id], [user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_meeting_emotion' AND object_id = OBJECT_ID(N'dbo.[emotion_logs]'))
CREATE NONCLUSTERED INDEX [idx_meeting_emotion] ON [dbo].[emotion_logs] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_user_emotion' AND object_id = OBJECT_ID(N'dbo.[emotion_logs]'))
CREATE NONCLUSTERED INDEX [idx_user_emotion] ON [dbo].[emotion_logs] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_emotion_logs_id' AND object_id = OBJECT_ID(N'dbo.[emotion_logs]'))
CREATE NONCLUSTERED INDEX [ix_emotion_logs_id] ON [dbo].[emotion_logs] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_evaluation_meeting_user' AND object_id = OBJECT_ID(N'dbo.[evaluation_logs]'))
CREATE NONCLUSTERED INDEX [idx_evaluation_meeting_user] ON [dbo].[evaluation_logs] ([meeting_id], [user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_evaluation_logs_id' AND object_id = OBJECT_ID(N'dbo.[evaluation_logs]'))
CREATE NONCLUSTERED INDEX [ix_evaluation_logs_id] ON [dbo].[evaluation_logs] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_evaluation_logs_meeting_id' AND object_id = OBJECT_ID(N'dbo.[evaluation_logs]'))
CREATE NONCLUSTERED INDEX [ix_evaluation_logs_meeting_id] ON [dbo].[evaluation_logs] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_evaluation_logs_transcript_id' AND object_id = OBJECT_ID(N'dbo.[evaluation_logs]'))
CREATE NONCLUSTERED INDEX [ix_evaluation_logs_transcript_id] ON [dbo].[evaluation_logs] ([transcript_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_evaluation_logs_user_id' AND object_id = OBJECT_ID(N'dbo.[evaluation_logs]'))
CREATE NONCLUSTERED INDEX [ix_evaluation_logs_user_id] ON [dbo].[evaluation_logs] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_exercise_report' AND object_id = OBJECT_ID(N'dbo.[exercises]'))
CREATE NONCLUSTERED INDEX [idx_exercise_report] ON [dbo].[exercises] ([report_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_exercises_id' AND object_id = OBJECT_ID(N'dbo.[exercises]'))
CREATE NONCLUSTERED INDEX [ix_exercises_id] ON [dbo].[exercises] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_exercises_report_id' AND object_id = OBJECT_ID(N'dbo.[exercises]'))
CREATE NONCLUSTERED INDEX [ix_exercises_report_id] ON [dbo].[exercises] ([report_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_graph_edges_graph_id' AND object_id = OBJECT_ID(N'dbo.[graph_edges]'))
CREATE NONCLUSTERED INDEX [ix_graph_edges_graph_id] ON [dbo].[graph_edges] ([graph_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_graph_edges_id' AND object_id = OBJECT_ID(N'dbo.[graph_edges]'))
CREATE NONCLUSTERED INDEX [ix_graph_edges_id] ON [dbo].[graph_edges] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_graph_nodes_graph_id' AND object_id = OBJECT_ID(N'dbo.[graph_nodes]'))
CREATE NONCLUSTERED INDEX [ix_graph_nodes_graph_id] ON [dbo].[graph_nodes] ([graph_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_graph_nodes_id' AND object_id = OBJECT_ID(N'dbo.[graph_nodes]'))
CREATE NONCLUSTERED INDEX [ix_graph_nodes_id] ON [dbo].[graph_nodes] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_knowledge_graphs_id' AND object_id = OBJECT_ID(N'dbo.[knowledge_graphs]'))
CREATE NONCLUSTERED INDEX [ix_knowledge_graphs_id] ON [dbo].[knowledge_graphs] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_knowledge_graphs_meeting_id' AND object_id = OBJECT_ID(N'dbo.[knowledge_graphs]'))
CREATE NONCLUSTERED INDEX [ix_knowledge_graphs_meeting_id] ON [dbo].[knowledge_graphs] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_learning_reports_id' AND object_id = OBJECT_ID(N'dbo.[learning_reports]'))
CREATE NONCLUSTERED INDEX [ix_learning_reports_id] ON [dbo].[learning_reports] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_learning_reports_meeting_id' AND object_id = OBJECT_ID(N'dbo.[learning_reports]'))
CREATE NONCLUSTERED INDEX [ix_learning_reports_meeting_id] ON [dbo].[learning_reports] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_learning_reports_user_id' AND object_id = OBJECT_ID(N'dbo.[learning_reports]'))
CREATE NONCLUSTERED INDEX [ix_learning_reports_user_id] ON [dbo].[learning_reports] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_class_code' AND object_id = OBJECT_ID(N'dbo.[meetings]'))
CREATE NONCLUSTERED INDEX [idx_class_code] ON [dbo].[meetings] ([class_code]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_meetings_class_code' AND object_id = OBJECT_ID(N'dbo.[meetings]'))
CREATE UNIQUE NONCLUSTERED INDEX [ix_meetings_class_code] ON [dbo].[meetings] ([class_code]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_meetings_id' AND object_id = OBJECT_ID(N'dbo.[meetings]'))
CREATE NONCLUSTERED INDEX [ix_meetings_id] ON [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_member_connections_id' AND object_id = OBJECT_ID(N'dbo.[member_connections]'))
CREATE NONCLUSTERED INDEX [ix_member_connections_id] ON [dbo].[member_connections] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_member_connections_meeting_id' AND object_id = OBJECT_ID(N'dbo.[member_connections]'))
CREATE NONCLUSTERED INDEX [ix_member_connections_meeting_id] ON [dbo].[member_connections] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_member_connections_user_id' AND object_id = OBJECT_ID(N'dbo.[member_connections]'))
CREATE NONCLUSTERED INDEX [ix_member_connections_user_id] ON [dbo].[member_connections] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_mental_health_assessments_id' AND object_id = OBJECT_ID(N'dbo.[mental_health_assessments]'))
CREATE NONCLUSTERED INDEX [ix_mental_health_assessments_id] ON [dbo].[mental_health_assessments] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_mental_health_assessments_meeting_id' AND object_id = OBJECT_ID(N'dbo.[mental_health_assessments]'))
CREATE NONCLUSTERED INDEX [ix_mental_health_assessments_meeting_id] ON [dbo].[mental_health_assessments] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_mental_health_assessments_user_id' AND object_id = OBJECT_ID(N'dbo.[mental_health_assessments]'))
CREATE NONCLUSTERED INDEX [ix_mental_health_assessments_user_id] ON [dbo].[mental_health_assessments] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_rag_chunks_id' AND object_id = OBJECT_ID(N'dbo.[rag_chunks]'))
CREATE NONCLUSTERED INDEX [ix_rag_chunks_id] ON [dbo].[rag_chunks] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_rag_chunks_source_type' AND object_id = OBJECT_ID(N'dbo.[rag_chunks]'))
CREATE NONCLUSTERED INDEX [ix_rag_chunks_source_type] ON [dbo].[rag_chunks] ([source_type]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_report_templates_id' AND object_id = OBJECT_ID(N'dbo.[report_templates]'))
CREATE NONCLUSTERED INDEX [ix_report_templates_id] ON [dbo].[report_templates] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_report_templates_teacher_id' AND object_id = OBJECT_ID(N'dbo.[report_templates]'))
CREATE NONCLUSTERED INDEX [ix_report_templates_teacher_id] ON [dbo].[report_templates] ([teacher_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_student_answers_exercise_id' AND object_id = OBJECT_ID(N'dbo.[student_answers]'))
CREATE NONCLUSTERED INDEX [ix_student_answers_exercise_id] ON [dbo].[student_answers] ([exercise_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_student_answers_id' AND object_id = OBJECT_ID(N'dbo.[student_answers]'))
CREATE NONCLUSTERED INDEX [ix_student_answers_id] ON [dbo].[student_answers] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_student_answers_user_id' AND object_id = OBJECT_ID(N'dbo.[student_answers]'))
CREATE NONCLUSTERED INDEX [ix_student_answers_user_id] ON [dbo].[student_answers] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_meeting' AND object_id = OBJECT_ID(N'dbo.[transcripts]'))
CREATE NONCLUSTERED INDEX [idx_meeting] ON [dbo].[transcripts] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_transcript_meeting_user' AND object_id = OBJECT_ID(N'dbo.[transcripts]'))
CREATE NONCLUSTERED INDEX [idx_transcript_meeting_user] ON [dbo].[transcripts] ([meeting_id], [user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_user' AND object_id = OBJECT_ID(N'dbo.[transcripts]'))
CREATE NONCLUSTERED INDEX [idx_user] ON [dbo].[transcripts] ([user_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_transcripts_id' AND object_id = OBJECT_ID(N'dbo.[transcripts]'))
CREATE NONCLUSTERED INDEX [ix_transcripts_id] ON [dbo].[transcripts] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_users_student_id' AND object_id = OBJECT_ID(N'dbo.[users]'))
CREATE UNIQUE NONCLUSTERED INDEX [ix_users_student_id] ON [dbo].[users] ([student_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_viewpoint_votes_id' AND object_id = OBJECT_ID(N'dbo.[viewpoint_votes]'))
CREATE NONCLUSTERED INDEX [ix_viewpoint_votes_id] ON [dbo].[viewpoint_votes] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_viewpoint_votes_meeting_id' AND object_id = OBJECT_ID(N'dbo.[viewpoint_votes]'))
CREATE NONCLUSTERED INDEX [ix_viewpoint_votes_meeting_id] ON [dbo].[viewpoint_votes] ([meeting_id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_viewpoint_votes_vote_session_id' AND object_id = OBJECT_ID(N'dbo.[viewpoint_votes]'))
CREATE NONCLUSTERED INDEX [ix_viewpoint_votes_vote_session_id] ON [dbo].[viewpoint_votes] ([vote_session_id]);
GO
-- ------------------------------------------------------------ 外键约束
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__ai_insigh__meeti__33D4B598')
ALTER TABLE [dbo].[ai_insights] WITH CHECK ADD CONSTRAINT [FK__ai_insigh__meeti__33D4B598] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__collabora__meeti__5AEE82B9')
ALTER TABLE [dbo].[collaboration_intervention_logs] WITH CHECK ADD CONSTRAINT [FK__collabora__meeti__5AEE82B9] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__emotion_l__meeti__300424B4')
ALTER TABLE [dbo].[emotion_logs] WITH CHECK ADD CONSTRAINT [FK__emotion_l__meeti__300424B4] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__emotion_l__user___30F848ED')
ALTER TABLE [dbo].[emotion_logs] WITH CHECK ADD CONSTRAINT [FK__emotion_l__user___30F848ED] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__evaluatio__meeti__5629CD9C')
ALTER TABLE [dbo].[evaluation_logs] WITH CHECK ADD CONSTRAINT [FK__evaluatio__meeti__5629CD9C] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__evaluatio__trans__571DF1D5')
ALTER TABLE [dbo].[evaluation_logs] WITH CHECK ADD CONSTRAINT [FK__evaluatio__trans__571DF1D5] FOREIGN KEY ([transcript_id]) REFERENCES [dbo].[transcripts] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__evaluatio__user___5812160E')
ALTER TABLE [dbo].[evaluation_logs] WITH CHECK ADD CONSTRAINT [FK__evaluatio__user___5812160E] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__exercises__repor__4AB81AF0')
ALTER TABLE [dbo].[exercises] WITH CHECK ADD CONSTRAINT [FK__exercises__repor__4AB81AF0] FOREIGN KEY ([report_id]) REFERENCES [dbo].[learning_reports] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__graph_edg__graph__4D94879B')
ALTER TABLE [dbo].[graph_edges] WITH CHECK ADD CONSTRAINT [FK__graph_edg__graph__4D94879B] FOREIGN KEY ([graph_id]) REFERENCES [dbo].[knowledge_graphs] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__graph_edg__sourc__4E88ABD4')
ALTER TABLE [dbo].[graph_edges] WITH CHECK ADD CONSTRAINT [FK__graph_edg__sourc__4E88ABD4] FOREIGN KEY ([source_node_id]) REFERENCES [dbo].[graph_nodes] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__graph_edg__targe__4F7CD00D')
ALTER TABLE [dbo].[graph_edges] WITH CHECK ADD CONSTRAINT [FK__graph_edg__targe__4F7CD00D] FOREIGN KEY ([target_node_id]) REFERENCES [dbo].[graph_nodes] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__graph_nod__graph__47DBAE45')
ALTER TABLE [dbo].[graph_nodes] WITH CHECK ADD CONSTRAINT [FK__graph_nod__graph__47DBAE45] FOREIGN KEY ([graph_id]) REFERENCES [dbo].[knowledge_graphs] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__knowledge__meeti__36B12243')
ALTER TABLE [dbo].[knowledge_graphs] WITH CHECK ADD CONSTRAINT [FK__knowledge__meeti__36B12243] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__learning___meeti__398D8EEE')
ALTER TABLE [dbo].[learning_reports] WITH CHECK ADD CONSTRAINT [FK__learning___meeti__398D8EEE] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__learning___user___3A81B327')
ALTER TABLE [dbo].[learning_reports] WITH CHECK ADD CONSTRAINT [FK__learning___user___3A81B327] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__meetings__teache__267ABA7A')
ALTER TABLE [dbo].[meetings] WITH CHECK ADD CONSTRAINT [FK__meetings__teache__267ABA7A] FOREIGN KEY ([teacher_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__member_co__meeti__440B1D61')
ALTER TABLE [dbo].[member_connections] WITH CHECK ADD CONSTRAINT [FK__member_co__meeti__440B1D61] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__member_co__user___44FF419A')
ALTER TABLE [dbo].[member_connections] WITH CHECK ADD CONSTRAINT [FK__member_co__user___44FF419A] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__mental_he__meeti__3E52440B')
ALTER TABLE [dbo].[mental_health_assessments] WITH CHECK ADD CONSTRAINT [FK__mental_he__meeti__3E52440B] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__mental_he__user___3D5E1FD2')
ALTER TABLE [dbo].[mental_health_assessments] WITH CHECK ADD CONSTRAINT [FK__mental_he__user___3D5E1FD2] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__report_te__teach__29572725')
ALTER TABLE [dbo].[report_templates] WITH CHECK ADD CONSTRAINT [FK__report_te__teach__29572725] FOREIGN KEY ([teacher_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__student_a__exerc__52593CB8')
ALTER TABLE [dbo].[student_answers] WITH CHECK ADD CONSTRAINT [FK__student_a__exerc__52593CB8] FOREIGN KEY ([exercise_id]) REFERENCES [dbo].[exercises] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__student_a__user___534D60F1')
ALTER TABLE [dbo].[student_answers] WITH CHECK ADD CONSTRAINT [FK__student_a__user___534D60F1] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__transcrip__meeti__2C3393D0')
ALTER TABLE [dbo].[transcripts] WITH CHECK ADD CONSTRAINT [FK__transcrip__meeti__2C3393D0] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__transcrip__user___2D27B809')
ALTER TABLE [dbo].[transcripts] WITH CHECK ADD CONSTRAINT [FK__transcrip__user___2D27B809] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]);
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK__viewpoint__meeti__412EB0B6')
ALTER TABLE [dbo].[viewpoint_votes] WITH CHECK ADD CONSTRAINT [FK__viewpoint__meeti__412EB0B6] FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]);
GO
