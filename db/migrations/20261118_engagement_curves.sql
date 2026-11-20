/*
三维学习投入曲线（P4 最小闭环）。可重复执行。

- 一行 = 一个课堂窗口、一个维度、一个学生或小组。
- user_id 为空表示小组级曲线。
- metrics 保存该维度在该窗口的指标；本期不写综合分。
*/

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.engagement_curves', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[engagement_curves] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [meeting_id] INT NOT NULL,
        [user_id] INT NULL,
        [dimension] NVARCHAR(20) NOT NULL,
        [window_start_second] FLOAT NOT NULL,
        [window_end_second] FLOAT NOT NULL,
        [metrics] NVARCHAR(MAX) NOT NULL,
        [status] NVARCHAR(20) NOT NULL,
        [protocol_version] NVARCHAR(20) NOT NULL,
        [created_at] DATETIME2 NOT NULL,
        CONSTRAINT [FK_engagement_curves_meeting]
            FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id]),
        CONSTRAINT [FK_engagement_curves_user]
            FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id])
    );
    CREATE INDEX [idx_engagement_meeting_window]
        ON [dbo].[engagement_curves] ([meeting_id], [dimension], [window_start_second]);
    CREATE INDEX [idx_engagement_meeting_user]
        ON [dbo].[engagement_curves] ([meeting_id], [user_id]);
END;

COMMIT TRANSACTION;
