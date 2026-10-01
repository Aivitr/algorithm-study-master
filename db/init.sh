#!/usr/bin/env bash
# 一次性建库服务（compose 里的 `db-init`）的入口脚本。
#
# MSSQL 官方镜像**没有** postgres/mysql 那样的 `/docker-entrypoint-initdb.d`
# 自动执行目录，所以只能另起一个一次性容器来跑脚本。
#
# 它做的事：把 `db/schema.sql` 灌进 db 服务。
#   - schema.sql 自带 `IF DB_ID(...) IS NULL CREATE DATABASE` + `USE`，
#     所以从 master 连进去直接跑即可，不需要预先建库。
#   - 每张表/索引/外键都包在 IF ... IS NULL / IF NOT EXISTS 里，
#     所以**重复执行是无操作**，`docker compose up` 反复跑不会报错。
#
# `-b` 让 sqlcmd 遇到 SQL 错误就返回非零 —— 这样建库失败会让 db-init 变成
# failed，compose 就不会继续拉起 app（否则 app 连着一个空库，注册时会报
# 一个和真实原因毫无关系的错）。
set -euo pipefail

SQLCMD=/opt/mssql-tools18/bin/sqlcmd
: "${MSSQL_SA_PASSWORD:?db-init 需要 MSSQL_SA_PASSWORD（由 docker-compose.yml 提供）}"
# 刻意**不用** DB_* 这个名字：那是 app 服务的命名空间（见 docker-compose.yml 里的
# 反向断言测试）。db-init 是运维侧的一次性容器，不该去读 app 的库配置，
# 否则 `.env` 里那份生产 DB_* 有朝一日被挂上来，建库就建到生产去了。
MSSQL_HOST="${MSSQL_HOST:-db}"
MSSQL_DB="${MSSQL_DB:-cscl_db}"

echo "[db-init] 等待 ${MSSQL_HOST} 接受连接..."
for attempt in $(seq 1 30); do
    if "$SQLCMD" -S "$MSSQL_HOST" -U sa -P "$MSSQL_SA_PASSWORD" -C -b -Q "SELECT 1" >/dev/null 2>&1; then
        echo "[db-init] ${MSSQL_HOST} 已就绪（第 ${attempt} 次尝试）"
        break
    fi
    if [ "$attempt" -eq 30 ]; then
        echo "[db-init] 等不到 ${MSSQL_HOST}，放弃。" >&2
        exit 1
    fi
    sleep 2
done

echo "[db-init] 执行 schema.sql（幂等，重复跑无副作用）..."
# -f 65001：schema.sql 是 UTF-8 无 BOM，里面含中文注释，不指定代码页会被按控制台
#   代码页误读。表名列名都是 ASCII，注释读花不影响执行，但没必要留这个坑。
"$SQLCMD" -S "$DB_HOST" -U sa -P "$MSSQL_SA_PASSWORD" -C -b -f 65001 -i /db/schema.sql

echo "[db-init] 完成：${MSSQL_DB} 已建好/已是最新结构。"
