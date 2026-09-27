#!/bin/bash
#
# 智能协作学习系统 - 一键部署脚本
# 域名: smartclass1.top
# 部署路径: /opt/smartclass1
#

set -e  # 遇到错误立即退出

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置变量
DEPLOY_DIR="/opt/smartclass1"
SERVICE_NAME="smartclass1"
DOMAIN="smartclass1.top"

# 依赖下限（实测）：sqlalchemy>=3.11, fastapi/uvicorn/openai>=3.10
# 即发行版自带的 python3 需 >= 3.11；Ubuntu 22.04(3.10) 及更早、CentOS 7(3.6) 均不满足，
# 需自行安装 python3.12（Ubuntu 走 deadsnakes PPA）后再跑本脚本。
PYTHON_MIN="3.11"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Let's Encrypt 注册邮箱；留空则用 --register-unsafely-without-email
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

# 由 configure_ssl 置位；决定 configure_nginx 装载 HTTPS 还是 HTTP-only 配置
SSL_READY=""

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否为 root 用户
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用 root 用户或 sudo 运行此脚本"
        exit 1
    fi
}

# 检查系统类型，并解析各发行版差异（Web 运行用户 / Nginx 站点目录）
check_system() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        log_info "检测到操作系统: $OS $VERSION"
    else
        log_error "无法检测操作系统类型"
        exit 1
    fi

    # Debian 系 Web 用户是 www-data，RHEL 系是 nginx
    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        WEB_USER="www-data"
        NGINX_SITE_DIR="/etc/nginx/sites-available"
        NGINX_SITE_LINK="/etc/nginx/sites-enabled"
    elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ] || [ "$OS" = "rocky" ] || [ "$OS" = "almalinux" ]; then
        WEB_USER="nginx"
        # RHEL 系没有 sites-available/sites-enabled，站点直接放 conf.d
        NGINX_SITE_DIR="/etc/nginx/conf.d"
        NGINX_SITE_LINK=""
    else
        log_error "不支持的操作系统: $OS"
        exit 1
    fi
    log_info "Web 运行用户: $WEB_USER, Nginx 站点目录: $NGINX_SITE_DIR"
}

# 校验 Python 版本满足依赖下限
check_python() {
    if ! command -v "$PYTHON_BIN" &> /dev/null; then
        log_error "未找到 $PYTHON_BIN，请先安装 Python >= $PYTHON_MIN"
        exit 1
    fi

    local ver
    ver=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    if [ "$(printf '%s\n%s\n' "$PYTHON_MIN" "$ver" | sort -V | head -1)" != "$PYTHON_MIN" ]; then
        log_error "Python $ver 过低，本项目依赖要求 >= $PYTHON_MIN"
        log_error "（sqlalchemy 2.1 要求 >=3.11；Ubuntu 22.04 自带 3.10、CentOS 7 自带 3.6 均不满足）"
        log_error "建议：Ubuntu 加 deadsnakes PPA 装 python3.12，然后 PYTHON_BIN=python3.12 重跑本脚本"
        exit 1
    fi
    log_info "Python 版本满足要求: $ver"
}

# 安装系统依赖
install_dependencies() {
    log_info "开始安装系统依赖..."

    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        apt update
        apt install -y python3 python3-pip python3-venv python3-dev build-essential \
                       ffmpeg nginx certbot python3-certbot-nginx git curl wget
    elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ] || [ "$OS" = "rocky" ] || [ "$OS" = "almalinux" ]; then
        # epel-release 必须最先装 —— 下面 certbot 等包依赖它
        yum install -y epel-release
        # ffmpeg 不在 base/EPEL 里，需要 RPM Fusion
        yum install -y --nogpgcheck \
            "https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %{rhel}).noarch.rpm" \
            || log_warn "RPM Fusion 源安装失败，请手动装 ffmpeg（否则视频抽帧/音频提取不可用）"
        yum update -y
        yum install -y python3 python3-pip python3-devel gcc gcc-c++ ffmpeg nginx \
                       certbot python3-certbot-nginx git curl wget
    else
        log_error "不支持的操作系统: $OS"
        exit 1
    fi

    log_info "系统依赖安装完成"
}

# 创建部署目录
create_directories() {
    log_info "创建部署目录..."

    mkdir -p $DEPLOY_DIR
    mkdir -p /etc/$SERVICE_NAME
    mkdir -p /var/log/$SERVICE_NAME
    mkdir -p $DEPLOY_DIR/storage/{video_chunks,audio_chunks,snapshots}
    mkdir -p $DEPLOY_DIR/storage/{research_models,research_gallery,research_runtime_cache}

    log_info "目录创建完成"
}

# 上传项目文件
upload_project() {
    log_info "准备上传项目文件..."
    log_warn "请手动上传项目文件到 $DEPLOY_DIR"
    log_warn "或使用以下命令从本地上传:"
    echo ""
    echo "  scp -r algorithm-study-master/* root@your-server:$DEPLOY_DIR/"
    echo ""
    echo "  或使用 git clone:"
    echo "  cd $DEPLOY_DIR"
    echo "  git clone <your-repo-url> ."
    echo ""
    read -p "项目文件已上传? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "请先上传项目文件"
        exit 1
    fi
}

# 创建 Python 虚拟环境
create_venv() {
    log_info "创建 Python 虚拟环境..."

    cd $DEPLOY_DIR
    "$PYTHON_BIN" -m venv venv
    source venv/bin/activate

    log_info "升级 pip..."
    pip install --upgrade pip

    log_info "安装 Python 依赖（含 torch 等，体积较大，耗时较长）..."
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt
    else
        log_warn "未找到 requirements.txt, 安装基础依赖..."
        pip install fastapi "uvicorn[standard]" sqlalchemy pymssql python-multipart \
                    openai requests websocket-client websockets aiohttp \
                    numpy opencv-python oss2 librosa resemblyzer
    fi

    # ⚠️ 必须在 requirements 之后执行：webrtcvad（经 resemblyzer 引入）导入
    #    pkg_resources，而 setuptools>=81 已删除该模块，否则 server.py 启动即崩。
    log_info "锁定 setuptools<81（webrtcvad 需要 pkg_resources）..."
    pip install "setuptools<81"

    deactivate
    log_info "Python 环境配置完成"
}

# 配置环境变量
configure_env() {
    log_info "配置环境变量..."

    if [ -f $DEPLOY_DIR/deploy/smartclass1.env.example ]; then
        cp $DEPLOY_DIR/deploy/smartclass1.env.example /etc/$SERVICE_NAME/$SERVICE_NAME.env
        log_warn "请编辑 /etc/$SERVICE_NAME/$SERVICE_NAME.env 填写实际配置"
        log_warn "必须配置: DATABASE_URL, LLM_API_KEY, ALIYUN_* 等"
        echo ""
        read -p "是否现在编辑配置文件? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            ${EDITOR:-nano} /etc/$SERVICE_NAME/$SERVICE_NAME.env
        fi
    else
        log_error "未找到环境变量模板文件"
        exit 1
    fi
}

# 配置 Systemd 服务
configure_systemd() {
    log_info "配置 Systemd 服务..."

    if [ ! -f "$DEPLOY_DIR/deploy/$SERVICE_NAME.service" ]; then
        log_error "未找到 Systemd 服务文件"
        exit 1
    fi

    # 单元文件里 User 写的是 www-data，RHEL 系需换成 nginx
    sed "s/^User=www-data/User=$WEB_USER/; s/^Group=www-data/Group=$WEB_USER/" \
        "$DEPLOY_DIR/deploy/$SERVICE_NAME.service" > "/etc/systemd/system/$SERVICE_NAME.service"

    # StandardOutput=append: 需要 systemd >= 240（Ubuntu 20.04 是 245，CentOS 7 只有 219）。
    # 低版本会被 systemd 拒绝加载，这里降级为仅走 journald。
    local sysd_ver
    sysd_ver=$(systemctl --version | head -1 | awk '{print $2}')
    if [ "${sysd_ver:-0}" -lt 240 ] 2>/dev/null; then
        log_warn "systemd $sysd_ver < 240，不支持 StandardOutput=append:，改用 journald 收日志"
        sed -i '/^StandardOutput=/d; /^StandardError=/d' "/etc/systemd/system/$SERVICE_NAME.service"
        log_warn "该机器上请用 journalctl -u $SERVICE_NAME 查看日志（不会有 /var/log/$SERVICE_NAME/*.log）"
    fi

    systemctl daemon-reload
    log_info "Systemd 服务配置完成"
}

# 把站点文件接入 Nginx（Debian 系走 sites-enabled 软链，RHEL 系放 conf.d 即可）
_enable_site() {
    if [ -n "$NGINX_SITE_LINK" ]; then
        mkdir -p "$NGINX_SITE_LINK"
        [ -L "$NGINX_SITE_LINK/$SERVICE_NAME" ] || \
            ln -s "$NGINX_SITE_DIR/$SERVICE_NAME" "$NGINX_SITE_LINK/"
    fi
}

# 第一步：先只装 HTTP 配置，让 certbot 能做 webroot 校验
# 为什么不能直接装正式的 HTTPS 配置：那份配置引用了 /etc/letsencrypt/live/... 下的证书，
# 而首次部署时证书还不存在，nginx -t 会直接报 "cannot load certificate" 并失败，
# 于是永远走不到申请证书那一步（先有鸡还是先有蛋）。
bootstrap_http_nginx() {
    log_info "写入临时 HTTP 配置（供 certbot 校验）..."

    mkdir -p /var/www/certbot
    cat > "$NGINX_SITE_DIR/$SERVICE_NAME" <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 200 'bootstrap ok'; add_header Content-Type text/plain; }
}
EOF

    _enable_site

    if ! nginx -t; then
        log_error "临时 Nginx 配置测试失败"
        exit 1
    fi

    systemctl enable nginx >/dev/null 2>&1 || true
    systemctl reload nginx >/dev/null 2>&1 || systemctl start nginx >/dev/null 2>&1 || true
    log_info "临时 Nginx 已就绪"
}

# 第二步：申请证书（webroot 方式，不依赖 443 配置）
configure_ssl() {
    log_info "配置 SSL 证书..."

    if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        log_info "检测到已有证书，跳过申请"
        SSL_READY="1"
        return 0
    fi

    read -p "是否申请 Let's Encrypt SSL 证书? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_warn "跳过 SSL 申请；站点将仅能通过 http:// 访问"
        SSL_READY="0"
        return 0
    fi

    local email_args
    if [ -n "$CERTBOT_EMAIL" ]; then
        email_args="--email $CERTBOT_EMAIL"
    else
        log_warn "未设置 CERTBOT_EMAIL，将不提供邮箱注册（无法接收证书到期提醒）"
        email_args="--register-unsafely-without-email"
    fi

    if certbot certonly --webroot -w /var/www/certbot \
            -d "$DOMAIN" -d "www.$DOMAIN" \
            --non-interactive --agree-tos $email_args --keep-until-expiring; then
        log_info "SSL 证书申请成功"
        SSL_READY="1"
    else
        log_warn "SSL 证书申请失败；站点将仅能通过 http:// 访问，稍后可重跑本脚本重试"
        SSL_READY="0"
    fi
}

# 第三步：证书就绪后，再装载正式的 HTTPS 配置
configure_nginx() {
    if [ "$SSL_READY" != "1" ]; then
        log_warn "无可用证书，保留 HTTP-only 配置（$NGINX_SITE_DIR/$SERVICE_NAME）"
        log_warn "拿到证书后重新运行本脚本即可切换为 HTTPS"
        return 0
    fi

    log_info "配置 Nginx (HTTPS)..."

    if [ ! -f "$DEPLOY_DIR/deploy/nginx-smartclass1.conf" ]; then
        log_error "未找到 Nginx 配置文件"
        exit 1
    fi

    # 模板里的域名硬编码为 smartclass1.top，这里按实际 DOMAIN 替换
    sed "s/smartclass1\.top/$DOMAIN/g" \
        "$DEPLOY_DIR/deploy/nginx-smartclass1.conf" > "$NGINX_SITE_DIR/$SERVICE_NAME"

    _enable_site

    if nginx -t; then
        log_info "Nginx 配置测试通过"
        systemctl reload nginx >/dev/null 2>&1 || true
    else
        log_error "Nginx 配置测试失败"
        exit 1
    fi
}

# 配置防火墙
configure_firewall() {
    log_info "配置防火墙..."

    if command -v ufw &> /dev/null; then
        ufw allow 22/tcp
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw --force enable
        log_info "UFW 防火墙配置完成"
    elif command -v firewall-cmd &> /dev/null; then
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        log_info "Firewalld 防火墙配置完成"
    else
        log_warn "未检测到防火墙,请手动配置"
    fi
}

# 设置文件权限
set_permissions() {
    log_info "设置文件权限..."

    chown -R "$WEB_USER:$WEB_USER" $DEPLOY_DIR
    chmod -R 755 $DEPLOY_DIR
    chmod 600 /etc/$SERVICE_NAME/$SERVICE_NAME.env
    mkdir -p /var/log/$SERVICE_NAME
    chown -R "$WEB_USER:$WEB_USER" /var/log/$SERVICE_NAME

    log_info "文件权限设置完成"
}

# 启动服务
start_services() {
    log_info "启动服务..."

    # 启动应用服务
    systemctl enable $SERVICE_NAME
    systemctl start $SERVICE_NAME

    # 重启 Nginx
    systemctl restart nginx

    # 检查服务状态
    sleep 3
    if systemctl is-active --quiet $SERVICE_NAME; then
        log_info "应用服务启动成功"
    else
        log_error "应用服务启动失败,请检查日志: journalctl -u $SERVICE_NAME -n 50"
        exit 1
    fi

    if systemctl is-active --quiet nginx; then
        log_info "Nginx 服务运行正常"
    else
        log_error "Nginx 服务异常"
        exit 1
    fi
}

# 显示部署信息
show_info() {
    echo ""
    echo "=========================================="
    log_info "部署完成!"
    echo "=========================================="
    echo ""
    if [ "$SSL_READY" = "1" ]; then
        echo "访问地址: https://$DOMAIN"
    else
        echo "访问地址: http://$DOMAIN   ⚠️ 未配置 SSL，仅 HTTP"
    fi
    echo "部署目录: $DEPLOY_DIR"
    echo "配置文件: /etc/$SERVICE_NAME/$SERVICE_NAME.env"
    echo "服务名称: $SERVICE_NAME"
    echo ""
    echo "常用命令:"
    echo "  查看服务状态: systemctl status $SERVICE_NAME"
    echo "  查看应用日志: tail -f /var/log/$SERVICE_NAME/app.log"
    echo "  查看错误日志: tail -f /var/log/$SERVICE_NAME/error.log"
    echo "  重启服务: systemctl restart $SERVICE_NAME"
    echo "  重启 Nginx: systemctl restart nginx"
    echo ""
    echo "=========================================="
}

# 主函数
main() {
    log_info "开始部署智能协作学习系统..."
    echo ""

    check_root
    check_system
    install_dependencies
    check_python
    create_directories
    upload_project
    create_venv
    configure_env
    configure_systemd
    # 先 HTTP 让 certbot 能校验，再申请证书，最后才装载引用证书的 HTTPS 配置
    bootstrap_http_nginx
    configure_ssl
    configure_nginx
    configure_firewall
    set_permissions
    start_services
    show_info

    log_info "部署流程全部完成!"
}

# 执行主函数
main
