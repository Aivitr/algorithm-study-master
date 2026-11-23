/*
Hint 发送记录。可重复执行。

- dedupe_key 不设唯一约束：同一候选在冷却结束后可以再次发送。
- evidence / evidence_ids 存 JSON 文本，便于回查触发依据。
*/

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.hint_logs', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[hint_logs] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [meeting_id] INT NOT NULL,
        [dedupe_key] NVARCHAR(200) NOT NULL,
        [hint_type] NVARCHAR(30) NOT NULL,
        [target_type] NVARCHAR(20) NOT NULL,
        [target_user_id] NVARCHAR(50) NULL,
        [trigger_reason] NVARCHAR(2000) NULL,
        [evidence] NVARCHAR(MAX) NULL,
        [evidence_ids] NVARCHAR(MAX) NULL,
        [text] NVARCHAR(2000) NULL,
        [model] NVARCHAR(50) NULL,
        [prompt_version] NVARCHAR(30) NULL,
        [status] NVARCHAR(20) NOT NULL,
        [created_by] INT NULL,
        [sent_at] DATETIME2 NULL,
        [response] NVARCHAR(2000) NULL,
        [created_at] DATETIME2 NOT NULL,
        CONSTRAINT [FK_hint_logs_meeting]
            FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]),
        CONSTRAINT [FK_hint_logs_created_by]
            FOREIGN KEY ([created_by]) REFERENCES [dbo].[users] ([id])
    );
    CREATE INDEX [idx_hint_logs_meeting_created]
        ON [dbo].[hint_logs] ([meeting_id], [created_at]);
END;

COMMIT TRANSACTION;
