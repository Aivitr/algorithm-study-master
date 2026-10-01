# -*- coding: utf-8 -*-
"""把生产库的**表结构**导出成一份幂等的建库脚本（`db/schema.sql`）。

这份脚本产出 `db/schema.sql`，**生产开发通用**：对空库跑就是建库，对已有的库跑是
无操作（每张表/索引/外键都包在 `IF ... IS NULL` / `IF NOT EXISTS` 里）。

## 它为什么必须自己解析 .env

**绝不 `import app.*`。** `app/core/database.py` 在**导入期**就执行
`_ensure_transcripts_columns()`，会对 `DATABASE_URL` 指向的库发 `ALTER TABLE`——
**导入动作即 DDL**。本脚本只连库、只读目录视图，所以它自带一个极小的 `.env`
解析器，绕开整个应用。

## 它做的唯一一件事就是读

发出的每一条语句都必须以 `SELECT` 开头，由 `_only_select()` 在发送前强制校验；
出现任何 DDL/DML 立即抛异常中止。对远程目标还要求显式确认（`--yes` 或
`EXPORT_CONFIRM=1`），沿用 `archive/ops-scripts/_prod_guard.py` 的约定。

## 用法

    python tools/export_prod_schema.py --yes            # 从 .env.prod（无则 .env）导出
    python tools/export_prod_schema.py --env-file .env  # 指定配置文件
    python tools/export_prod_schema.py --out /tmp/x.sql # 指定输出

导完请人工过目 diff 再提交——它是生产的**冻结快照**，模型改了它不会自己跟。
"""

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "db" / "schema.sql"

# 与 tests_safe/conftest.py、archive/ops-scripts/_prod_guard.py 同一套回环判定，保持一致语义
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "", None}
_CONFIRM_ENV = "EXPORT_CONFIRM"

_DB_TARGET = "cscl_db"

# 带长度语义的字符/二进制类型：n 或 MAX
_LENGTH_TYPES = {"char", "varchar", "nchar", "nvarchar", "binary", "varbinary"}
# 带精度/小数位的数值类型
_PRECISION_TYPES = {"decimal", "numeric"}


# --------------------------------------------------------------------------
# .env 解析（极简，只为拿 DB_*；不 import 应用里的任何东西）
# --------------------------------------------------------------------------


def read_env_file(path: Path) -> dict:
    """只认 `KEY=VALUE` 单行，忽略注释与空行。不处理引号展开之外的花样。"""
    values = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def resolve_env_file(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            sys.exit(f"[中断] 指定的配置文件不存在：{path}")
        return path
    prod = REPO_ROOT / ".env.prod"
    if prod.is_file():
        return prod
    return REPO_ROOT / ".env"


def rel_to_repo(path: Path) -> str:
    """仓库外的路径（比如临时目录里的 .env）直接原样显示，别在这里炸。"""
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def redact(s: str) -> str:
    if "@" not in s or "://" not in s:
        return s
    scheme, _, rest = s.partition("://")
    creds, _, host = rest.rpartition("@")
    if ":" in creds:
        user, _, _ = creds.partition(":")
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{host}"


# --------------------------------------------------------------------------
# 只读护栏
# --------------------------------------------------------------------------


def _only_select(cursor, sql: str):
    """发送前强制校验：本脚本只许读。"""
    head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    if head not in {"SELECT", "WITH"}:
        raise RuntimeError(
            f"本脚本只允许只读查询，拒绝发送以 {head!r} 开头的语句：\n{sql[:300]}"
        )
    cursor.execute(sql)
    return cursor


def confirm_remote(host: str, db_name: str) -> None:
    line = "=" * 74
    print(line)
    print("[生产库结构导出] 即将执行：只读读取 INFORMATION_SCHEMA / sys 目录视图")
    print(f"    目标主机 = {host}")
    print(f"    目标库   = {db_name}")
    print("本操作**不写入、不建表、不改结构**：发出的每条语句都由 _only_select() 校验过，")
    print("出现任何 DDL/DML 会立刻抛异常中止。产出物是 db/schema.sql 的文本。")
    if host in _LOOPBACK:
        print("目标为本机——继续执行。")
        print(line)
        return
    if os.getenv(_CONFIRM_ENV) == "1" or "--yes" in sys.argv:
        print("已确认，继续执行。")
        print(line)
        return
    print()
    print("对**远程库**执行本操作需要显式确认。请二选一：")
    print("    python tools/export_prod_schema.py --yes")
    print(f"    或设置环境变量 {_CONFIRM_ENV}=1")
    print(line)
    sys.exit(2)


# --------------------------------------------------------------------------
# 目录视图查询
# --------------------------------------------------------------------------

_Q_TABLES = """
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_SCHEMA, TABLE_NAME
"""

# 库级排序规则必须一起搬。不带 COLLATE 的 CREATE DATABASE 会取**服务器默认值**，
# 而生产库是中文排序规则——两者对中文字符串的**比较与排序语义不同**（影响唯一索引
# 判重、ORDER BY、LIKE）。
_Q_COLLATION = """
SELECT CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS nvarchar(128)) AS COLLATION_NAME
"""

_Q_COLUMNS = """
SELECT
    c.COLUMN_NAME,
    c.ORDINAL_POSITION,
    c.DATA_TYPE,
    c.CHARACTER_MAXIMUM_LENGTH,
    c.NUMERIC_PRECISION,
    c.NUMERIC_SCALE,
    c.IS_NULLABLE,
    c.COLUMN_DEFAULT,
    COLUMNPROPERTY(OBJECT_ID(N'dbo.' + c.TABLE_NAME), c.COLUMN_NAME, 'IsIdentity') AS IS_IDENTITY,
    COLUMNPROPERTY(OBJECT_ID(N'dbo.' + c.TABLE_NAME), c.COLUMN_NAME, 'IsComputed') AS IS_COMPUTED
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME = %s
ORDER BY c.ORDINAL_POSITION
"""

_Q_INDEXES = """
SELECT
    i.name AS INDEX_NAME,
    i.type_desc AS TYPE_DESC,
    i.is_unique AS IS_UNIQUE,
    i.is_primary_key AS IS_PK,
    i.is_unique_constraint AS IS_UNIQUE_CONSTRAINT,
    c.name AS COLUMN_NAME,
    ic.key_ordinal AS KEY_ORDINAL,
    ic.is_descending_key AS IS_DESC
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID(N'dbo.' + %s)
  AND i.type > 0
  AND i.is_hypothetical = 0
  AND ic.is_included_column = 0
ORDER BY i.is_primary_key DESC, i.is_unique_constraint DESC, i.name, ic.key_ordinal
"""

_Q_FOREIGN_KEYS = """
SELECT
    fk.name AS FK_NAME,
    OBJECT_NAME(fk.parent_object_id) AS CHILD_TABLE,
    pc.name AS CHILD_COLUMN,
    OBJECT_NAME(fk.referenced_object_id) AS PARENT_TABLE,
    rc.name AS PARENT_COLUMN,
    fk.delete_referential_action_desc AS ON_DELETE,
    fk.update_referential_action_desc AS ON_UPDATE,
    fkc.constraint_column_id AS ORD
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
WHERE OBJECT_NAME(fk.parent_object_id) = %s
ORDER BY fk.name, fkc.constraint_column_id
"""


# --------------------------------------------------------------------------
# DDL 拼装
# --------------------------------------------------------------------------


def render_type(row: dict) -> str:
    data_type = (row["DATA_TYPE"] or "").lower()
    length = row["CHARACTER_MAXIMUM_LENGTH"]
    precision = row["NUMERIC_PRECISION"]
    scale = row["NUMERIC_SCALE"]

    if data_type in _LENGTH_TYPES:
        if length is None:
            return data_type
        if length == -1:
            return f"{data_type}(max)"
        # nchar/nvarchar 的长度按字符计；其他按字节计，这里直接采用目录里的值
        return f"{data_type}({length})"
    if data_type in _PRECISION_TYPES and precision is not None:
        return f"{data_type}({precision},{scale if scale is not None else 0})"
    if data_type == "float" and precision is not None and precision != 53:
        return f"float({precision})"
    if data_type == "datetime2" and scale is not None and scale != 7:
        return f"datetime2({scale})"
    return data_type


def render_default(raw) -> str:
    """目录里的默认值形如 `((0))` / `(getdate())`，原样带上即可。"""
    if raw is None:
        return ""
    return f" DEFAULT {raw}"


def build_table(cursor, table: str) -> tuple:
    """返回 (表的 DDL, 索引 DDL 列表, 外键 DDL 列表)。"""
    cols = _only_select(cursor, _Q_COLUMNS % (_sql_literal(table),)).fetchall()
    if not cols:
        return None, [], []

    lines = []
    for row in cols:
        name = row["COLUMN_NAME"]
        col = f"    [{name}] {render_type(row)}"
        if row["IS_IDENTITY"]:
            col += " IDENTITY(1,1)"
        col += " NOT NULL" if row["IS_NULLABLE"] == "NO" else " NULL"
        col += render_default(row["COLUMN_DEFAULT"])
        lines.append(col)

    # 主键与唯一约束写成表内约束（更贴近人类写的 DDL）
    idx_rows = _only_select(cursor, _Q_INDEXES % (_sql_literal(table),)).fetchall()
    indexes = {}
    for row in idx_rows:
        indexes.setdefault(row["INDEX_NAME"], []).append(row)

    inline_pk = None
    for idx_name, rows in indexes.items():
        head = rows[0]
        if not head["IS_PK"]:
            continue
        cols_sql = ", ".join(
            f"[{r['COLUMN_NAME']}]" + (" DESC" if r["IS_DESC"] else "") for r in rows
        )
        inline_pk = f"    CONSTRAINT [{idx_name}] PRIMARY KEY ({cols_sql})"
        break
    if inline_pk:
        lines.append(inline_pk)

    ddl = (
        f"IF OBJECT_ID(N'dbo.[{table}]', N'U') IS NULL\n"
        f"BEGIN\n"
        f"CREATE TABLE [dbo].[{table}] (\n"
        + ",\n".join(lines)
        + "\n);\nEND;\n"
    )

    # 唯一约束（非主键）与普通索引，单独出语句
    extra = []
    for idx_name, rows in indexes.items():
        head = rows[0]
        if head["IS_PK"]:
            continue
        cols_sql = ", ".join(
            f"[{r['COLUMN_NAME']}]" + (" DESC" if r["IS_DESC"] else "") for r in rows
        )
        unique = "UNIQUE " if (head["IS_UNIQUE"] or head["IS_UNIQUE_CONSTRAINT"]) else ""
        kind = "UNIQUE INDEX" if unique else "INDEX"
        extra.append(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes "
            f"WHERE name = N'{idx_name}' AND object_id = OBJECT_ID(N'dbo.[{table}]'))\n"
            f"CREATE {unique}NONCLUSTERED INDEX [{idx_name}] ON [dbo].[{table}] ({cols_sql});"
        )

    fk_rows = _only_select(cursor, _Q_FOREIGN_KEYS % (_sql_literal(table),)).fetchall()
    by_fk = {}
    for row in fk_rows:
        by_fk.setdefault(row["FK_NAME"], []).append(row)
    for fk_name, rows in by_fk.items():
        head = rows[0]
        child = ", ".join(f"[{r['CHILD_COLUMN']}]" for r in rows)
        parent = ", ".join(f"[{r['PARENT_COLUMN']}]" for r in rows)
        on_delete = (
            ""
            if head["ON_DELETE"] == "NO_ACTION"
            else f" ON DELETE {head['ON_DELETE'].replace('_', ' ')}"
        )
        on_update = (
            ""
            if head["ON_UPDATE"] == "NO_ACTION"
            else f" ON UPDATE {head['ON_UPDATE'].replace('_', ' ')}"
        )
        extra.append(
            f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'{fk_name}')\n"
            f"ALTER TABLE [dbo].[{table}] WITH CHECK ADD CONSTRAINT [{fk_name}] "
            f"FOREIGN KEY ({child}) REFERENCES [dbo].[{head['PARENT_TABLE']}] ({parent})"
            f"{on_delete}{on_update};"
        )

    return ddl, extra, by_fk


def _sql_literal(value: str) -> str:
    """把表名安全地嵌进单引号里（这些名字来自目录视图，仍按最坏情况转义）。"""
    return "'" + value.replace("'", "''") + "'"


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="导出生产库表结构为幂等建库脚本")
    parser.add_argument("--env-file", default=None, help="默认 .env.prod，无则 .env")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--yes", action="store_true", help="对远程库的显式确认")
    args = parser.parse_args()

    env_path = resolve_env_file(args.env_file)
    env = read_env_file(env_path)

    host = env.get("DB_HOST", "")
    port = int(env.get("DB_PORT") or 1433)
    user = env.get("DB_USER", "")
    password = env.get("DB_PASSWORD", "")
    db_name = env.get("DB_NAME", _DB_TARGET)

    if not host or not user:
        sys.exit(
            f"[中断] {env_path} 里没有可用的 DB_HOST / DB_USER。\n"
            f"       本脚本需要 DB_* 这组直连参数（两条注册/登录路由用的也是它）。"
        )

    print(f"[生产库结构导出] 配置来自 {rel_to_repo(env_path)}")
    confirm_remote(host, db_name)

    import pymssql  # 延迟导入：确认之后才碰驱动，也避免无谓的依赖错误盖过提示

    conn = pymssql.connect(
        server=host, port=port, user=user, password=password,
        database=db_name, charset="utf8", timeout=30, login_timeout=15,
    )
    try:
        cursor = conn.cursor(as_dict=True)
        collation = _only_select(cursor, _Q_COLLATION).fetchone()["COLLATION_NAME"]
        if not re.fullmatch(r"[A-Za-z0-9_]+", collation or ""):
            sys.exit(f"[中断] 从服务器读到的排序规则名不像标识符：{collation!r}，拒绝拼进 DDL。")

        table_rows = _only_select(cursor, _Q_TABLES).fetchall()
        # 本脚本全程按 dbo 拼 DDL（OBJECT_ID(N'dbo.'+name)）。若库里存在别的模式，
        # 硬跑会产出**指向错误对象的脚本**——宁可中止，也不要静默产出错的建库文件。
        odd_schemas = sorted({r["TABLE_SCHEMA"] for r in table_rows} - {"dbo"})
        if odd_schemas:
            sys.exit(
                f"[中断] {db_name} 里存在非 dbo 模式的表：{', '.join(odd_schemas)}。\n"
                f"       本脚本目前只按 dbo 拼 DDL，直接跑会产出错误的脚本。"
                f"请先确认这批表的归属，再按需扩展本脚本。"
            )
        tables = [r["TABLE_NAME"] for r in table_rows]
        if not tables:
            sys.exit(f"[中断] {db_name} 里一张表都没有，导出的脚本会是空的——请核对目标库。")

        print(f"[生产库结构导出] 读到 {len(tables)} 张表，排序规则 {collation}")
        table_blocks, index_blocks, fk_blocks = [], [], []
        for table in tables:
            ddl, extra, by_fk = build_table(cursor, table)
            if ddl is None:
                print(f"    [跳过] {table}：没有列")
                continue
            table_blocks.append(ddl)
            for stmt in extra:
                (fk_blocks if "FOREIGN KEY" in stmt else index_blocks).append(stmt)
            print(f"    {table}: {len(by_fk)} 个外键")
    finally:
        conn.close()

    # 源主机名**刻意不写进产物**：db/schema.sql 是入库文件，而生产 RDS 主机名
    # 属于不该进版本库的那一类（与用户名、口令同级）。
    header = f"""-- ============================================================================
-- 建库脚本（生产开发通用）—— 由 tools/export_prod_schema.py 自动生成，请勿手改。
--
-- 来源：{db_name}（**只读**目录视图导出；源主机名不入库，见 .env.prod）
-- 排序规则：{collation}
-- 生成物用途：对新库执行即建库；对已有库执行是无操作（每条语句都幂等）。
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
-- 而本库是 {collation}，两者对中文字符串的比较/排序语义不同。
IF DB_ID(N'{db_name}') IS NULL
    CREATE DATABASE [{db_name}] COLLATE {collation};
GO

-- 显式切库：这样从 master 连进去直接 -i 本文件也能跑通，
-- 不必要求调用方先自己 CREATE DATABASE 再用 -d 指过来。
USE [{db_name}];
GO

"""

    parts = [header]
    for block in table_blocks:
        parts.append(block + "GO\n")
    if index_blocks:
        parts.append("-- ---------------------------------------------------------------- 索引\n")
        for stmt in index_blocks:
            parts.append(stmt + "\nGO\n")
    if fk_blocks:
        parts.append("-- ------------------------------------------------------------ 外键约束\n")
        for stmt in fk_blocks:
            parts.append(stmt + "\nGO\n")

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 显式指定 newline="\n"：本仓库全 LF，Path.write_text 的平台默认换行会写成 CRLF
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(parts))

    print(f"[生产库结构导出] 已写入 {rel_to_repo(out_path)}")
    print(f"    表 {len(table_blocks)} 张 / 索引 {len(index_blocks)} 条 / 外键 {len(fk_blocks)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
