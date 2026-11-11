/*
服务端登录会话与课堂占用锁。可重复执行。

- 同一账号只保留一个有效会话（由应用层在登录时撤销旧会话）。
- 同一 device_id 只保留一个账号会话（应用层撤销）。
- 同一 user_id / device_id 对同一 meeting_id 只能有一行占用；
  唯一约束负责并发兜底。
*/

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.user_sessions', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[user_sessions] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [token_hash] NVARCHAR(64) NOT NULL,
        [user_id] INT NOT NULL,
        [device_id] NVARCHAR(128) NOT NULL,
        [user_agent] NVARCHAR(512) NULL,
        [created_at] DATETIME2 NOT NULL,
        [last_seen_at] DATETIME2 NOT NULL,
        [expires_at] DATETIME2 NOT NULL,
        [revoked_at] DATETIME2 NULL,
        CONSTRAINT [UQ_user_sessions_token_hash] UNIQUE ([token_hash]),
        CONSTRAINT [FK_user_sessions_users] FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id])
    );
    CREATE INDEX [IX_user_sessions_user_active]
        ON [dbo].[user_sessions] ([user_id], [revoked_at]);
    CREATE INDEX [IX_user_sessions_device_active]
        ON [dbo].[user_sessions] ([device_id], [revoked_at]);
END;

IF OBJECT_ID(N'dbo.active_classroom_sessions', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[active_classroom_sessions] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id] INT NOT NULL,
        [user_id] INT NOT NULL,
        [device_id] NVARCHAR(128) NOT NULL,
        [meeting_id] INT NOT NULL,
        [claimed_at] DATETIME2 NOT NULL,
        CONSTRAINT [UQ_active_classroom_user_meeting] UNIQUE ([user_id], [meeting_id]),
        CONSTRAINT [UQ_active_classroom_device_meeting] UNIQUE ([device_id], [meeting_id]),
        CONSTRAINT [FK_active_classroom_session]
            FOREIGN KEY ([session_id]) REFERENCES [dbo].[user_sessions] ([id]),
        CONSTRAINT [FK_active_classroom_user]
            FOREIGN KEY ([user_id]) REFERENCES [dbo].[users] ([id]),
        CONSTRAINT [FK_active_classroom_meeting]
            FOREIGN KEY ([meeting_id]) REFERENCES [dbo].[meetings] ([id])
    );
    CREATE INDEX [IX_active_classroom_meeting]
        ON [dbo].[active_classroom_sessions] ([meeting_id]);
END;

COMMIT TRANSACTION;
