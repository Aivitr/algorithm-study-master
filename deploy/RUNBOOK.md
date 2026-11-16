# 部署 runbook

## 一次性配置（GitHub）

仓库 Settings → Secrets and variables → Actions：

| 类型 | 名称 | 值 |
|---|---|---|
| Variable | `DEPLOY_HOST` | `47.114.103.74` |
| Variable | `DEPLOY_USER` | `deploy` |
| Variable | `DEPLOY_PATH` | `/opt/smartclass` |
| Secret | `DEPLOY_SSH_KEY` | 服务器 `/home/deploy/.ssh/id_ed25519` 的完整内容 |

Settings → Environments 新建 `production`：

- Required reviewer：至少 1 人
- Deployment branches：只允许 `main` 与 `v*` tag

Settings → Branches → `main`：

- Require a pull request before merging
- Require status checks：`quality`、`frontend`、`secret-scan`
- 禁止 force push / 直接 push

## 发布

Actions → `deploy` → Run workflow，`ref` 填 `main`（或要发布的 SHA）；
必须先创建 RDS 快照并勾选 `confirm_db_backup`，否则脚本会在迁移前中止。
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
docker compose --project-directory . -f deploy/docker-compose.prod.yml up -d app
```

数据库迁移**不会**自动回滚；发布前应确认迁移向后兼容。

## 日志与告警

- 应用容器日志用 Docker `json-file`，单文件 50MB、保留 5 个（见
  `deploy/docker-compose.prod.yml`）。磁盘仍持续增长时先查
  `docker system df` 和 `/var/lib/docker`。
- 部署失败会以 GitHub Actions 失败运行的形式显示；仓库 Actions 页面和
  GitHub 通知即可看到。需要外部告警时，在阿里云 CloudMonitor/拨测里对
  `https://47.114.103.74/healthz` 配置 1 分钟探测，返回非 200 告警。
- 依赖安全告警：仓库 Settings → Code security 开启 Dependabot alerts；
  `.github/dependabot.yml` 只自动升级 GitHub Actions，Python 依赖仍走
  `uv.lock`，避免自动改 `pyproject.toml` 后 `--frozen` 构建失败。

## 密钥与 SSH 轮换

- `.env` / `.env.prod` 不进 Git；轮换 LLM/OSS/阿里云密钥时改文件后重启 app：
  `docker compose --project-directory . -f deploy/docker-compose.prod.yml up -d app`。
- `DEPLOY_SSH_KEY` 轮换：在服务器生成新 ed25519 key，把公钥加入
  `/home/deploy/.ssh/authorized_keys`，把私钥更新到 GitHub Secret，再删除旧公钥。
- 服务器 root 密码登录当前按用户要求保留；关闭前先确认新 deploy key 可登录。

## 迁移失败

迁移在 build 之前执行；失败时脚本直接退出，应用仍运行上一版。
查看 `/var/log/smartclass-deploy.log`，修正迁移或恢复数据库快照后再发布。
