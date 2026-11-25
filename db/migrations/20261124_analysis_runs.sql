/*
分析运行观测记录。可重复执行。
*/

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.analysis_runs', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[analysis_runs] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [meeting_id] INT NOT NULL,
        [kind] NVARCHAR(30) NOT NULL,
        [source] NVARCHAR(30) NOT NULL,
        [model] NVARCHAR(50) NULL,
        [version] NVARCHAR(30) NULL,
        [status] NVARCHAR(30) NOT NULL,
        [latency_ms] INT NULL,
        [prompt_tokens] INT NULL,
        [completion_tokens] INT NULL,
        [cost] FLOAT NULL,
        [result] NVARCHAR(MAX) NULL,
        [error] NVARCHAR(2000) NULL,
        [created_at] DATETIME2 NOT NULL,
        CONSTRAINT [FK_analysis_runs_meeting]
            FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id])
    );
    CREATE INDEX [idx_analysis_runs_meeting_created]
        ON [dbo].[analysis_runs] ([meeting_id], [created_at]);
END;

COMMIT TRANSACTION;
