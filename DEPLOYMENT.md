# 智能协作学习系统 - 部署指南

## 一、系统环境要求

### 1.1 服务器配置
- **操作系统**: Ubuntu 20.04 LTS 或 CentOS 7+
- **CPU**: 4核心以上
- **内存**: 8GB以上
- **磁盘**: 50GB以上
- **网络**: 公网IP + 域名(用于SSL)

### 1.2 软件依赖
- Python 3.8+
- FFmpeg 4.3+
- Nginx 1.18+
- MySQL 5.7+ (已有远程数据库)

## 二、依赖安装

### 2.1 系统软件安装

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Python3和pip
sudo apt install python3 python3-pip python3-venv -y

# 安装FFmpeg
sudo apt install ffmpeg -y

# 安装Nginx
sudo apt install nginx -y

# 验证安装
python3 --version
ffmpeg -version
nginx -v
```

### 2.2 Python依赖安装

```bash
# 进入项目目录
cd /path/to/algorithm-study-master

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install fastapi uvicorn[standard] sqlalchemy pymysql opencv-python numpy openai aiohttp websockets
```

### 2.3 依赖清单
创建 `requirements.txt`:
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pymysql==1.1.0
opencv-python==4.8.1.78
numpy==1.24.3
openai==1.3.5
aiohttp==3.9.1
websockets==12.0
```

安装:
```bash
pip install -r requirements.txt
```

## 三、项目部署

### 3.1 项目上传

```bash
# 使用scp上传
scp -r algorithm-study-master user@your-server:/opt/

# 或使用git克隆
cd /opt
git clone <your-repo-url> algorithm-study-master
cd algorithm-study-master
```

### 3.2 配置文件检查

检查 `database.py` 中的数据库连接:
```python
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:3308/<DB_NAME>?charset=utf8mb4"
```

检查 `llm_service.py` 中的API密钥:
```python
API_KEY = os.getenv("LLM_API_KEY", "")  # 从 .env 读取
BASE_URL = "https://api.deepseek.com"
```

### 3.3 创建存储目录

```bash
cd /opt/algorithm-study-master
mkdir -p storage/video_chunks storage/audio_chunks storage/snapshots
chmod 755 storage -R
```

### 3.4 测试运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 测试启动
python server.py

# 应该看到:
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

访问 `http://your-server-ip:8000` 测试是否正常。

## 四、Systemd服务配置

### 4.1 创建服务文件

创建 `/etc/systemd/system/smart-learning.service`:

```ini
[Unit]
Description=Smart Collaborative Learning System
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/algorithm-study-master
Environment="PATH=/opt/algorithm-study-master/venv/bin"
ExecStart=/opt/algorithm-study-master/venv/bin/python server.py
Restart=always
RestartSec=10

# 日志输出
StandardOutput=append:/var/log/smart-learning.log
StandardError=append:/var/log/smart-learning-error.log

[Install]
WantedBy=multi-user.target
```

### 4.2 启动服务

```bash
# 重载systemd配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start smart-learning

# 查看状态
sudo systemctl status smart-learning

# 开机自启
sudo systemctl enable smart-learning

# 查看日志
sudo journalctl -u smart-learning -f
```

## 五、Nginx反向代理配置

### 5.1 创建配置文件

创建 `/etc/nginx/sites-available/smart-learning`:

```nginx
# HTTP重定向到HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS配置
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL证书配置
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 日志
    access_log /var/log/nginx/smart-learning-access.log;
    error_log /var/log/nginx/smart-learning-error.log;

    # 客户端上传大小限制(视频文件)
    client_max_body_size 100M;

    # WebSocket超时设置
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    # 根路径
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket路由
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # WebSocket保持连接
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # 静态文件缓存
    location /storage/ {
        proxy_pass http://127.0.0.1:8000/storage/;
        expires 1h;
        add_header Cache-Control "public, immutable";
    }
}
```

### 5.2 启用配置

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/smart-learning /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启Nginx
sudo systemctl restart nginx
```

## 六、SSL证书配置(Let's Encrypt)

### 6.1 安装Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
```

### 6.2 获取证书

```bash
# 自动配置
sudo certbot --nginx -d your-domain.com

# 或手动模式
sudo certbot certonly --nginx -d your-domain.com
```

### 6.3 自动续期

```bash
# 测试续期
sudo certbot renew --dry-run

# Certbot会自动创建cron任务,无需手动配置
```

## 七、防火墙配置

### 7.1 UFW防火墙

```bash
# 允许HTTP和HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 允许SSH(如果还没开)
sudo ufw allow 22/tcp

# 启用防火墙
sudo ufw enable

# 查看状态
sudo ufw status
```

## 八、性能优化

### 8.1 系统参数调优

编辑 `/etc/sysctl.conf`:
```bash
# 增加TCP连接数
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096

# 文件描述符
fs.file-max = 65535
```

应用:
```bash
sudo sysctl -p
```

### 8.2 Nginx优化

编辑 `/etc/nginx/nginx.conf`:
```nginx
worker_processes auto;
worker_connections 4096;

# 开启gzip压缩
gzip on;
gzip_types text/plain text/css application/json application/javascript;
```

### 8.3 应用层优化

在 `server.py` 中:
```python
# 数据库连接池
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=20,        # 增加连接池
    max_overflow=10,
    pool_recycle=3600,
    pool_pre_ping=True
)
```

## 九、监控与日志

### 9.1 日志管理

```bash
# 查看应用日志
sudo tail -f /var/log/smart-learning.log

# 查看错误日志
sudo tail -f /var/log/smart-learning-error.log

# 查看Nginx日志
sudo tail -f /var/log/nginx/smart-learning-access.log
sudo tail -f /var/log/nginx/smart-learning-error.log
```

### 9.2 日志轮转

创建 `/etc/logrotate.d/smart-learning`:
```
/var/log/smart-learning*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 9.3 系统监控

```bash
# 查看CPU和内存
htop

# 查看网络连接
netstat -tulpn | grep 8000

# 查看进程
ps aux | grep python
```

## 十、备份策略

### 10.1 数据库备份

```bash
# 创建备份脚本 /opt/backup/backup_db.sh
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mysqldump -h <DB_HOST> -P 3308 -u <DB_USER> -p'<DB_PASSWORD>' <DB_NAME> > /opt/backup/db_$DATE.sql
# 保留最近7天的备份
find /opt/backup -name "db_*.sql" -mtime +7 -delete
```

添加到crontab:
```bash
# 每天凌晨2点备份
0 2 * * * /opt/backup/backup_db.sh
```

### 10.2 文件备份

```bash
# 备份重要文件
tar -czf /opt/backup/files_$(date +%Y%m%d).tar.gz \
  /opt/algorithm-study-master/storage/snapshots
```

## 十一、故障排查

### 11.1 常见问题

**问题1: 服务无法启动**
```bash
# 检查端口占用
sudo lsof -i :8000

# 检查Python路径
which python3

# 查看详细错误
sudo journalctl -u smart-learning -n 50
```

**问题2: WebSocket连接失败**
```bash
# 检查Nginx配置
sudo nginx -t

# 查看Nginx错误日志
sudo tail -f /var/log/nginx/error.log

# 确认upgrade header
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" http://localhost:8000/ws/test/1
```

**问题3: 视频处理慢**
```bash
# 检查FFmpeg版本
ffmpeg -version

# 监控CPU使用
top

# 考虑增加服务器配置或使用GPU加速
```

### 11.2 性能诊断

```bash
# 并发测试
python test_concurrent_users.py

# 压力测试
ab -n 1000 -c 10 http://your-domain.com/
```

## 十二、安全加固

### 12.1 系统安全

```bash
# 禁用root登录
sudo vim /etc/ssh/sshd_config
# PermitRootLogin no

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装fail2ban
sudo apt install fail2ban -y
```

### 12.2 应用安全

1. **API密钥保护**: 将敏感信息移到环境变量
2. **CORS配置**: 限制跨域请求来源
3. **速率限制**: 防止API滥用
4. **输入验证**: 防止SQL注入和XSS

## 十三、扩展部署(高可用)

### 13.1 负载均衡

使用Nginx upstream:
```nginx
upstream smart_learning_backend {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    location / {
        proxy_pass http://smart_learning_backend;
    }
}
```

### 13.2 多进程部署

使用Gunicorn:
```bash
pip install gunicorn
gunicorn server:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

---

## 快速部署命令汇总

```bash
# 1. 安装依赖
sudo apt update && sudo apt install python3 python3-pip python3-venv ffmpeg nginx -y

# 2. 项目部署
cd /opt/algorithm-study-master
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 创建服务
sudo cp smart-learning.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start smart-learning
sudo systemctl enable smart-learning

# 4. 配置Nginx
sudo cp nginx-config /etc/nginx/sites-available/smart-learning
sudo ln -s /etc/nginx/sites-available/smart-learning /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

# 5. SSL证书
sudo certbot --nginx -d your-domain.com

# 6. 防火墙
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 完成!
```

## 联系与支持

如有问题,请查看:
- 应用日志: `/var/log/smart-learning.log`
- Nginx日志: `/var/log/nginx/smart-learning-error.log`
- 系统日志: `sudo journalctl -u smart-learning`

---

## 十四、生产环境变量（建议）

> 当前仓库中部分密钥仍存在于代码文件。上线前建议改为环境变量注入，并在 CI/CD 或服务器密钥管理中维护。

### 14.1 推荐变量清单

| 变量名 | 用途 | 示例 |
|---|---|---|
| `APP_ENV` | 运行环境标识 | `production` |
| `APP_HOST` | 服务监听地址 | `0.0.0.0` |
| `APP_PORT` | 服务端口 | `8000` |
| `DATABASE_URL` | 数据库连接串 | `mssql+pymssql://user:pass@host:3433/db?charset=utf8` |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥 | `sk-xxxx` |
| `DEEPSEEK_BASE_URL` | DeepSeek 地址 | `https://api.deepseek.com` |
| `OLLAMA_BASE_URL` | 本地/内网 Ollama 地址 | `http://127.0.0.1:11434` |
| `GEMMA_MODEL` | Gemma 模型名 | `gemma4:e4b` |
| `OSS_ACCESS_KEY_ID` | OSS AccessKey ID | `LTAIxxxxx` |
| `OSS_ACCESS_KEY_SECRET` | OSS AccessKey Secret | `******` |
| `OSS_BUCKET_NAME` | OSS Bucket | `collaborative-learning-videos` |
| `OSS_ENDPOINT` | OSS Endpoint | `oss-cn-hangzhou.aliyuncs.com` |

### 14.2 systemd 注入方式（推荐）

1. 新建环境文件（仅 root 可读）：

```bash
sudo mkdir -p /etc/smart-learning
sudo vim /etc/smart-learning/smart-learning.env
sudo chmod 600 /etc/smart-learning/smart-learning.env
```

2. 示例内容：

```bash
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=mssql+pymssql://user:pass@host:3433/db?charset=utf8
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
OLLAMA_BASE_URL=http://127.0.0.1:11434
GEMMA_MODEL=gemma4:e4b
OSS_ACCESS_KEY_ID=LTAIxxxxx
OSS_ACCESS_KEY_SECRET=xxxxxx
OSS_BUCKET_NAME=collaborative-learning-videos
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
```

3. 在服务文件中增加：

```ini
EnvironmentFile=/etc/smart-learning/smart-learning.env
```

4. 重载并生效：

```bash
sudo systemctl daemon-reload
sudo systemctl restart smart-learning
sudo systemctl status smart-learning
```

---

## 十五、回滚步骤（生产）

### 15.1 触发条件

- 发布后健康检查失败（接口 5xx、WebSocket 大量断连）
- 关键能力退化（情绪识别/报告生成明显异常）
- 资源异常（CPU、内存、连接数飙升且无法快速恢复）

### 15.2 标准回滚流程（建议 10 分钟内完成）

1. **冻结发布**
```bash
sudo systemctl stop smart-learning
```

2. **切回上一版本代码**
```bash
cd /opt/algorithm-study-master
git fetch --all --tags
git checkout <last_stable_tag_or_commit>
```

3. **恢复上一版依赖（如有变化）**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

4. **恢复上一版配置**
- 回滚 `/etc/smart-learning/smart-learning.env` 到备份版本
- 确认 Nginx 配置未引入不兼容改动

5. **重启服务并验证**
```bash
sudo systemctl start smart-learning
sudo systemctl status smart-learning
curl -f http://127.0.0.1:8000/ || echo "health check failed"
```

6. **必要时回滚数据库**
- 仅在本次发布包含破坏性 schema 变更时执行
- 优先使用发布前快照/备份，避免手动回改线上表结构

7. **对外通告**
- 在团队群发布“已回滚至版本 `<tag/commit>`、影响范围、后续修复计划”

### 15.3 回滚前必须准备

- 每次上线前打 tag（如 `release-YYYYMMDD-HHMM`）
- 保留至少 1 份可用数据库快照
- 保留最近一次可运行的 `smart-learning.env` 备份
- 明确值班人与升级窗口，避免无人值守发布
# 智能协作学习系统 - 部署指南

## 一、系统环境要求

### 1.1 服务器配置
- **操作系统**: Ubuntu 20.04 LTS 或 CentOS 7+
- **CPU**: 4核心以上
- **内存**: 8GB以上
- **磁盘**: 50GB以上
- **网络**: 公网IP + 域名(用于SSL)

### 1.2 软件依赖
- Python 3.8+
- FFmpeg 4.3+
- Nginx 1.18+
- MySQL 5.7+ (已有远程数据库)

## 二、依赖安装

### 2.1 系统软件安装

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Python3和pip
sudo apt install python3 python3-pip python3-venv -y

# 安装FFmpeg
sudo apt install ffmpeg -y

# 安装Nginx
sudo apt install nginx -y

# 验证安装
python3 --version
ffmpeg -version
nginx -v
```

### 2.2 Python依赖安装

```bash
# 进入项目目录
cd /path/to/algorithm-study-master

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install fastapi uvicorn[standard] sqlalchemy pymysql opencv-python numpy openai aiohttp websockets
```

### 2.3 依赖清单
创建 `requirements.txt`:
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pymysql==1.1.0
opencv-python==4.8.1.78
numpy==1.24.3
openai==1.3.5
aiohttp==3.9.1
websockets==12.0
```

安装:
```bash
pip install -r requirements.txt
```

## 三、项目部署

### 3.1 项目上传

```bash
# 使用scp上传
scp -r algorithm-study-master user@your-server:/opt/

# 或使用git克隆
cd /opt
git clone <your-repo-url> algorithm-study-master
cd algorithm-study-master
```

### 3.2 配置文件检查

检查 `database.py` 中的数据库连接:
```python
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:3308/<DB_NAME>?charset=utf8mb4"
```

检查 `llm_service.py` 中的API密钥:
```python
API_KEY = os.getenv("LLM_API_KEY", "")  # 从 .env 读取
BASE_URL = "https://api.deepseek.com"
```

### 3.3 创建存储目录

```bash
cd /opt/algorithm-study-master
mkdir -p storage/video_chunks storage/audio_chunks storage/snapshots
chmod 755 storage -R
```

### 3.4 测试运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 测试启动
python server.py

# 应该看到:
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

访问 `http://your-server-ip:8000` 测试是否正常。

## 四、Systemd服务配置

### 4.1 创建服务文件

创建 `/etc/systemd/system/smart-learning.service`:

```ini
[Unit]
Description=Smart Collaborative Learning System
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/algorithm-study-master
Environment="PATH=/opt/algorithm-study-master/venv/bin"
ExecStart=/opt/algorithm-study-master/venv/bin/python server.py
Restart=always
RestartSec=10

# 日志输出
StandardOutput=append:/var/log/smart-learning.log
StandardError=append:/var/log/smart-learning-error.log

[Install]
WantedBy=multi-user.target
```

### 4.2 启动服务

```bash
# 重载systemd配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start smart-learning

# 查看状态
sudo systemctl status smart-learning

# 开机自启
sudo systemctl enable smart-learning

# 查看日志
sudo journalctl -u smart-learning -f
```

## 五、Nginx反向代理配置

### 5.1 创建配置文件

创建 `/etc/nginx/sites-available/smart-learning`:

```nginx
# HTTP重定向到HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS配置
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL证书配置
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 日志
    access_log /var/log/nginx/smart-learning-access.log;
    error_log /var/log/nginx/smart-learning-error.log;

    # 客户端上传大小限制(视频文件)
    client_max_body_size 100M;

    # WebSocket超时设置
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    # 根路径
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket路由
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # WebSocket保持连接
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # 静态文件缓存
    location /storage/ {
        proxy_pass http://127.0.0.1:8000/storage/;
        expires 1h;
        add_header Cache-Control "public, immutable";
    }
}
```

### 5.2 启用配置

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/smart-learning /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启Nginx
sudo systemctl restart nginx
```

## 六、SSL证书配置(Let's Encrypt)

### 6.1 安装Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
```

### 6.2 获取证书

```bash
# 自动配置
sudo certbot --nginx -d your-domain.com

# 或手动模式
sudo certbot certonly --nginx -d your-domain.com
```

### 6.3 自动续期

```bash
# 测试续期
sudo certbot renew --dry-run

# Certbot会自动创建cron任务,无需手动配置
```

## 七、防火墙配置

### 7.1 UFW防火墙

```bash
# 允许HTTP和HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 允许SSH(如果还没开)
sudo ufw allow 22/tcp

# 启用防火墙
sudo ufw enable

# 查看状态
sudo ufw status
```

## 八、性能优化

### 8.1 系统参数调优

编辑 `/etc/sysctl.conf`:
```bash
# 增加TCP连接数
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096

# 文件描述符
fs.file-max = 65535
```

应用:
```bash
sudo sysctl -p
```

### 8.2 Nginx优化

编辑 `/etc/nginx/nginx.conf`:
```nginx
worker_processes auto;
worker_connections 4096;

# 开启gzip压缩
gzip on;
gzip_types text/plain text/css application/json application/javascript;
```

### 8.3 应用层优化

在 `server.py` 中:
```python
# 数据库连接池
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=20,        # 增加连接池
    max_overflow=10,
    pool_recycle=3600,
    pool_pre_ping=True
)
```

## 九、监控与日志

### 9.1 日志管理

```bash
# 查看应用日志
sudo tail -f /var/log/smart-learning.log

# 查看错误日志
sudo tail -f /var/log/smart-learning-error.log

# 查看Nginx日志
sudo tail -f /var/log/nginx/smart-learning-access.log
sudo tail -f /var/log/nginx/smart-learning-error.log
```

### 9.2 日志轮转

创建 `/etc/logrotate.d/smart-learning`:
```
/var/log/smart-learning*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 9.3 系统监控

```bash
# 查看CPU和内存
htop

# 查看网络连接
netstat -tulpn | grep 8000

# 查看进程
ps aux | grep python
```

## 十、备份策略

### 10.1 数据库备份

```bash
# 创建备份脚本 /opt/backup/backup_db.sh
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mysqldump -h <DB_HOST> -P 3308 -u <DB_USER> -p'<DB_PASSWORD>' <DB_NAME> > /opt/backup/db_$DATE.sql
# 保留最近7天的备份
find /opt/backup -name "db_*.sql" -mtime +7 -delete
```

添加到crontab:
```bash
# 每天凌晨2点备份
0 2 * * * /opt/backup/backup_db.sh
```

### 10.2 文件备份

```bash
# 备份重要文件
tar -czf /opt/backup/files_$(date +%Y%m%d).tar.gz \
  /opt/algorithm-study-master/storage/snapshots
```

## 十一、故障排查

### 11.1 常见问题

**问题1: 服务无法启动**
```bash
# 检查端口占用
sudo lsof -i :8000

# 检查Python路径
which python3

# 查看详细错误
sudo journalctl -u smart-learning -n 50
```

**问题2: WebSocket连接失败**
```bash
# 检查Nginx配置
sudo nginx -t

# 查看Nginx错误日志
sudo tail -f /var/log/nginx/error.log

# 确认upgrade header
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" http://localhost:8000/ws/test/1
```

**问题3: 视频处理慢**
```bash
# 检查FFmpeg版本
ffmpeg -version

# 监控CPU使用
top

# 考虑增加服务器配置或使用GPU加速
```

### 11.2 性能诊断

```bash
# 并发测试
python test_concurrent_users.py

# 压力测试
ab -n 1000 -c 10 http://your-domain.com/
```

## 十二、安全加固

### 12.1 系统安全

```bash
# 禁用root登录
sudo vim /etc/ssh/sshd_config
# PermitRootLogin no

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装fail2ban
sudo apt install fail2ban -y
```

### 12.2 应用安全

1. **API密钥保护**: 将敏感信息移到环境变量
2. **CORS配置**: 限制跨域请求来源
3. **速率限制**: 防止API滥用
4. **输入验证**: 防止SQL注入和XSS

## 十三、扩展部署(高可用)

### 13.1 负载均衡

使用Nginx upstream:
```nginx
upstream smart_learning_backend {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    location / {
        proxy_pass http://smart_learning_backend;
    }
}
```

### 13.2 多进程部署

使用Gunicorn:
```bash
pip install gunicorn
gunicorn server:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

---

## 快速部署命令汇总

```bash
# 1. 安装依赖
sudo apt update && sudo apt install python3 python3-pip python3-venv ffmpeg nginx -y

# 2. 项目部署
cd /opt/algorithm-study-master
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 创建服务
sudo cp smart-learning.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start smart-learning
sudo systemctl enable smart-learning

# 4. 配置Nginx
sudo cp nginx-config /etc/nginx/sites-available/smart-learning
sudo ln -s /etc/nginx/sites-available/smart-learning /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

# 5. SSL证书
sudo certbot --nginx -d your-domain.com

# 6. 防火墙
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 完成!
```

## 联系与支持

如有问题,请查看:
- 应用日志: `/var/log/smart-learning.log`
- Nginx日志: `/var/log/nginx/smart-learning-error.log`
- 系统日志: `sudo journalctl -u smart-learning`
