# 智能协作学习系统

## 快速开始（容器，一条命令）

```bash
cp .env.example .env              # 填入密钥，见下方"必填项"
cp .env.dev.example .env.dev      # 开发库指向，照抄即可，不用改
docker compose up --build
```

打开 <http://127.0.0.1:8000>。

`up` 会按顺序拉起三个服务：`db`（SQL Server 2022，数据落命名卷）、
`db-init`（一次性跑 `db/schema.sql` 建库，跑完退出）、`app`。

**必填项**——只有这两处，其余 50 个键都有默认值：

| 位置 | 键 | 不填会怎样 |
|---|---|---|
| `.env` | `LLM_API_KEY` | `import server` 直接抛 `OpenAIError`，容器起不来。只想看看页面可以给假值 |
| `.env.dev` | 整份 | compose 里是 `required: true`，缺了当场报错。`cp .env.dev.example .env.dev` 即可 |

数据库指向**按环境分层**：`.env.dev` 连本机容器（`dev`），`.env.prod` 连线上 RDS（`prod`），
由 `APP_ENV` 选择。两份都**不进版本库**，仓库里只有它们的 `.example` 模板。
细节（含"为什么不用 MySQL 顶替"）见 `deploy/docker.md`。

> 代价：`db` 镜像 2.31 GB，常驻约 2 GB 内存。不用时 `docker compose stop db`。

## 运行（不用容器，手工装环境）

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

打开 `http://127.0.0.1:8000`

## 配置
- 复制 `.env.example` 为 `.env`
- 数据库指向放在 `.env.dev`（本机）或 `.env.prod`（线上），见上方快速开始
- 需要线上 AI / 阿里云 / OSS 时再填写对应环境变量

## 可选依赖
- 阿里本地语音识别 `requirements_funasr.txt`
- 性能优化/GPU加速 `requirements_enhanced_runtime.txt`

## 项目简介

这是一个基于AI技术的智能协作学习平台,通过实时音视频分析、自然语言处理和情绪识别技术,为师生提供智能化的教学支持与学习评估。系统支持教师/学生多角色协作,实现教学过程的全程智能监控、即时反馈和数据分析。

## 核心功能

### 🎓 教师功能
- **智能教学设计生成**: 输入课题和参考资料,AI自动生成教学目标、分工策略和阶段性成就指标
- **实时监控看板**: 监控所有学生的情绪变化、参与积极性、话题关联度
- **学习报告生成**: 自动生成每个学生的学习报告,包含情绪分析、学习表现、不足点和改进建议
- **习题智能生成**: 根据学生薄弱点自动生成10-15道个性化练习题
- **心理健康评估**: 基于情绪波动和行为模式分析潜在心理问题
- **知识图谱可视化**: 自动构建课堂讨论的知识关系网络

### 👨‍🎓 学生功能
- **实时协作学习**: 视频音频实时采集,支持10-50人同时在线
- **智能提示反馈**: AI实时分析发言内容,提供学习引导和思维拓展建议
- **实时字幕显示**: 语音转文字内容直接显示在视频画面底部
- **知识点追踪**: 实时显示课堂知识点完成情况
- **专注度监测**: 实时计算并显示话题关联度和学习投入程度
- **个人学习报告**: 课后查看详细的学习报告和个性化习题

### 🤖 AI能力
- **LLM服务**: DeepSeek API驱动的教学设计、内容分析、习题生成
- **语音识别**: 阿里云语音识别服务,实时语音转文字
- **视觉分析**: OpenCV + Haar级联分类器实现人脸检测和情绪识别
- **知识图谱**: 自动从对话中提取概念和关系,构建可视化知识网络

## 技术架构

### 后端技术栈
- **框架**: FastAPI + WebSocket
- **数据库**: MySQL (远程数据库)
- **AI服务**: DeepSeek LLM + 阿里云语音识别
- **视觉处理**: OpenCV + NumPy
- **音视频处理**: FFmpeg

### 前端技术栈
- **框架**: Vue.js 2.x
- **样式**: TailwindCSS
- **图表**: ECharts (知识图谱可视化)
- **通信**: WebSocket + Axios

## 快速开始

### 1. 环境要求
- Python 3.8+
- FFmpeg 4.3+
- MySQL 5.7+ (或使用远程数据库)

### 2. 安装依赖


# 克隆项目
git clone <your-repo-url>
cd algorithm-study-master

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境 (Windows)
venv\Scripts\activate
# 激活虚拟环境 (Linux/Mac)
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt


### 3. 配置数据库和API密钥

编辑 `database.py`:

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://username:password@host:port/database"


编辑 `llm_service.py`:

API_KEY = "your-deepseek-api-key"


### 4. 启动服务


python server.py


访问 `http://localhost:8000`

### 5. 测试并发性能


python test_concurrent_users.py


## 项目结构


algorithm-study-master/
├── server.py                      # 主服务器
├── database.py                    # 数据库模型
├── llm_service.py                 # LLM服务
├── knowledge_graph_service.py     # 知识图谱服务
├── video_processor.py             # 视频处理
├── ai_core.py                     # AI核心功能
├── index.html                     # 前端界面
├── test_concurrent_users.py       # 并发测试脚本
├── DEPLOYMENT.md                  # 部署文档
├── requirements.txt               # Python依赖
├── 1/                             # 语音识别模块
│   ├── aliyun.py
│   ├── service_aliyun.py
│   └── ...
└── storage/                       # 临时存储目录
    ├── video_chunks/
    ├── audio_chunks/
    └── snapshots/


## 数据库表结构

### 核心表
- **users**: 用户信息 (支持teacher/student角色)
- **meetings**: 课堂信息 (包含教学设计、知识点)
- **transcripts**: 对话记录 (实时语音转文字)
- **emotion_logs**: 情绪日志
- **ai_insights**: AI提示记录

### 扩展表
- **knowledge_graphs**: 知识图谱数据
- **graph_nodes**: 图谱节点
- **graph_edges**: 图谱边
- **learning_reports**: 学习报告
- **exercises**: 习题库
- **student_answers**: 学生作答记录
- **mental_health_assessments**: 心理健康评估

## API接口

### 登录相关
- `POST /login` - 登录或创建课堂

### 课堂功能
- `GET /summary?meeting_id=<id>` - 获取课堂总结
- `GET /api/knowledge-graph/<meeting_id>` - 获取知识图谱
- `POST /api/generate-report` - 生成学习报告
- `GET /api/reports/<user_id>` - 获取用户所有报告

### WebSocket
- `WS /ws/<username>/<meeting_id>` - 实时通信

## 部署指南


### 生产环境部署要点
1. 使用Nginx反向代理
2. 配置SSL证书(Let's Encrypt)
3. 使用Systemd管理服务
4. 配置日志轮转
5. 设置防火墙规则
6. 数据库定期备份


## 使用示例

### 教师创建课堂
1. 选择"教师"角色
2. 输入课堂号和主题
3. AI自动生成教学设计
4. 学生使用课堂号加入

### 学生加入课堂
1. 选择"学生"角色
2. 输入课堂号
3. 授权摄像头和麦克风
4. 开始协作学习

### 课堂互动
- 学生发言自动转文字并显示在视频底部
- AI实时分析话题关联度并给出提示
- 知识点完成自动标记
- 情绪异常自动记录

### 课后分析
- 教师查看每个学生的学习报告
- 学生查看个人报告和习题
- 查看知识图谱了解讨论结构

## 许可证

MIT License

## 联系方式

如有问题或建议,请通过以下方式联系:
- 邮箱: dai13576381980@qq.com


致谢

- DeepSeek: LLM服务提供
- 阿里云: 语音识别服务
- OpenCV: 视觉处理库
- FastAPI: 高性能Web框架
- Vue.js: 前端框架

