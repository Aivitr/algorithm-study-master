# 智能协作学习系统 - 服务器部署指南

> **本地开发请走容器**：[`docker.md`](docker.md)（阶段 5）。
> 本文件描述的是 **systemd + nginx 的线上部署路线**，仍然有效、未被取代；
> 容器化的线上部署方案尚未定案，见 `docker.md` 文末代办。

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
pip install fastapi uvicorn[standard] sqlalchemy pymssql opencv-python numpy openai aiohttp websockets python-multipart
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
# 数据库连接 (修改为你的实际数据库信息 —— 注意是 MSSQL，不是 MySQL)
DATABASE_URL=mssql+pymssql://username:password@host:1433/database?charset=utf8

# DeepSeek API 密钥
LLM_API_KEY=sk-your-deepseek-api-key

# 阿里云语音识别
ALIYUN_ACCESS_KEY_ID=your-access-key-id
ALIYUN_ACCESS_KEY_SECRET=your-access-key-secret
ALIYUN_APP_KEY=your-app-key

# 阿里云 OSS (可选)
OSS_ACCESS_KEY_ID=your-oss-key-id
OSS_ACCESS_KEY_SECRET=your-oss-key-secret
OSS_BUCKET_NAME=your-bucket-name
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
```

**保护配置文件:**

```bash
sudo chmod 600 /etc/smartclass1/smartclass1.env
```

**初始化数据库（生产侧，用统一的建库脚本）:**

```bash
# 与本地开发用的是同一份 db/schema.sql —— 这是刻意的，两边不会漂移。
# 脚本**可重复执行**：每条 CREATE 都有 IF 守卫并自带 USE，对已有库是无操作。
sqlcmd -S <RDS主机> -U <用户> -P '<口令>' -d master -C -b -f 65001 -i db/schema.sql
```

`-C` 表示信任服务器证书，`-b` 让出错时返回非零退出码，`-f 65001` 指定输入为 UTF-8
（脚本里有中文字符串，不加会乱码）。库名与排序规则由脚本头部决定；
若目标库已存在且排序规则不是 `Chinese_PRC_CI_AS`，脚本不会改它 —— 需要人工确认。

> 该脚本是生产结构的**冻结快照**，模型改了它不会自己跟。重新生成用
> `python tools/export_prod_schema.py --yes`（用法见该脚本文件头）。

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
# 检查数据库连接（SQL Server 用 sqlcmd，不是 mysql 客户端）
sqlcmd -S host,1433 -U username -P password -d cscl_db -C -Q "SELECT 1"

# 检查环境变量
sudo cat /etc/smartclass1/smartclass1.env | grep DATABASE_URL
```

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

⚠️ **本节原给的是 `mysqldump` 脚本，对 SQL Server 完全无效**（该命令是 MySQL 的工具，
本系统的库是 SQL Server 2022）。原文已移除，**不是**改成另一段现成脚本——
线上的库是**阿里云 RDS**，其备份方式（自动备份策略、时间点恢复、`BACKUP DATABASE`
是否可用）**以阿里云控制台与服务商文档为准**，写死一段在这里反而会误导。

需要手工备份时，先用 `sqlcmd` 确认连通，再按服务商的备份方案执行：

```bash
sqlcmd -S <host>,1433 -U <user> -P <password> -d cscl_db -C -Q "SELECT 1"
```

另注：`db/schema.sql` 是**表结构的冻结快照**，不是数据备份——它能让空库长出同样的表，
但里面没有一行业务数据，不能拿去顶替备份。

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
- [原部署文档](../docs/DEPLOYMENT.md)
- [功能介绍](../docs/功能介绍文档.md)

---

**部署完成后,访问 https://smartclass1.top 即可使用系统!** 🎉
