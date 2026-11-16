# 部署 runbook

## 一次性配置（GitHub）

仓库 Settings → Secrets and variables → Actions 添加：

| Secret | 值 |
|---|---|
| `DEPLOY_HOST` | `47.114.103.74` |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_PATH` | `/opt/smartclass` |
| `DEPLOY_SSH_KEY` | 服务器 `/home/deploy/.ssh/id_ed25519` 的完整内容 |

Settings → Environments 新建 `production`：

- Required reviewer：至少 1 人
- Deployment branches：只允许 `main` 与 `v*` tag

Settings → Branches → `main`：

- Require a pull request before merging
- Require status checks：`quality`、`frontend`、`secret-scan`
- 禁止 force push / 直接 push

## 发布

Actions → `deploy` → Run workflow，`ref` 填 `main`（或要发布的 SHA）。
部署脚本会：

1. `git fetch/checkout` 目标 ref
2. 跑 `tools/apply_migrations.py --dry-run` 和正式迁移
3. `docker compose build app`，保留上一版镜像
4. `docker compose up -d app`
5. 轮询 `http://127.0.0.1:8000/healthz`，失败自动回滚上一版 commit/镜像
6. 全过程写 `/var/log/smartclass-deploy.log`

## 回滚

健康检查失败时脚本自动回滚。手动回滚：

```bash
ssh deploy@47.114.103.74
cd /opt/smartclass
git log --oneline -5
git checkout -f <上一版 SHA>
docker tag algorithm-study-master:pre-<上一版 SHA> algorithm-study-master:dev
docker compose up -d app
```

数据库迁移**不会**自动回滚；发布前应确认迁移向后兼容。

## 迁移失败

迁移在 build 之前执行；失败时脚本直接退出，应用仍运行上一版。
查看 `/var/log/smartclass-deploy.log`，修正迁移或恢复数据库快照后再发布。
