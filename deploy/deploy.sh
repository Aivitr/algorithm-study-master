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
PYTHON_VERSION="3.8"

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

# 检查系统类型
check_system() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        log_info "检测到操作系统: $OS $VERSION"
    else
        log_error "无法检测操作系统类型"
        exit 1
    fi
}

# 安装系统依赖
install_dependencies() {
    log_info "开始安装系统依赖..."

    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        apt update
        apt install -y python3 python3-pip python3-venv ffmpeg nginx certbot python3-certbot-nginx git curl wget
    elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ]; then
        yum update -y
        yum install -y python3 python3-pip ffmpeg nginx certbot python3-certbot-nginx git curl wget
        yum install -y epel-release
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
    python3 -m venv venv
    source venv/bin/activate

    log_info "升级 pip..."
    pip install --upgrade pip

    log_info "安装 Python 依赖..."
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt
    else
        log_warn "未找到 requirements.txt, 安装基础依赖..."
        pip install fastapi uvicorn[standard] sqlalchemy pymssql opencv-python numpy openai aiohttp websockets python-multipart
    fi

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

    if [ -f $DEPLOY_DIR/deploy/$SERVICE_NAME.service ]; then
        cp $DEPLOY_DIR/deploy/$SERVICE_NAME.service /etc/systemd/system/
        systemctl daemon-reload
        log_info "Systemd 服务配置完成"
    else
        log_error "未找到 Systemd 服务文件"
        exit 1
    fi
}

# 配置 Nginx
configure_nginx() {
    log_info "配置 Nginx..."

    if [ -f $DEPLOY_DIR/deploy/nginx-smartclass1.conf ]; then
        cp $DEPLOY_DIR/deploy/nginx-smartclass1.conf /etc/nginx/sites-available/$SERVICE_NAME

        # 创建软链接
        if [ ! -L /etc/nginx/sites-enabled/$SERVICE_NAME ]; then
            ln -s /etc/nginx/sites-available/$SERVICE_NAME /etc/nginx/sites-enabled/
        fi

        # 测试配置
        nginx -t
        if [ $? -eq 0 ]; then
            log_info "Nginx 配置测试通过"
        else
            log_error "Nginx 配置测试失败"
            exit 1
        fi
    else
        log_error "未找到 Nginx 配置文件"
        exit 1
    fi
}

# 配置 SSL 证书
configure_ssl() {
    log_info "配置 SSL 证书..."

    read -p "是否配置 Let's Encrypt SSL 证书? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "开始申请 SSL 证书..."
        certbot --nginx -d $DOMAIN -d www.$DOMAIN

        if [ $? -eq 0 ]; then
            log_info "SSL 证书配置成功"
        else
            log_warn "SSL 证书配置失败,请稍后手动配置"
        fi
    else
        log_warn "跳过 SSL 证书配置,请稍后手动配置"
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

    chown -R www-data:www-data $DEPLOY_DIR
    chmod -R 755 $DEPLOY_DIR
    chmod 600 /etc/$SERVICE_NAME/$SERVICE_NAME.env
    chown -R www-data:www-data /var/log/$SERVICE_NAME

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
    echo "访问地址: https://$DOMAIN"
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
    create_directories
    upload_project
    create_venv
    configure_env
    configure_systemd
    configure_nginx
    configure_ssl
    configure_firewall
    set_permissions
    start_services
    show_info

    log_info "部署流程全部完成!"
}

# 执行主函数
main
