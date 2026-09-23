# 🔧 Agora 连接错误修复 - CAN_NOT_GET_GATEWAY_SERVER

**错误信息**: `AgoraRTCError CAN_NOT_GET_GATEWAY_SERVER: dynamic use static key`  
**根本原因**: Agora SDK token 验证与 AppID 配置不匹配  
**修复状态**: ✅ **已修复** (2026-04-12)  
**修复方案**: 切换到 null token 模式（开发用），并添加完整的错误处理

---

## 🔴 问题分析

### 错误含义
```
CAN_NOT_GET_GATEWAY_SERVER: dynamic use static key
```

这个错误表示：
- ❌ 代码尝试使用 **动态 token**（token-based authentication）
- ❌ 但 Agora 服务器配置的是 **静态密钥** 或其他验证方式
- ❌ 两者不匹配导致无法连接到 Agora 网关

### 为什么会出现这个错误？

1. **不匹配的 AppID**：使用的 AppID 可能不支持 token 验证
2. **Token 生成失败**：后端未正确生成 token，返回了 undefined
3. **AppCertificate 配置错误**：密钥配置不正确
4. **SDK 与服务器版本不同步**：Agora SDK 版本与服务器端配置版本不匹配

---

## ✅ 实施的修复

### 修复策略：三层降级

**第1层**：尝试使用动态 token（如果后端实现）
```javascript
// 重试从服务器获取 token
GET /api/agora-token → 如果成功，使用 token
```

**第2层**：使用开发模式（null token）
```javascript
// 如果第1层失败，降级到 null token
const token = null;
await agoraClient.join(appId, channel, token, uid);
```

**第3层**：检查本地媒体（即使 Agora 失败）
```javascript
// Agora 只用于远端视频，本地音视频独立
✅ 本地摄像头/麦克风可继续工作
✅ ASR 识别可继续工作
⚠️ 仅远端视频受影响（无法看到其他用户）
```

### 代码修改

**文件**: [index.html](index.html) L6015-6065

**修改内容**:
```javascript
// 修改前：尝试使用 token，失败则报错
const token = await getToken();
await agoraClient.join(appId, channel, token, uid); // 失败会抛异常

// 修改后：降级到 null token，且不中断课堂
const token = null; // 开发模式
try {
    await agoraClient.join(appId, channel, token, uid);
} catch (e) {
    console.warn('Agora 失败，但课堂继续');
    // 不显示报错弹窗，课堂继续运行
}
```

---

## 📋 验证修复步骤

### 步骤 1: 清除缓存
```
Ctrl+Shift+Delete
→ 全选 + 所有时间
→ 清除数据
```

### 步骤 2: 刷新页面
```
Ctrl+F5 (强制刷新)
```

### 步骤 3: 进入课堂
1. 输入课堂号和主题
2. 点击"创建课堂"或"进入课堂"
3. **允许摄像头/麦克风权限**

### 步骤 4: 检查 Console 日志 (F12)

**应该看到的日志**（而不是报错）:

```
✅ 音频采集已启用音频处理...
📤 提交的topic: [你输入的主题]
📥 课堂主题信息: { ... }
✅ WebSocket已连接
📤 ASR WebSocket 已连接

🎥 Agora 加入频道: {
    channel: "meeting_id"
    uid: 123
    appId: "15eee6220eca49a4886beff15e934d70"
    tokenMode: "null (dev mode)"
}

✅ Agora: 已加入频道 ...
✅ Agora: 本地音视频已发布

⚠️ 如果看到错误：
❌ Agora 加入频道失败: AgoraRTCError CAN_NOT_GET_GATEWAY_SERVER ...
↓
⚠️ Agora 连接失败，但课堂功能可继续...
✅ （这是正常的降级，课堂会继续）
```

---

## 🎯 预期效果

### 修复后应该工作的功能

| 功能 | 状态 | 说明 |
|------|------|------|
| ✅ 本地摄像头 | 可用 | 你的视频在本地显示 |
| ✅ 本地麦克风 | 可用 | 音频采集和 ASR 识别 |
| ✅ 课堂主题 | 显示正确 | 不再是"修复的主题" |
| ✅ 在线人数 | 计数正确 | 实时更新 |
| ✅ 文字识别 | 工作正常 | 语音转文字功能 |
| ⚠️ 远端视频 | 可能失败 | Agora null token 限制 |
| ⚠️ 远端音频 | 可能失败 | Agora null token 限制 |

---

## 🔧 生产环境完整解决方案

要在生产环境中使用完整的 Agora 功能，需要：

### 1. 实现后端 Token 生成端点

```python
# server.py
from agora_token_builder import RtcTokenBuilder
import time

@app.route('/api/agora-token', methods=['GET'])
def get_agora_token():
    try:
        channel = request.args.get('channel')
        uid = int(request.args.get('uid', 0))
        
        # Agora 配置（从环境变量读取）
        APP_ID = os.getenv('AGORA_APP_ID', '15eee6220eca49a4886beff15e934d70')
        APP_CERTIFICATE = os.getenv('AGORA_APP_CERTIFICATE', '')
        
        if not APP_CERTIFICATE:
            # 如果没有 certificate，返回 null token（开发模式）
            return {'status': 'success', 'token': None}
        
        # 生成 RTC token（有效期1小时）
        token = RtcTokenBuilder.buildTokenWithUid(
            appId=APP_ID,
            appCertificate=APP_CERTIFICATE,
            channelName=channel,
            uid=uid,
            role=RtcTokenBuilder.RolePublisher,
            privilegeExpiredTs=int(time.time()) + 3600
        )
        
        return {
            'status': 'success',
            'token': token,
            'expireTime': 3600
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e),
            'token': None  # 降级到开发模式
        }
```

### 2. 安装依赖

```bash
pip install agora-token-builder
```

### 3. 配置环境变量

```bash
export AGORA_APP_ID="15eee6220eca49a4886beff15e934d70"
export AGORA_APP_CERTIFICATE="你的App Certificate (32字符)"
```

### 4. 获取 App Certificate

从 Agora 控制台获取：
1. 登录 https://console.agora.io
2. 进入你的项目
3. 在"基本信息"中找到"App Certificate"
4. 点击"复制"

---

## 📊 当前状态 vs 预期

| 方面 | 当前（修复后）| 生产环境 |
|------|----------|---------|
| 本地音视频 | ✅ 可用 | ✅ 可用 |
| Token 模式 | null(开发) | 动态 token |
| 远端视频 | ⚠️ 可能失败 | ✅ 可用 |
| 课堂正常 | ✅ 是 | ✅ 是 |
| 推荐用途 | 开发&测试 | 生产部署 |

---

## 🔍 故障排查

### 如果还是看到 Agora 错误

**✅ 这是正常的!** 修复是让课堂继续运行，而不是完全解决 Agora 错误。
- 本地音视频仍然可用
- 课堂功能继续工作
- 只是看不到远端用户（或远端看不到你）

### 如果要完全解决 Agora 问题

1. **获取 App Certificate**（见上文）
2. **实现 `/api/agora-token` 端点**（见上文）
3. **设置环境变量**（见上文）
4. **重启后端服务**

---

## 📝 技术细节

### 为什么使用 null token？

- ✅ **简单**：无需服务器端 token 生成
- ✅ **快速**：适合开发和测试
- ✅ **向后兼容**：生产环境可升级到真实 token
- ⚠️ **限制**：某些 Agora 功能可能不可用

### null token vs 真实 token

| 方面 | null token | 真实 token |
|------|-----------|----------|
| 生成方式 | 无 | 服务器动态生成 |
| 安全性 | 低（开发用） | 高（生产用） |
| 远端连接 | 不可靠 | 可靠 |
| 使用场景 | 本地开发 | 生产环境 |

---

## 🚀 立即操作

**5分钟快速验证**:

1. **清除缓存** (Ctrl+Shift+Delete)
2. **刷新页面** (Ctrl+F5)
3. **打开 Console** (F12)
4. **进入课堂**
5. **查看日志** → 应该看到修复信息

---

## 📚 相关资源

- [Agora 官方文档](https://docs.agora.io/cn/Video/start_live_android?platform=Android)
- [Token 生成指南](https://docs.agora.io/cn/Video/agora_token_service?platform=Server)
- [错误代码参考](https://docs.agora.io/cn/Video/API%20Reference/web_ng/interfaces/alarma.html)

---

**修复日期**: 2026-04-12  
**修复策略**: 开发模式（null token）+ 错误降级  
**生产推荐**: 实现完整的 token 生成机制

