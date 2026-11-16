#!/usr/bin/env bash
#
# 服务器原地部署：git checkout -> 迁移 -> docker compose build/up -> 健康检查。
#
# 由 GitHub Actions 以 deploy 用户调用：
#   ./deploy/deploy.sh <git-ref-or-sha>
#
# 失败时回滚到上一版 commit 与镜像；数据库迁移不做自动回滚。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/smartclass}"
BRANCH="${BRANCH:-main}"
LOG_FILE="${LOG_FILE:-/var/log/smartclass-deploy.log}"
LOCK_FILE="${LOCK_FILE:-/var/lock/smartclass-deploy.lock}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/healthz}"
TARGET_REF="${1:-origin/main}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "another deploy is already running" >&2
    exit 1
fi
exec >>"$LOG_FILE" 2>&1

echo "=== $(date -Is) deploy target=$TARGET_REF ==="

cd "$APP_DIR"
# 生产用独立编排；--project-directory 让 .env/.env.prod/build context 相对仓库根解析
COMPOSE=(docker compose --project-directory . -f deploy/docker-compose.prod.yml)

avail_kb="$(df -Pk "$APP_DIR" | awk 'NR==2 {print $4}')"
if [ "${avail_kb:-0}" -lt 5000000 ]; then
    echo "not enough disk space: ${avail_kb} KB available, need 5 GB"
    exit 1
fi

if [ "${CONFIRM_DB_BACKUP:-}" != "1" ]; then
    echo "database backup not confirmed; take an RDS snapshot, then set CONFIRM_DB_BACKUP=1"
    exit 1
fi

git fetch --depth 1 origin "$BRANCH"
PREV="$(git rev-parse HEAD)"

if [ "$TARGET_REF" = "$BRANCH" ] || [ "$TARGET_REF" = "origin/$BRANCH" ]; then
    # 本地 main 可能落后或分叉；强制重置到刚 fetch 的远程分支
    TARGET_REF="origin/$BRANCH"
    git checkout -f -B "$BRANCH" "$TARGET_REF"
else
    if ! git cat-file -e "${TARGET_REF}^{commit}" 2>/dev/null; then
        git fetch --depth 1 origin "$TARGET_REF"
    fi
    git checkout -f "$TARGET_REF"
fi

NEW="$(git rev-parse HEAD)"
echo "previous=$PREV new=$NEW"

# 保留上一版镜像，健康检查失败时回滚
docker tag algorithm-study-master:dev "algorithm-study-master:pre-$PREV" 2>/dev/null || true

echo "--- migrations ---"
"${COMPOSE[@]}" run --rm --no-deps app python tools/apply_migrations.py --dry-run
"${COMPOSE[@]}" run --rm --no-deps app python tools/apply_migrations.py

echo "--- build ---"
"${COMPOSE[@]}" build app
docker tag algorithm-study-master:dev "algorithm-study-master:$NEW"

echo "--- restart ---"
"${COMPOSE[@]}" up -d app

healthy=0
for _ in $(seq 1 30); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 2
done

if [ "$healthy" -ne 1 ]; then
    echo "health check failed, rolling back to $PREV"
    git checkout -f "$PREV"
    docker tag "algorithm-study-master:pre-$PREV" algorithm-study-master:dev 2>/dev/null || true
    "${COMPOSE[@]}" up -d app
    echo "rollback triggered; previous container restored (migrations are not rolled back)"
    exit 1
fi

echo "=== deploy ok: $NEW ==="
