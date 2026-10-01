# 阿里云OSS配置指南

## 🚀 快速开始

### 第一步：登录阿里云控制台

1. 访问 [阿里云控制台](https://oss.console.aliyun.com/)
2. 搜索"对象存储OSS"并进入

### 第二步：创建Bucket

1. 点击"创建Bucket"按钮
2. 填写以下配置：
   - **Bucket名称**：`collaborative-learning-videos`（或自定义名称，需全局唯一）
   - **地域**：选择离您最近的（如：华东1-杭州）
   - **存储类型**：**标准存储**
   - **读写权限**：**公共读**（⚠️ 重要！允许直接访问视频）
   - **服务器端加密**：关闭（可选）
   - 其他保持默认
3. 点击"确定"完成创建

### 第三步：获取AccessKey

1. 点击右上角头像 → **AccessKey管理**
2. 点击"创建AccessKey"
3. ⚠️ **重要**：记录 **AccessKey ID** 和 **AccessKey Secret**（只显示一次！）

### 第四步：配置项目

1. 打开 `oss_config.py` 文件
2. 填写您的配置信息：

```python
# AccessKey ID（在阿里云控制台获取）
OSS_ACCESS_KEY_ID = "LTAI5t你的AccessKeyID"

# AccessKey Secret
OSS_ACCESS_KEY_SECRET = "你的AccessKeySecret密钥"

# Bucket名称（在OSS控制台创建的Bucket）
OSS_BUCKET_NAME = "collaborative-learning-videos"

# OSS Endpoint（根据你的Bucket地域选择）
OSS_ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"
```

3. 保存文件

### 第五步：测试OSS连接

重启服务器，如果看到以下日志说明配置成功：

```
✅ OSS模块导入成功
✅ OSS初始化成功: collaborative-learning-videos
```

---

## 📊 成本估算

- **存储费用**：0.12元/GB/月
- **外网流出流量**：0.50元/GB
- **外网流入流量**：免费
- **请求次数**：PUT/POST 0.01元/万次，GET 0.01元/万次

### 示例计算

如果您有100GB视频，每月10GB下载流量：
- 存储费用：100GB × 0.12元 = 12元
- 流量费用：10GB × 0.50元 = 5元
- **总计：17元/月**

---

## 🔧 Endpoint 地域对照表

| 地域 | Endpoint |
|------|----------|
| 华东1（杭州） | oss-cn-hangzhou.aliyuncs.com |
| 华东2（上海） | oss-cn-shanghai.aliyuncs.com |
| 华北1（青岛） | oss-cn-qingdao.aliyuncs.com |
| 华北2（北京） | oss-cn-beijing.aliyuncs.com |
| 华北3（张家口） | oss-cn-zhangjiakou.aliyuncs.com |
| 华南1（深圳） | oss-cn-shenzhen.aliyuncs.com |

完整列表：https://help.aliyun.com/zh/oss/user-guide/regions-and-endpoints

---

## ✅ 功能说明

配置完成后，系统会自动：

1. **上传视频和快照到OSS**
   - 说话时自动上传视频和快照
   - 静默时有情绪变化也上传快照

2. **删除本地临时文件**
   - 上传成功后自动删除本地文件
   - 节省本地存储空间

3. **从OSS播放视频**
   - 点击情绪点查看视频时，直接从OSS加载
   - 支持秒开（HTTP Range Requests）

---

## 🐛 常见问题

### Q1: 提示"OSS模块未配置"？
**A**: 检查以下内容：
- `oss_config.py` 文件是否存在
- AccessKey ID 和 Secret 是否填写正确
- 是否安装了 `oss2` 库（`pip install oss2`）

### Q2: 上传失败，提示"权限不足"？
**A**: 检查 AccessKey 权限：
- 登录阿里云控制台 → RAM访问控制
- 检查子用户是否有 OSS 完整权限
- 或使用主账号的 AccessKey

### Q3: 视频播放失败，提示"跨域错误"？
**A**: 配置 Bucket 的跨域规则（CORS）：
1. 进入 OSS 控制台 → 选择 Bucket
2. 点击"权限管理" → "跨域设置"
3. 添加规则：
   - 来源：`*`
   - 方法：GET, POST, HEAD
   - 允许 Headers：`*`
   - 暴露 Headers：`ETag, Content-Range`

### Q4: 如何暂时关闭OSS功能？
**A**: 有两种方法：
1. **重命名配置文件**：将 `oss_config.py` 改名为 `oss_config.py.bak`
2. **删除导入**：在 `server.py` 中注释掉 OSS 相关导入

系统会自动切换回本地存储模式。

---

## 📝 数据迁移

### 从本地迁移到OSS

如果您已有本地视频，需要迁移到OSS：

```python
# 运行迁移脚本（可选）
import os
import oss2
from oss_config import *

auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)

local_dir = "storage/video_chunks"
for filename in os.listdir(local_dir):
    if filename.endswith('.webm'):
        local_path = os.path.join(local_dir, filename)
        oss_path = f"{VIDEO_PREFIX}{filename}"
        bucket.put_object_from_file(oss_path, local_path)
        print(f"✅ 已迁移: {filename}")
```

---

## 🎉 完成！

配置完成后，重启服务器，享受云端视频存储和秒开播放体验！

如有问题，请检查服务器日志中的 OSS 相关输出。
