/*
存量 SQL Server 数据库迁移：课堂三阶段生命周期。

可重复执行。迁移规则：
  active / paused -> running
  ended           -> ended
  NULL            -> created

旧数据没有真实开始时间，已进入或结束的课堂使用 created_at 近似回填 started_at。
*/

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.meetings', N'started_at') IS NULL
BEGIN
    ALTER TABLE [dbo].[meetings] ADD [started_at] datetime NULL;
END;

UPDATE [dbo].[meetings]
SET [started_at] = COALESCE([started_at], [created_at])
WHERE [status] IN ('active', 'paused', 'ended') AND [started_at] IS NULL;

UPDATE [dbo].[meetings]
SET [status] = CASE
    WHEN [status] IN ('active', 'paused') THEN 'running'
    WHEN [status] IS NULL THEN 'created'
    ELSE [status]
END;

IF EXISTS (
    SELECT 1 FROM [dbo].[meetings]
    WHERE [status] NOT IN ('created', 'running', 'ended')
)
BEGIN
    ROLLBACK TRANSACTION;
    THROW 50001, 'meetings.status contains values outside created/running/ended', 1;
END;

-- 旧库已有 DEFAULT ('active') 时不能只判断“存在默认约束”，必须替换它。
DECLARE @meetings_status_default sysname;
SELECT @meetings_status_default = dc.name
FROM sys.default_constraints dc
INNER JOIN sys.columns c ON c.default_object_id = dc.object_id
WHERE dc.parent_object_id = OBJECT_ID(N'dbo.meetings')
  AND c.name = N'status'
  AND dc.definition NOT LIKE N'%created%';

IF @meetings_status_default IS NOT NULL
BEGIN
    DECLARE @drop_status_default_sql nvarchar(max);
    SET @drop_status_default_sql =
        N'ALTER TABLE [dbo].[meetings] DROP CONSTRAINT '
        + QUOTENAME(@meetings_status_default);
    EXEC sp_executesql @drop_status_default_sql;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.default_constraints dc
    INNER JOIN sys.columns c ON c.default_object_id = dc.object_id
    WHERE dc.parent_object_id = OBJECT_ID(N'dbo.meetings')
      AND c.name = N'status'
)
BEGIN
    ALTER TABLE [dbo].[meetings]
        ADD CONSTRAINT [DF_meetings_status] DEFAULT ('created') FOR [status];
END;

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.meetings')
      AND name = N'status'
      AND is_nullable = 1
)
BEGIN
    ALTER TABLE [dbo].[meetings] ALTER COLUMN [status] varchar(20) NOT NULL;
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.meetings')
      AND name = N'CK_meetings_status'
)
BEGIN
    ALTER TABLE [dbo].[meetings] WITH CHECK
        ADD CONSTRAINT [CK_meetings_status]
        CHECK ([status] IN ('created', 'running', 'ended'));
END;

COMMIT TRANSACTION;
