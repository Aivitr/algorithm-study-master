# 智能协作学习系统 - 服务器部署指南

## 📋 部署概述

本指南将帮助你把智能协作学习系统部署到 **smartclass1.top** 服务器上。

**域名**: https://smartclass1.top
**部署路径**: /opt/smartclass1
**服务名称**: smartclass1

---

## 🚀 快速部署 (推荐)

### 方式一: 使用一键部署脚本

1. **上传项目到服务器**

```bash
# 在本地执行
cd algorithm-study-master
scp -r . root@smartclass1.top:/opt/smartclass1/
```

2. **执行部署脚本**

```bash
# 在服务器上执行
cd /opt/smartclass1
chmod +x deploy/deploy.sh
sudo ./deploy/deploy.sh
```

脚本会自动完成:
- ✅ 安装系统依赖 (Python, FFmpeg, Nginx)
- ✅ 创建 Python 虚拟环境
- ✅ 安装 Python 依赖包
- ✅ 配置 Systemd 服务
- ✅ 配置 Nginx 反向代理
- ✅ 申请 SSL 证书
- ✅ 配置防火墙
- ✅ 启动服务

---

## 📝 手动部署步骤

如果你想手动控制每一步,可以按照以下步骤操作。

> ⚠️ **顺序修正**：下面的 **7. 配置 Nginx → 8. 配置 SSL 证书** 这个顺序会失败 ——
> `deploy/nginx-smartclass1.conf` 引用了 `/etc/letsencrypt/live/<域名>/` 下的证书，
> 首次部署时证书还不存在，`nginx -t` 必然报 `cannot load certificate`，于是永远走不到申请证书那一步。
> 正确顺序是：先放一份**只监听 80、只提供 `/.well-known/acme-challenge/`** 的临时配置并 reload，
> 用 `certbot certonly --webroot -w /var/www/certbot -d <域名>` 拿到证书，**最后**才装载正式配置。
> `deploy.sh` 已按此顺序实现（`bootstrap_http_nginx → configure_ssl → configure_nginx`），
> 手动部署时请照此调整。另外要求 Python >= 3.11（SQLAlchemy 2.1 的下限）。


### 1. 准备服务器环境

**服务器要求:**
- 操作系统: Ubuntu 20.04+ / CentOS 7+
- CPU: 4核心以上
- 内存: 8GB 以上
- 磁盘: 50GB 以上
- 已绑定域名: smartclass1.top

**安装系统依赖:**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv ffmpeg nginx certbot python3-certbot-nginx git

# CentOS/RHEL
sudo yum update -y
sudo yum install -y python3 python3-pip ffmpeg nginx certbot python3-certbot-nginx git epel-release
```

### 2. 上传项目文件

**方式 A: 使用 SCP 上传**

```bash
# 在本地执行
scp -r algorithm-study-master root@smartclass1.top:/opt/smartclass1/
```

**方式 B: 使用 Git 克隆**

```bash
# 在服务器上执行
cd /opt
git clone <your-repo-url> smartclass1
cd smartclass1
```

### 3. 创建目录结构

```bash
cd /opt/smartclass1

# 创建必要的目录
sudo mkdir -p /etc/smartclass1
sudo mkdir -p /var/log/smartclass1
sudo mkdir -p storage/{video_chunks,audio_chunks,snapshots}
sudo mkdir -p storage/{research_models,research_gallery,research_runtime_cache}
```

### 4. 配置 Python 环境

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装依赖
pip install -r requirements.txt

# 如果没有 requirements.txt,手动安装
# 注意必须是 pymssql（MSSQL 驱动），不是 pymysql（MySQL 驱动）
pip install fastapi uvicorn[standard] sqlalchemy pymssql opencv-python numpy openai aiohttp websockets python-multipart
# webrtcvad 需要 pkg_resources，setuptools>=81 已删除该模块，因此必须锁定
pip install "setuptools<81"
```

### 5. 配置环境变量

```bash
# 复制环境变量模板
sudo cp deploy/smartclass1.env.example /etc/smartclass1/smartclass1.env

# 编辑配置文件
sudo nano /etc/smartclass1/smartclass1.env
```

**必须配置的项目:**

```bash
# 数据库连接 (修改为你的实际数据库信息)
# 本项目用 SQL Server (MSSQL)，不是 MySQL —— 驱动是 pymssql，默认端口 3433。
# charset 必须保持 utf8：改成 cp936 会让中文在写入时被二次编码、不可逆损坏。
DATABASE_URL=mssql+pymssql://username:password@host:3433/database?charset=utf8

# DeepSeek API 密钥
LLM_API_KEY=sk-your-deepseek-api-key

# 阿里云语音识别（不配则课堂内没有实时字幕）
ALIYUN_ACCESS_KEY_ID=your-access-key-id
ALIYUN_ACCESS_KEY_SECRET=your-access-key-secret
ALIYUN_APP_KEY=your-app-key

# 阿里云 OSS (可选)
# 只有下面两行会被读取；bucket / endpoint / domain 在 oss_config.py 里是硬编码的，
# 写在这里不生效，要换必须改 oss_config.py。
OSS_ACCESS_KEY_ID=your-oss-key-id
OSS_ACCESS_KEY_SECRET=your-oss-key-secret
```

**建库时排序规则**（否则 `varchar` 列存不了中文）:

```sql
CREATE DATABASE <db> COLLATE Chinese_PRC_CI_AS;
```

**保护配置文件:**

```bash
sudo chmod 600 /etc/smartclass1/smartclass1.env
```

### 6. 配置 Systemd 服务

```bash
# 复制服务文件
sudo cp deploy/smartclass1.service /etc/systemd/system/

# 重载 systemd
sudo systemctl daemon-reload

# 启用服务 (开机自启)
sudo systemctl enable smartclass1

# 启动服务
sudo systemctl start smartclass1

# 查看服务状态
sudo systemctl status smartclass1
```

### 7. 配置 Nginx

```bash
# 复制 Nginx 配置
sudo cp deploy/nginx-smartclass1.conf /etc/nginx/sites-available/smartclass1

# 创建软链接
sudo ln -s /etc/nginx/sites-available/smartclass1 /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

### 8. 配置 SSL 证书

```bash
# 使用 Let's Encrypt 自动配置 SSL
sudo certbot --nginx -d smartclass1.top -d www.smartclass1.top

# 测试自动续期
sudo certbot renew --dry-run
```

### 9. 配置防火墙

```bash
# Ubuntu (UFW)
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw enable

# CentOS (Firewalld)
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 10. 设置文件权限

```bash
sudo chown -R www-data:www-data /opt/smartclass1
sudo chmod -R 755 /opt/smartclass1
sudo chown -R www-data:www-data /var/log/smartclass1
```

---

## ✅ 验证部署

### 1. 检查服务状态

```bash
# 检查应用服务
sudo systemctl status smartclass1

# 检查 Nginx
sudo systemctl status nginx

# 查看应用日志
sudo tail -f /var/log/smartclass1/app.log

# 查看错误日志
sudo tail -f /var/log/smartclass1/error.log
```

### 2. 测试访问

```bash
# 测试本地访问
curl http://localhost:8000

# 测试域名访问
curl https://smartclass1.top
```

### 3. 浏览器访问

打开浏览器访问: **https://smartclass1.top**

---

## 🔧 常用运维命令

### 服务管理

```bash
# 启动服务
sudo systemctl start smartclass1

# 停止服务
sudo systemctl stop smartclass1

# 重启服务
sudo systemctl restart smartclass1

# 查看服务状态
sudo systemctl status smartclass1

# 查看实时日志
sudo journalctl -u smartclass1 -f
```

### 日志查看

```bash
# 应用日志
sudo tail -f /var/log/smartclass1/app.log

# 错误日志
sudo tail -f /var/log/smartclass1/error.log

# Nginx 访问日志
sudo tail -f /var/log/nginx/smartclass1-access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/smartclass1-error.log
```

### 更新部署

```bash
# 1. 停止服务
sudo systemctl stop smartclass1

# 2. 备份当前版本
cd /opt
sudo tar -czf smartclass1-backup-$(date +%Y%m%d).tar.gz smartclass1/

# 3. 更新代码
cd /opt/smartclass1
git pull  # 如果使用 git
# 或重新上传文件

# 4. 更新依赖
source venv/bin/activate
pip install -r requirements.txt

# 5. 重启服务
sudo systemctl start smartclass1
```

---

## 🐛 故障排查

### 问题 1: 服务无法启动

```bash
# 查看详细错误
sudo journalctl -u smartclass1 -n 50

# 检查端口占用
sudo lsof -i :8000

# 检查配置文件
cat /etc/smartclass1/smartclass1.env
```

### 问题 2: WebSocket 连接失败

```bash
# 检查 Nginx 配置
sudo nginx -t

# 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/error.log

# 测试 WebSocket
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" http://localhost:8000/ws/test/1
```

### 问题 3: 数据库连接失败

```bash
# 检查环境变量（应用只读 DATABASE_URL 这一个变量）
sudo cat /etc/smartclass1/smartclass1.env | grep DATABASE_URL

# 从服务器测通连接（本项目是 SQL Server，不是 MySQL）
# 注意 charset 必须是 utf8
python3 -c "import pymssql; c=pymssql.connect(server='host', port=3433, user='u', password='p', database='db', charset='utf8'); print('OK')"

# 如果登录/注册能连上却报错，检查建表是否已完成
cd /opt/smartclass1 && venv/bin/python init_db.py
```

**中文乱码 / 写入后变 `?`**：确认连接串是 `charset=utf8`（不是 `cp936`），
并且中文列是 `NVARCHAR` 而不是 `varchar`（见项目 `docs/README.md` §4.3）。

### 问题 4: SSL 证书问题

```bash
# 检查证书状态
sudo certbot certificates

# 手动续期
sudo certbot renew

# 重新申请证书
sudo certbot --nginx -d smartclass1.top --force-renewal
```

---

## 📊 性能优化

### 1. 系统参数调优

```bash
# 编辑系统参数
sudo nano /etc/sysctl.conf

# 添加以下内容
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
fs.file-max = 65535

# 应用配置
sudo sysctl -p
```

### 2. Nginx 优化

```bash
# 编辑 Nginx 配置
sudo nano /etc/nginx/nginx.conf

# 调整 worker 进程
worker_processes auto;
worker_connections 4096;

# 启用 gzip 压缩
gzip on;
gzip_types text/plain text/css application/json application/javascript;
```

### 3. 应用优化

在 `/etc/smartclass1/smartclass1.env` 中调整:

```bash
# 增加数据库连接池
# 在 database.py 中配置
pool_size=20
max_overflow=10
```

---

## 🔒 安全加固

### 1. 系统安全

```bash
# 禁用 root 登录
sudo nano /etc/ssh/sshd_config
# 设置: PermitRootLogin no

# 安装 fail2ban
sudo apt install fail2ban -y

# 定期更新系统
sudo apt update && sudo apt upgrade -y
```

### 2. 应用安全

- ✅ 所有敏感信息已移到环境变量
- ✅ 配置文件权限设置为 600
- ✅ 使用 HTTPS 加密传输
- ✅ 配置了安全响应头

---

## 📦 备份策略

### 数据库备份

```bash
# 创建备份脚本
sudo nano /opt/backup/backup_db.sh

#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
# 本项目数据库是 SQL Server (MSSQL)，不是 MySQL —— mysqldump 用不了。
# 线上为阿里云 RDS SQL Server：用控制台的备份/快照功能（支持自动备份与备份文件下载）。
# 需要自己导出时用 sqlcmd / bcp，例如:
#   sqlcmd -S <host>,3433 -U <user> -P '<password>' -d <db> \
#          -Q "BACKUP DATABASE [<db>] TO DISK = N'/opt/backup/db_$DATE.bak' WITH INIT"
find /opt/backup -name "db_*.bak" -mtime +7 -delete

# 添加执行权限
sudo chmod +x /opt/backup/backup_db.sh

# 添加到 crontab (每天凌晨 2 点备份)
sudo crontab -e
0 2 * * * /opt/backup/backup_db.sh
```

### 文件备份

```bash
# 备份存储文件
sudo tar -czf /opt/backup/storage_$(date +%Y%m%d).tar.gz /opt/smartclass1/storage/
```

---

## 📞 技术支持

如遇到问题,请检查:

1. **应用日志**: `/var/log/smartclass1/app.log`
2. **错误日志**: `/var/log/smartclass1/error.log`
3. **Nginx 日志**: `/var/log/nginx/smartclass1-error.log`
4. **系统日志**: `sudo journalctl -u smartclass1`

---

## 📚 相关文档

- [项目 README](../README.md)
- [原部署文档](../DEPLOYMENT.md)
- [功能介绍](../功能介绍文档.md)

---

**部署完成后,访问 https://smartclass1.top 即可使用系统!** 🎉
